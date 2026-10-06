from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.modules.orders.routes as _orders_routes  # noqa: F401 - resolves circular import
from app.integrations.base import ExternalOrder, ExternalOrderItem
from app.modules.orders.models import OrderFulfillmentChannel, OrderPlatform
from app.modules.orders.schemas.sync import SyncResponse
from app.modules.orders.service import OrderSyncService


def _build_service() -> OrderSyncService:
    return OrderSyncService(
        session=MagicMock(),
        sync_repo=MagicMock(),
        order_repo=MagicMock(),
        order_item_repo=MagicMock(),
        listing_repo=MagicMock(),
    )


def _build_external_order() -> ExternalOrder:
    return ExternalOrder(
        platform_order_id="114-123",
        platform_order_number="114-123",
        customer_name="Alice",
        customer_email="alice@example.com",
        customer_external_id=None,
        ship_address_line1=None,
        ship_address_line2=None,
        ship_address_line3=None,
        ship_city="Dallas",
        ship_state="TX",
        ship_postal_code="75001",
        ship_country="US",
        subtotal=27.88,
        tax=1.53,
        shipping=0.0,
        total=29.41,
        currency="USD",
        ordered_at=datetime(2026, 6, 4, 4, 0, 11, tzinfo=timezone.utc),
        items=[
            ExternalOrderItem(
                platform_item_id="ITEM-1",
                platform_sku="SKU-1",
                asin="ASIN-1",
                title="Widget One",
                quantity=1,
                unit_price=27.88,
                total_price=27.88,
                raw_data={"carrier": "AMZN_US"},
            )
        ],
        raw_data={"carrier": "AMZN_US"},
        tracking_number="TBA123",
        carrier="AMZN_US",
    )


@pytest.mark.asyncio
async def test_ingest_order_creates_fba_channel_for_amazon_fba_csv():
    service = _build_service()
    service.order_repo.get_by_external_id = AsyncMock(return_value=None)
    service.order_repo.create = AsyncMock(return_value=SimpleNamespace(id=1))
    service._get_or_create_customer = AsyncMock(return_value=None)
    service._ingest_item = AsyncMock()
    service._is_tracking_duplicate = AsyncMock(return_value=False)

    response = SyncResponse(platform="AMAZON")
    ext = _build_external_order()

    result = await service._ingest_order(
        ext,
        OrderPlatform.AMAZON,
        response,
        source="AMAZON_FBA_CSV",
        fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
    )

    created_payload = service.order_repo.create.await_args.args[0]
    assert result == "created"
    assert created_payload["fulfillment_channel"] == OrderFulfillmentChannel.AMAZON_FBA
    assert created_payload["carrier"] == "AMZN_US"


@pytest.mark.asyncio
async def test_ingest_order_skips_existing_csv_order_without_update():
    service = _build_service()
    existing = SimpleNamespace(id=1)
    service.order_repo.get_by_external_id = AsyncMock(return_value=existing)
    service._update_existing_order = AsyncMock()

    result = await service._ingest_order(
        _build_external_order(),
        OrderPlatform.AMAZON,
        SyncResponse(platform="AMAZON"),
        source="SHIPSTATION_CSV",
        skip_existing=True,
    )

    assert result == "unchanged"
    service._update_existing_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_existing_order_upgrades_to_fba_and_later_api_sync_does_not_downgrade():
    service = _build_service()
    service._get_or_create_customer = AsyncMock(return_value=None)
    service._upsert_existing_order_items = AsyncMock(return_value=False)

    existing = SimpleNamespace(
        id=1,
        customer_id=None,
        source="AMAZON_API",
        fulfillment_channel=OrderFulfillmentChannel.SELF_FULFILLED,
        external_order_number="114-123",
        ordered_at=datetime(2026, 6, 4, 4, 0, 11, tzinfo=timezone.utc),
        tracking_number="TBA123",
        carrier="AMZN_US",
        subtotal_amount=Decimal("27.88"),
        tax_amount=Decimal("1.53"),
        shipping_amount=Decimal("0.00"),
        total_amount=Decimal("27.88"),
        currency="USD",
        platform_data={"carrier": "AMZN_US"},
    )
    response = SyncResponse(platform="AMAZON")
    ext = _build_external_order()

    changed = await service._update_existing_order(
        existing=existing,
        ext=ext,
        platform=OrderPlatform.AMAZON,
        response=response,
        source="AMAZON_FBA_CSV",
        fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
    )

    assert changed is True
    assert existing.fulfillment_channel == OrderFulfillmentChannel.AMAZON_FBA

    existing.source = "AMAZON_API"
    changed = await service._update_existing_order(
        existing=existing,
        ext=ext,
        platform=OrderPlatform.AMAZON,
        response=response,
        source="AMAZON_API",
        fulfillment_channel=None,
    )

    assert existing.fulfillment_channel == OrderFulfillmentChannel.AMAZON_FBA
    assert changed is False


@pytest.mark.asyncio
async def test_update_existing_order_upgrades_platform_from_amazon_to_amazon_fba():
    service = _build_service()
    service._get_or_create_customer = AsyncMock(return_value=None)
    service._upsert_existing_order_items = AsyncMock(return_value=False)
    service._is_tracking_duplicate = AsyncMock(return_value=False)

    existing = SimpleNamespace(
        id=1,
        platform=OrderPlatform.AMAZON,
        customer_id=None,
        source="SHIPSTATION_CSV",
        fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
        external_order_number="111-9125115-2573034",
        ordered_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        tracking_number=None,
        carrier=None,
        subtotal_amount=Decimal("27.88"),
        tax_amount=Decimal("0.00"),
        shipping_amount=Decimal("0.00"),
        total_amount=Decimal("27.88"),
        currency="USD",
        platform_data={},
    )
    response = SyncResponse(platform="AMAZON_FBA")
    ext = _build_external_order()

    changed = await service._update_existing_order(
        existing=existing,
        ext=ext,
        platform=OrderPlatform.AMAZON_FBA,
        response=response,
        source="AMAZON_FBA_CSV",
        fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
    )

    assert changed is True
    assert existing.platform == OrderPlatform.AMAZON_FBA


@pytest.mark.asyncio
async def test_order_repository_get_by_external_id_cross_amazon_platforms():
    from app.repositories.orders.order_repository import OrderRepository
    from unittest.mock import MagicMock

    session = MagicMock()
    mock_order = SimpleNamespace(
        id=42,
        platform=OrderPlatform.AMAZON,
        external_order_id="111-9125115-2573034",
        zoho_id="Z-100",
    )
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_order
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    repo = OrderRepository(session)
    found = await repo.get_by_external_id(OrderPlatform.AMAZON_FBA, "111-9125115-2573034")

    assert found is mock_order
    session.execute.assert_awaited_once()
