from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import OrderPlatform, ReturnNormalizedStatus, ReturnZohoSyncStatus
from app.modules.orders.models import OrderFulfillmentChannel
from app.modules.returns.schemas.sync import ReturnSyncResponse
from app.modules.returns.service import (
    NormalizedReturnItem,
    NormalizedReturnRecord,
    ReturnSyncService,
)


def _build_service() -> ReturnSyncService:
    session = MagicMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return ReturnSyncService(
        session=session,
        sync_repo=MagicMock(),
        record_repo=MagicMock(),
        order_repo=MagicMock(),
    )


def _build_record() -> NormalizedReturnRecord:
    return NormalizedReturnRecord(
        external_record_key="order:EB-1",
        external_order_id="EB-1",
        platform=OrderPlatform.EBAY_USAV,
        source="EBAY_USAV_API",
        normalized_status=ReturnNormalizedStatus.CANCELLED,
        customer_name="Alice",
        customer_email="alice@example.com",
        ordered_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
        event_at=datetime(2026, 6, 8, 1, tzinfo=timezone.utc),
        last_source_updated_at=datetime(2026, 6, 8, 1, tzinfo=timezone.utc),
        source_status="CANCELED",
        order_total_amount=Decimal("20.00"),
        refunded_amount=Decimal("0"),
        currency="USD",
        raw_payload={"orderId": "EB-1"},
        items=[
            NormalizedReturnItem(
                external_item_id="ITEM-1",
                external_sku="SKU-1",
                item_name="Item 1",
                ordered_qty=1,
                cancelled_qty=1,
                payload={"itemId": "ITEM-1"},
            )
        ],
    )


@pytest.mark.asyncio
async def test_find_linked_order_uses_external_reference_lookup_when_available():
    class Repo:
        def __init__(self):
            self.reference_calls = []

        async def get_by_external_reference(self, platform, external_order_id):
            self.reference_calls.append((platform, external_order_id))
            return SimpleNamespace(id=11)

        async def get_with_items(self, order_id):
            return SimpleNamespace(id=order_id, items=[])

    service = _build_service()
    repo = Repo()
    service.order_repo = repo

    order = await service._find_linked_order(OrderPlatform.AMAZON, "112-123")

    assert order.id == 11
    assert repo.reference_calls == [(OrderPlatform.AMAZON, "112-123")]


@pytest.mark.asyncio
async def test_upsert_record_links_existing_order_and_item():
    service = _build_service()
    service.order_repo.get_by_external_id = AsyncMock(return_value=SimpleNamespace(id=11))
    service.order_repo.get_with_items = AsyncMock(
        return_value=SimpleNamespace(
            id=11,
            items=[SimpleNamespace(id=22, external_item_id="ITEM-1", external_sku="SKU-1", item_name="Item 1", unit_price=Decimal("0"))],
        )
    )
    service.record_repo.get_by_external_key = AsyncMock(return_value=None)
    service.record_repo.create = AsyncMock(return_value=SimpleNamespace(id=99))

    response = ReturnSyncResponse(platform="EBAY_USAV")
    result = await service._upsert_record(_build_record(), response)

    created_payload = service.record_repo.create.await_args.args[0]
    assert result == "created"
    assert created_payload["linked_order_id"] == 11
    assert response.new_records == 1
    assert response.linked_orders == 1
    assert response.linked_items == 1


@pytest.mark.asyncio
async def test_upsert_record_returns_unchanged_for_identical_snapshot():
    service = _build_service()
    service.order_repo.get_by_external_id = AsyncMock(return_value=SimpleNamespace(id=11))
    service.order_repo.get_with_items = AsyncMock(
        return_value=SimpleNamespace(
            id=11,
            items=[SimpleNamespace(id=22, external_item_id="ITEM-1", external_sku="SKU-1", item_name="Item 1", unit_price=Decimal("0"))],
        )
    )
    existing = SimpleNamespace(
        id=99,
        platform=OrderPlatform.EBAY_USAV,
        source="EBAY_USAV_API",
        external_record_key="order:EB-1",
        external_order_id="EB-1",
        external_return_id=None,
        linked_order_id=11,
        customer_name="Alice",
        customer_email="alice@example.com",
        ordered_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
        event_at=datetime(2026, 6, 8, 1, tzinfo=timezone.utc),
        last_source_updated_at=datetime(2026, 6, 8, 1, tzinfo=timezone.utc),
        normalized_status=ReturnNormalizedStatus.CANCELLED,
        source_status="CANCELED",
        source_substatus=None,
        reason=None,
        fulfillment_channel=OrderFulfillmentChannel.SELF_FULFILLED,
        order_total_amount=Decimal("20.00"),
        refunded_amount=Decimal("0"),
        currency="USD",
        zoho_sync_status=ReturnZohoSyncStatus.PENDING,
        raw_payload={"orderId": "EB-1"},
        items=[
            SimpleNamespace(
                linked_order_item_id=22,
                external_item_id="ITEM-1",
                external_sku="SKU-1",
                item_name="Item 1",
                ordered_qty=1,
                returned_qty=0,
                cancelled_qty=1,
                refunded_amount=Decimal("0"),
                item_payload={"itemId": "ITEM-1"},
            )
        ],
    )
    service.record_repo.get_by_external_key = AsyncMock(return_value=existing)

    response = ReturnSyncResponse(platform="EBAY_USAV")
    result = await service._upsert_record(_build_record(), response)

    assert result == "unchanged"
    service.session.delete.assert_not_called()


def test_build_item_rows_leaves_links_null_without_order():
    service = _build_service()
    rows, linked_count = service._build_item_rows(
        None,
        [
            NormalizedReturnItem(
                external_item_id="ITEM-1",
                external_sku="SKU-1",
                item_name="Item 1",
                ordered_qty=1,
                returned_qty=1,
                refunded_amount=Decimal("5.00"),
            )
        ],
    )

    assert linked_count == 0
    assert rows[0]["linked_order_item_id"] is None
