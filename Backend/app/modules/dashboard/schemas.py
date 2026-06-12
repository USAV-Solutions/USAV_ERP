"""Response schemas for best-selling dashboard APIs."""

from pydantic import BaseModel


class DataQualityWarning(BaseModel):
    code: str
    message: str
    count: int
    severity: str = "warning"


class BestSellingSummary(BaseModel):
    total_units_sold: int
    total_revenue: float
    gross_profit: float
    average_margin_percent: float
    return_rate_percent: float
    low_stock_best_sellers: int
    orders_included: int
    sku_count: int
    warnings: list[DataQualityWarning]


class BestSellingProductRow(BaseModel):
    rank: int
    sku: str
    product_name: str
    platform: str
    qty_sold: int
    revenue: float
    average_selling_price: float
    cost_of_goods_sold: float
    allocated_shipping_cost: float
    gross_profit: float
    gross_margin_percent: float
    return_qty: int
    return_rate_percent: float
    inventory_left: int
    missing_cost_rows: int
    status_badges: list[str]


class BestSellingProductsResponse(BaseModel):
    total: int
    rows: list[BestSellingProductRow]


class TrendPoint(BaseModel):
    date: str
    qty_sold: int
    revenue: float
    gross_profit: float


class PlatformBreakdownRow(BaseModel):
    platform: str
    qty_sold: int
    revenue: float
    gross_profit: float
    return_rate_percent: float


class RecentOrderRow(BaseModel):
    order_id: int
    external_order_id: str
    ordered_at: str | None
    platform: str
    customer: str
    qty: int
    revenue: float


class BestSellingProductDetail(BaseModel):
    product: BestSellingProductRow
    platform_breakdown: list[PlatformBreakdownRow]
    recent_orders: list[RecentOrderRow]

