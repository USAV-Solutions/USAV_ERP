from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import OrderPlatform, ReturnNormalizedStatus, ReturnZohoSyncStatus
from app.modules.returns.zoho_sync import ZohoReturnSyncService


class _TestZohoReturnSyncService(ZohoReturnSyncService):
    def __init__(self, record=None, already_synced_qty: int = 0, zoho_client=None):
        session = MagicMock()
        session.commit = AsyncMock()
        super().__init__(session=session, zoho_client=zoho_client or MagicMock())
        self.record = record
        self.already_synced_qty = already_synced_qty

    async def _get_record(self, record_id: int):
        return self.record

    async def _already_synced_quantity(self, record_id: int, order_item_id: int) -> int:
        return self.already_synced_qty


def _record(*, zoho_salesreturn_id=None, quantity=2, returned_qty=1):
    order_item = SimpleNamespace(
        id=20,
        external_item_id="ITEM-1",
        external_sku="SKU-1",
        item_name="Item 1",
        quantity=quantity,
        variant=SimpleNamespace(zoho_item_id="ZITEM-1"),
    )
    return_item = SimpleNamespace(
        id=30,
        linked_order_item_id=20,
        linked_order_item=order_item,
        external_item_id="ITEM-1",
        external_sku="SKU-1",
        item_name="Item 1",
        returned_qty=returned_qty,
        cancelled_qty=0,
    )
    order = SimpleNamespace(
        id=10,
        zoho_id="SO-1",
        external_order_id="ORDER-1",
        external_order_number="ORDER-NUM-1",
        items=[order_item],
    )
    return SimpleNamespace(
        id=1,
        platform=OrderPlatform.EBAY_USAV,
        external_record_key="return:RET-1",
        external_order_id="ORDER-1",
        external_return_id="RET-1",
        linked_order=order,
        items=[return_item],
        event_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
        reason="buyer_returned",
        normalized_status=ReturnNormalizedStatus.RETURNED,
        zoho_salesreturn_id=zoho_salesreturn_id,
        zoho_salesreturn_number=None,
        zoho_sync_status=ReturnZohoSyncStatus.PENDING,
        zoho_sync_error=None,
        zoho_synced_at=None,
    )


def _zoho_client():
    client = MagicMock()
    client.get_salesorder = AsyncMock(
        return_value={
            "salesorder_id": "SO-1",
            "line_items": [
                {
                    "line_item_id": "SOL-1",
                    "item_id": "ZITEM-1",
                    "sku": "SKU-1",
                    "name": "Item 1",
                }
            ],
        }
    )
    client.search_salesorder_by_reference = AsyncMock(return_value=None)
    client.create_sales_return = AsyncMock(
        return_value={"salesreturn_id": "SR-1", "salesreturn_number": "SR-0001"}
    )
    return client


@pytest.mark.asyncio
async def test_validate_blocks_missing_local_order_before_zoho_call():
    record = _record()
    record.linked_order = None
    client = _zoho_client()
    service = _TestZohoReturnSyncService(record=record, zoho_client=client)

    result = await service.validate_return_for_zoho(record.id)

    assert result.status == ReturnZohoSyncStatus.MISSING_LOCAL_ORDER
    client.get_salesorder.assert_not_called()
    assert record.zoho_sync_status == ReturnZohoSyncStatus.MISSING_LOCAL_ORDER


@pytest.mark.asyncio
async def test_validate_ready_maps_local_item_to_zoho_salesorder_line():
    record = _record()
    service = _TestZohoReturnSyncService(record=record, zoho_client=_zoho_client())

    result = await service.validate_return_for_zoho(record.id)

    assert result.status == ReturnZohoSyncStatus.READY_TO_SYNC
    assert result.zoho_salesorder_id == "SO-1"
    assert result.line_items[0].zoho_salesorder_item_id == "SOL-1"
    assert record.zoho_sync_status == ReturnZohoSyncStatus.READY_TO_SYNC


@pytest.mark.asyncio
async def test_validate_blocks_quantity_above_available_after_prior_synced_returns():
    record = _record(quantity=2, returned_qty=2)
    service = _TestZohoReturnSyncService(record=record, already_synced_qty=1, zoho_client=_zoho_client())

    result = await service.validate_return_for_zoho(record.id)

    assert result.status == ReturnZohoSyncStatus.QUANTITY_CONFLICT
    assert "exceeds available order quantity" in result.blockers[0]


@pytest.mark.asyncio
async def test_sync_skips_create_when_return_already_has_zoho_salesreturn_id():
    record = _record(zoho_salesreturn_id="SR-EXISTING")
    client = _zoho_client()
    service = _TestZohoReturnSyncService(record=record, zoho_client=client)

    result = await service.sync_return_to_zoho(record.id)

    assert result.status == ReturnZohoSyncStatus.ALREADY_SYNCED
    client.create_sales_return.assert_not_called()
    assert record.zoho_sync_status == ReturnZohoSyncStatus.SYNCED


@pytest.mark.asyncio
async def test_sync_creates_sales_return_and_stores_result():
    record = _record()
    client = _zoho_client()
    service = _TestZohoReturnSyncService(record=record, zoho_client=client)

    result = await service.sync_return_to_zoho(record.id)

    assert result.status == ReturnZohoSyncStatus.SYNCED
    assert record.zoho_salesreturn_id == "SR-1"
    assert record.zoho_salesreturn_number == "SR-0001"
    payload = client.create_sales_return.await_args.args[0]
    assert payload["salesorder_id"] == "SO-1"
    assert payload["line_items"] == [{"salesorder_item_id": "SOL-1", "quantity": 1}]
