"""
Shared helper for turning already-parsed import rows into persisted orders.

Both the manual ``POST /orders/import/file`` route and the server-side FBA
pipeline (``app/modules/fba``) parse their source into the same row-dict shape
(the one ``_parse_amazon_fba_csv`` / ``_parse_order_csv`` produce) and then hand
it here. Keeping this in one place means the FBA pipeline produces byte-for-byte
the same orders as a manual CSV upload.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.integrations.base import BasePlatformClient, ExternalOrder, ExternalOrderItem
from app.modules.orders.models import OrderFulfillmentChannel
from app.modules.orders.service import OrderSyncService


class StaticImportClient(BasePlatformClient):
    """A platform client that just replays a fixed list of orders."""

    def __init__(self, platform_name: str, orders: list):
        self._platform_name = platform_name
        self._orders = orders

    @property
    def platform_name(self) -> str:
        return self._platform_name

    async def authenticate(self) -> bool:
        return True

    async def fetch_orders(self, since=None, until=None, status=None):
        _ = (since, until, status)
        return self._orders

    async def get_order(self, order_id: str):
        _ = order_id
        return None

    async def update_stock(self, updates):
        _ = updates
        return []

    async def update_tracking(self, order_id: str, tracking_number: str, carrier: str) -> bool:
        _ = (order_id, tracking_number, carrier)
        return False


def rows_to_external_orders(rows: list[dict]) -> dict[str, list[ExternalOrder]]:
    """Group parsed row-dicts into ``{platform_name: [ExternalOrder, ...]}``."""
    orders_by_platform: dict[str, list[ExternalOrder]] = {}
    for row in rows:
        items = [
            ExternalOrderItem(
                platform_item_id=item["platform_item_id"],
                platform_sku=item["platform_sku"],
                asin=item["asin"],
                title=item["title"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                total_price=item["total_price"],
                raw_data=item["raw_data"],
            )
            for item in row["items"]
        ]
        platform_name = row.get("platform_name") or "MANUAL"
        external_order = ExternalOrder(
            platform_order_id=row["platform_order_id"],
            platform_order_number=row["platform_order_number"],
            customer_name=row["customer_name"],
            customer_email=row["customer_email"],
            customer_external_id=row.get("customer_external_id"),
            ship_address_line1=row["ship_address_line1"],
            ship_address_line2=row["ship_address_line2"],
            ship_address_line3=row["ship_address_line3"],
            ship_city=row["ship_city"],
            ship_state=row["ship_state"],
            ship_postal_code=row["ship_postal_code"],
            ship_country=row["ship_country"],
            subtotal=row["subtotal"],
            tax=row["tax"],
            shipping=row["shipping"],
            total=row["total"],
            currency=row["currency"],
            ordered_at=row["ordered_at"],
            items=items,
            raw_data=row["raw_data"],
            customer_source=None,
            tracking_number=row.get("tracking_number"),
            carrier=row.get("carrier"),
        )
        orders_by_platform.setdefault(platform_name, []).append(external_order)
    return orders_by_platform


async def ingest_parsed_rows(
    service: OrderSyncService,
    rows: list[dict],
    *,
    source: str,
    fulfillment_channel: Optional[OrderFulfillmentChannel] = None,
    skip_existing: bool = False,
) -> dict:
    """Persist parsed rows via the order sync service. Returns an aggregate dict.

    Idempotent: orders are matched on ``(platform, external_order_id)`` and
    updated in place, so re-importing an overlapping window does not duplicate
    orders, line items, or amounts.
    """
    orders_by_platform = rows_to_external_orders(rows)
    aggregate = {
        "new_orders": 0,
        "new_items": 0,
        "auto_matched": 0,
        "skipped_duplicates": 0,
        "errors": [],
        "success": True,
    }
    for platform_name, platform_orders in orders_by_platform.items():
        client = StaticImportClient(platform_name, platform_orders)
        result = await service.sync_platform_range(
            platform_name,
            client,
            datetime(1970, 1, 1, tzinfo=timezone.utc),
            datetime.now(timezone.utc),
            source=source,
            fulfillment_channel=fulfillment_channel,
            skip_existing=skip_existing,
        )
        aggregate["new_orders"] += result.new_orders
        aggregate["new_items"] += result.new_items
        aggregate["auto_matched"] += result.auto_matched
        aggregate["skipped_duplicates"] += result.skipped_duplicates
        aggregate["errors"].extend(result.errors)
        if not result.success:
            aggregate["success"] = False
    return aggregate
