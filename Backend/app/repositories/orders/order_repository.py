"""
Order & OrderItem repository.

Provides database operations for order headers and line items, including
deduplication-safe upserts and filtered queries for the dashboard.
"""
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import ZohoSyncStatus
from app.modules.orders.models import (
    Order,
    OrderItem,
    OrderItemStatus,
    OrderPlatform,
    OrderStatus,
)
from app.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    """Repository for Order (header) operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(Order, session)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    async def get_with_items(self, order_id: int) -> Optional[Order]:
        """Load an order together with all its line items and customer."""
        stmt = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.customer))
            .where(Order.id == order_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self,
        platform: OrderPlatform,
        external_order_id: str,
    ) -> Optional[Order]:
        """Look up an order by its platform-specific ID (dedup check)."""
        stmt = select(Order).where(
            and_(
                Order.platform == platform,
                Order.external_order_id == external_order_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_orders(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        platform: Optional[OrderPlatform] = None,
        status: Optional[OrderStatus] = None,
        item_status: Optional[OrderItemStatus] = None,
        ordered_at_from: Optional[datetime] = None,
        ordered_at_to: Optional[datetime] = None,
        zoho_sync_status: Optional[ZohoSyncStatus] = None,
        source: Optional[str] = None,
        sort_by: str = "ordered_at",
        sort_dir: str = "desc",
        search: Optional[str] = None,
    ) -> tuple[Sequence[Order], int]:
        """
        Paginated order list with optional filters.

        ``item_status`` filters to orders that contain **at least one** item
        matching the given status (e.g. "show me orders with UNMATCHED items").
        """
        stmt = select(Order).options(
            selectinload(Order.items),
            selectinload(Order.customer),
        )

        if platform is not None:
            stmt = stmt.where(Order.platform == platform)
        if status is not None:
            stmt = stmt.where(Order.status == status)
        if item_status is not None:
            stmt = stmt.where(
                Order.items.any(OrderItem.status == item_status)
            )
        if ordered_at_from is not None:
            stmt = stmt.where(Order.ordered_at >= ordered_at_from)
        if ordered_at_to is not None:
            stmt = stmt.where(Order.ordered_at <= ordered_at_to)
        if zoho_sync_status is not None:
            stmt = stmt.where(Order.zoho_sync_status == zoho_sync_status)
        if source:
            stmt = stmt.where(Order.source.ilike(f"%{source.strip()}%"))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                Order.external_order_id.ilike(pattern)
                | Order.customer_name.ilike(pattern)
            )

        # Total count (before pagination)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_columns = {
            "ordered_at": Order.ordered_at,
            "created_at": Order.created_at,
            "total_amount": Order.total_amount,
            "external_order_id": Order.external_order_id,
        }
        sort_column = sort_columns.get(sort_by.lower(), Order.ordered_at)

        if sort_dir.lower() == "asc":
            stmt = stmt.order_by(sort_column.asc(), Order.id.asc())
        else:
            stmt = stmt.order_by(desc(sort_column), desc(Order.id))

        stmt = stmt.offset(skip).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()

        return rows, total


class OrderItemRepository(BaseRepository[OrderItem]):
    """Repository for OrderItem (line-item) operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(OrderItem, session)

    async def get_unmatched(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[OrderItem]:
        """Return items that still need SKU resolution."""
        stmt = (
            select(OrderItem)
            .where(OrderItem.status == OrderItemStatus.UNMATCHED)
            .order_by(OrderItem.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_matched(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[OrderItem]:
        """Return items that were auto- or manually matched."""
        stmt = (
            select(OrderItem)
            .where(OrderItem.status == OrderItemStatus.MATCHED)
            .order_by(OrderItem.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_by_status(self) -> dict[str, int]:
        """Dashboard helper – count items grouped by status."""
        stmt = (
            select(OrderItem.status, func.count())
            .group_by(OrderItem.status)
        )
        rows = (await self.session.execute(stmt)).all()
        return {status.value: count for status, count in rows}
