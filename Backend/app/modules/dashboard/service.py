"""Aggregation logic for the best-selling products dashboard."""

from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Date, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import InventoryItem, InventoryStatus, ProductFamily, ProductIdentity, ProductVariant
from app.models.entities import Customer
from app.modules.dashboard.schemas import (
    BestSellingProductDetail,
    BestSellingProductRow,
    BestSellingProductsResponse,
    BestSellingSummary,
    DataQualityWarning,
    PlatformBreakdownRow,
    RecentOrderRow,
    TrendPoint,
)
from app.modules.orders.models import Order, OrderItem, OrderItemStatus, OrderPlatform, OrderStatus
from app.modules.returns.models import ReturnItem


SortBy = Literal["qty_sold", "revenue", "gross_profit", "return_rate", "inventory_left", "margin"]
SortDir = Literal["asc", "desc"]

EXCLUDED_ORDER_STATUSES = (
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
    OrderStatus.ERROR,
    OrderStatus.ON_HOLD,
)


def _float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _percent(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _date_bounds(start_date: date | None, end_date: date | None) -> tuple[datetime | None, datetime | None]:
    start_dt = datetime.combine(start_date, time.min) if start_date else None
    end_dt = datetime.combine(end_date, time.max) if end_date else None
    return start_dt, end_dt


def _platform_value(platform: object) -> str:
    return getattr(platform, "value", str(platform))


def _badges(row: dict[str, Any], rank: int) -> list[str]:
    badges: list[str] = []
    if row["return_rate_percent"] >= 20:
        badges.append("High Return")
    if row["inventory_left"] <= 2 and row["qty_sold"] > 0:
        badges.append("Low Stock")
    if row["gross_margin_percent"] >= 30:
        badges.append("High Margin")
    if rank <= 10:
        badges.append("Fast Seller")
    return badges


class BestSellingDashboardService:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _base_filters(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        platform: OrderPlatform | None,
        search: str | None = None,
        sku: str | None = None,
    ) -> list[Any]:
        start_dt, end_dt = _date_bounds(start_date, end_date)
        filters: list[Any] = [
            Order.status.notin_(EXCLUDED_ORDER_STATUSES),
            OrderItem.status != OrderItemStatus.CANCELLED,
        ]
        if start_dt:
            filters.append(Order.ordered_at >= start_dt)
        if end_dt:
            filters.append(Order.ordered_at <= end_dt)
        if platform:
            filters.append(Order.platform == platform)
        if search:
            like = f"%{search.strip()}%"
            filters.append(
                or_(
                    ProductVariant.full_sku.ilike(like),
                    ProductVariant.variant_name.ilike(like),
                    ProductFamily.base_name.ilike(like),
                    OrderItem.external_sku.ilike(like),
                    OrderItem.item_name.ilike(like),
                )
            )
        if sku:
            sku_expr = func.coalesce(ProductVariant.full_sku, OrderItem.external_sku, "UNMATCHED")
            filters.append(sku_expr == sku)
        return filters

    def _aggregate_sources(self) -> tuple[Any, Any, Any, Any]:
        return_qty = (
            select(
                ReturnItem.linked_order_item_id.label("order_item_id"),
                func.coalesce(func.sum(ReturnItem.returned_qty), 0).label("return_qty"),
            )
            .where(ReturnItem.linked_order_item_id.is_not(None))
            .group_by(ReturnItem.linked_order_item_id)
            .subquery()
        )
        order_qty = (
            select(
                OrderItem.order_id.label("order_id"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("order_qty"),
            )
            .group_by(OrderItem.order_id)
            .subquery()
        )
        inventory_left = (
            select(
                InventoryItem.variant_id.label("variant_id"),
                func.count(InventoryItem.id).label("inventory_left"),
            )
            .where(InventoryItem.status == InventoryStatus.AVAILABLE)
            .group_by(InventoryItem.variant_id)
            .subquery()
        )
        allocated_inventory = aliased(InventoryItem)
        return return_qty, order_qty, inventory_left, allocated_inventory

    async def products(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        platform: OrderPlatform | None,
        search: str | None,
        sort_by: SortBy,
        sort_dir: SortDir,
        limit: int,
        offset: int,
    ) -> BestSellingProductsResponse:
        rows = await self._all_product_rows(
            start_date=start_date,
            end_date=end_date,
            platform=platform,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return BestSellingProductsResponse(total=len(rows), rows=rows[offset : offset + limit])

    async def summary(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        platform: OrderPlatform | None,
    ) -> BestSellingSummary:
        rows = await self._all_product_rows(
            start_date=start_date,
            end_date=end_date,
            platform=platform,
            search=None,
            sort_by="qty_sold",
            sort_dir="desc",
        )
        total_units = sum(row.qty_sold for row in rows)
        total_revenue = sum(row.revenue for row in rows)
        gross_profit = sum(row.gross_profit for row in rows)
        return_qty = sum(row.return_qty for row in rows)
        missing_cost_rows = sum(row.missing_cost_rows for row in rows)
        low_stock_best_sellers = sum(1 for row in rows[:10] if row.inventory_left <= 2)
        orders_included = await self._orders_included(start_date=start_date, end_date=end_date, platform=platform)
        orders_with_shipping = await self._orders_with_shipping(start_date=start_date, end_date=end_date, platform=platform)
        unlinked_returns = await self._unlinked_returns(start_date=start_date, end_date=end_date)

        warnings = [
            DataQualityWarning(
                code="platform_fees_unavailable",
                message="Platform fees are not captured yet; dashboard shows gross profit, not net profit.",
                count=len(rows),
            ),
            DataQualityWarning(
                code="shipping_allocated_by_quantity",
                message="Order-level shipping is allocated to SKUs by quantity for this MVP.",
                count=orders_with_shipping,
                severity="info",
            ),
        ]
        if missing_cost_rows:
            warnings.append(
                DataQualityWarning(
                    code="missing_cost_basis",
                    message="Some sold rows do not have allocated inventory cost basis.",
                    count=missing_cost_rows,
                )
            )
        if unlinked_returns:
            warnings.append(
                DataQualityWarning(
                    code="unlinked_returns",
                    message="Some return items are not linked to order items and are excluded from SKU return rates.",
                    count=unlinked_returns,
                )
            )

        return BestSellingSummary(
            total_units_sold=total_units,
            total_revenue=round(total_revenue, 2),
            gross_profit=round(gross_profit, 2),
            average_margin_percent=_percent(gross_profit, total_revenue),
            return_rate_percent=_percent(return_qty, total_units),
            low_stock_best_sellers=low_stock_best_sellers,
            orders_included=orders_included,
            sku_count=len(rows),
            warnings=warnings,
        )

    async def platform_breakdown(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        sku: str | None = None,
    ) -> list[PlatformBreakdownRow]:
        rows = await self._all_product_rows(
            start_date=start_date,
            end_date=end_date,
            platform=None,
            search=None,
            sort_by="qty_sold",
            sort_dir="desc",
            sku=sku,
        )
        grouped: dict[str, dict[str, float]] = defaultdict(lambda: {"qty": 0, "revenue": 0.0, "profit": 0.0, "returns": 0})
        for row in rows:
            bucket = grouped[row.platform]
            bucket["qty"] += row.qty_sold
            bucket["revenue"] += row.revenue
            bucket["profit"] += row.gross_profit
            bucket["returns"] += row.return_qty
        return [
            PlatformBreakdownRow(
                platform=platform,
                qty_sold=int(values["qty"]),
                revenue=round(values["revenue"], 2),
                gross_profit=round(values["profit"], 2),
                return_rate_percent=_percent(values["returns"], values["qty"]),
            )
            for platform, values in sorted(grouped.items(), key=lambda item: item[1]["revenue"], reverse=True)
        ]

    async def trends(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        platform: OrderPlatform | None,
        sku: str | None = None,
    ) -> list[TrendPoint]:
        return_qty, order_qty, _, allocated_inventory = self._aggregate_sources()
        ordered_date = cast(Order.ordered_at, Date)
        shipping_share = case(
            (
                order_qty.c.order_qty > 0,
                (func.coalesce(Order.shipping_amount, 0) * OrderItem.quantity) / order_qty.c.order_qty,
            ),
            else_=0,
        )
        cost_expr = func.coalesce(allocated_inventory.cost_basis, 0)
        stmt = (
            select(
                ordered_date.label("date"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("qty_sold"),
                func.coalesce(func.sum(OrderItem.total_price), 0).label("revenue"),
                (
                    func.coalesce(func.sum(OrderItem.total_price), 0)
                    - func.coalesce(func.sum(cost_expr), 0)
                    - func.coalesce(func.sum(shipping_share), 0)
                ).label("gross_profit"),
            )
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(ProductVariant, ProductVariant.id == OrderItem.variant_id)
            .outerjoin(ProductIdentity, ProductIdentity.id == ProductVariant.identity_id)
            .outerjoin(ProductFamily, ProductFamily.product_id == ProductIdentity.product_id)
            .outerjoin(allocated_inventory, allocated_inventory.id == OrderItem.allocated_inventory_id)
            .outerjoin(order_qty, order_qty.c.order_id == Order.id)
            .outerjoin(return_qty, return_qty.c.order_item_id == OrderItem.id)
            .where(and_(*self._base_filters(start_date=start_date, end_date=end_date, platform=platform, sku=sku)))
            .where(Order.ordered_at.is_not(None))
            .group_by(ordered_date)
            .order_by(ordered_date)
        )
        result = await self.session.execute(stmt)
        return [
            TrendPoint(
                date=row.date.isoformat(),
                qty_sold=_int(row.qty_sold),
                revenue=round(_float(row.revenue), 2),
                gross_profit=round(_float(row.gross_profit), 2),
            )
            for row in result.mappings().all()
        ]

    async def product_detail(
        self,
        *,
        sku: str,
        start_date: date | None,
        end_date: date | None,
    ) -> BestSellingProductDetail | None:
        rows = await self._all_product_rows(
            start_date=start_date,
            end_date=end_date,
            platform=None,
            search=None,
            sort_by="qty_sold",
            sort_dir="desc",
            sku=sku,
        )
        if not rows:
            return None
        qty_sold = sum(row.qty_sold for row in rows)
        revenue = sum(row.revenue for row in rows)
        cost = sum(row.cost_of_goods_sold for row in rows)
        shipping = sum(row.allocated_shipping_cost for row in rows)
        gross_profit = sum(row.gross_profit for row in rows)
        return_qty = sum(row.return_qty for row in rows)
        inventory_left = max(row.inventory_left for row in rows)
        product_values = {
            "sku": sku,
            "product_name": rows[0].product_name,
            "platform": "ALL",
            "qty_sold": qty_sold,
            "revenue": round(revenue, 2),
            "average_selling_price": round(revenue / qty_sold, 2) if qty_sold else 0.0,
            "cost_of_goods_sold": round(cost, 2),
            "allocated_shipping_cost": round(shipping, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_margin_percent": _percent(gross_profit, revenue),
            "return_qty": return_qty,
            "return_rate_percent": _percent(return_qty, qty_sold),
            "inventory_left": inventory_left,
            "missing_cost_rows": sum(row.missing_cost_rows for row in rows),
        }
        product = BestSellingProductRow(rank=1, status_badges=_badges(product_values, 1), **product_values)
        platform_rows = await self.platform_breakdown(start_date=start_date, end_date=end_date, sku=sku)
        recent_orders = await self._recent_orders(sku=sku, start_date=start_date, end_date=end_date)
        return BestSellingProductDetail(product=product, platform_breakdown=platform_rows, recent_orders=recent_orders)

    async def _all_product_rows(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        platform: OrderPlatform | None,
        search: str | None,
        sort_by: SortBy,
        sort_dir: SortDir,
        sku: str | None = None,
    ) -> list[BestSellingProductRow]:
        return_qty, order_qty, inventory_left, allocated_inventory = self._aggregate_sources()
        sku_expr = func.coalesce(ProductVariant.full_sku, OrderItem.external_sku, "UNMATCHED")
        name_expr = func.coalesce(ProductVariant.variant_name, ProductFamily.base_name, OrderItem.item_name, "Unknown")
        shipping_share = case(
            (
                order_qty.c.order_qty > 0,
                (func.coalesce(Order.shipping_amount, 0) * OrderItem.quantity) / order_qty.c.order_qty,
            ),
            else_=0,
        )
        cost_expr = func.coalesce(allocated_inventory.cost_basis, 0)
        stmt = (
            select(
                sku_expr.label("sku"),
                name_expr.label("product_name"),
                Order.platform.label("platform"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("qty_sold"),
                func.coalesce(func.sum(OrderItem.total_price), 0).label("revenue"),
                func.coalesce(func.sum(cost_expr), 0).label("cost_of_goods_sold"),
                func.coalesce(func.sum(shipping_share), 0).label("allocated_shipping_cost"),
                func.coalesce(func.sum(return_qty.c.return_qty), 0).label("return_qty"),
                func.coalesce(func.max(inventory_left.c.inventory_left), 0).label("inventory_left"),
                func.count(OrderItem.id)
                .filter(or_(OrderItem.allocated_inventory_id.is_(None), allocated_inventory.cost_basis.is_(None)))
                .label("missing_cost_rows"),
            )
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(ProductVariant, ProductVariant.id == OrderItem.variant_id)
            .outerjoin(ProductIdentity, ProductIdentity.id == ProductVariant.identity_id)
            .outerjoin(ProductFamily, ProductFamily.product_id == ProductIdentity.product_id)
            .outerjoin(allocated_inventory, allocated_inventory.id == OrderItem.allocated_inventory_id)
            .outerjoin(order_qty, order_qty.c.order_id == Order.id)
            .outerjoin(return_qty, return_qty.c.order_item_id == OrderItem.id)
            .outerjoin(inventory_left, inventory_left.c.variant_id == ProductVariant.id)
            .where(and_(*self._base_filters(start_date=start_date, end_date=end_date, platform=platform, search=search, sku=sku)))
            .group_by(sku_expr, name_expr, Order.platform)
        )
        result = await self.session.execute(stmt)
        raw_rows: list[dict[str, Any]] = []
        for row in result.mappings().all():
            revenue = _float(row["revenue"])
            cost = _float(row["cost_of_goods_sold"])
            shipping = _float(row["allocated_shipping_cost"])
            gross_profit = revenue - cost - shipping
            qty_sold = _int(row["qty_sold"])
            raw_rows.append(
                {
                    "sku": row["sku"] or "UNMATCHED",
                    "product_name": row["product_name"] or "Unknown",
                    "platform": _platform_value(row["platform"]),
                    "qty_sold": qty_sold,
                    "revenue": round(revenue, 2),
                    "average_selling_price": round(revenue / qty_sold, 2) if qty_sold else 0.0,
                    "cost_of_goods_sold": round(cost, 2),
                    "allocated_shipping_cost": round(shipping, 2),
                    "gross_profit": round(gross_profit, 2),
                    "gross_margin_percent": _percent(gross_profit, revenue),
                    "return_qty": _int(row["return_qty"]),
                    "return_rate_percent": _percent(_int(row["return_qty"]), qty_sold),
                    "inventory_left": _int(row["inventory_left"]),
                    "missing_cost_rows": _int(row["missing_cost_rows"]),
                }
            )

        sort_key = {
            "qty_sold": lambda item: item["qty_sold"],
            "revenue": lambda item: item["revenue"],
            "gross_profit": lambda item: item["gross_profit"],
            "return_rate": lambda item: item["return_rate_percent"],
            "inventory_left": lambda item: item["inventory_left"],
            "margin": lambda item: item["gross_margin_percent"],
        }[sort_by]
        raw_rows.sort(key=sort_key, reverse=sort_dir == "desc")
        return [
            BestSellingProductRow(rank=index, status_badges=_badges(row, index), **row)
            for index, row in enumerate(raw_rows, start=1)
        ]

    async def _orders_included(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        platform: OrderPlatform | None,
    ) -> int:
        stmt = (
            select(func.count(func.distinct(Order.id)))
            .select_from(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(and_(*self._base_filters(start_date=start_date, end_date=end_date, platform=platform)))
        )
        result = await self.session.execute(stmt)
        return _int(result.scalar_one())

    async def _orders_with_shipping(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        platform: OrderPlatform | None,
    ) -> int:
        stmt = (
            select(func.count(func.distinct(Order.id)))
            .select_from(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(
                and_(*self._base_filters(start_date=start_date, end_date=end_date, platform=platform)),
                Order.shipping_amount > 0,
            )
        )
        result = await self.session.execute(stmt)
        return _int(result.scalar_one())

    async def _unlinked_returns(self, *, start_date: date | None, end_date: date | None) -> int:
        start_dt, end_dt = _date_bounds(start_date, end_date)
        filters: list[Any] = [ReturnItem.linked_order_item_id.is_(None), ReturnItem.returned_qty > 0]
        if start_dt:
            filters.append(ReturnItem.created_at >= start_dt)
        if end_dt:
            filters.append(ReturnItem.created_at <= end_dt)
        stmt = select(func.count(ReturnItem.id)).where(and_(*filters))
        result = await self.session.execute(stmt)
        return _int(result.scalar_one())

    async def _recent_orders(self, *, sku: str, start_date: date | None, end_date: date | None) -> list[RecentOrderRow]:
        sku_expr = func.coalesce(ProductVariant.full_sku, OrderItem.external_sku, "UNMATCHED")
        stmt = (
            select(
                Order.id.label("order_id"),
                Order.external_order_id.label("external_order_id"),
                Order.ordered_at.label("ordered_at"),
                Order.platform.label("platform"),
                Customer.name.label("customer"),
                OrderItem.quantity.label("qty"),
                OrderItem.total_price.label("revenue"),
            )
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(Customer, Customer.id == Order.customer_id)
            .outerjoin(ProductVariant, ProductVariant.id == OrderItem.variant_id)
            .outerjoin(ProductIdentity, ProductIdentity.id == ProductVariant.identity_id)
            .outerjoin(ProductFamily, ProductFamily.product_id == ProductIdentity.product_id)
            .where(and_(*self._base_filters(start_date=start_date, end_date=end_date, platform=None, sku=sku)))
            .order_by(Order.ordered_at.desc().nullslast(), Order.id.desc())
            .limit(10)
        )
        result = await self.session.execute(stmt)
        rows = []
        for row in result.mappings().all():
            ordered_at = row["ordered_at"]
            rows.append(
                RecentOrderRow(
                    order_id=row["order_id"],
                    external_order_id=row["external_order_id"],
                    ordered_at=ordered_at.isoformat() if ordered_at else None,
                    platform=_platform_value(row["platform"]),
                    customer=row["customer"] or "Unknown",
                    qty=_int(row["qty"]),
                    revenue=round(_float(row["revenue"]), 2),
                )
            )
        return rows
