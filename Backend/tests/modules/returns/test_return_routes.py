from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import OrderPlatform, ReturnNormalizedStatus
from app.modules.orders.models import OrderFulfillmentChannel
from app.modules.returns.routes import list_returns, sync_status


@pytest.mark.asyncio
async def test_list_returns_passes_filters_to_repository():
    record_repo = MagicMock()
    row = SimpleNamespace(
        id=1,
        platform=OrderPlatform.ECWID,
        source="ECWID_API",
        external_record_key="order:1",
        external_order_id="1",
        external_return_id=None,
        linked_order_id=None,
        customer_name="Alice",
        customer_email="alice@example.com",
        ordered_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
        event_at=datetime(2026, 6, 8, 1, tzinfo=timezone.utc),
        last_source_updated_at=datetime(2026, 6, 8, 1, tzinfo=timezone.utc),
        normalized_status=ReturnNormalizedStatus.RETURNED,
        source_status="REFUNDED",
        source_substatus="RETURNED",
        reason=None,
        fulfillment_channel=OrderFulfillmentChannel.SELF_FULFILLED,
        order_total_amount=Decimal("10"),
        refunded_amount=Decimal("10"),
        currency="USD",
        items=[],
        created_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
    )
    record_repo.list_records = AsyncMock(return_value=([row], 1, {"RETURNED": 1}))

    response = await list_returns(
        skip=0,
        limit=50,
        platform=OrderPlatform.ECWID,
        normalized_status="RETURNED",
        record_repo=record_repo,
    )

    assert response.total == 1
    assert record_repo.list_records.await_args.kwargs["platform"] == OrderPlatform.ECWID
    assert record_repo.list_records.await_args.kwargs["normalized_status"] == ReturnNormalizedStatus.RETURNED


@pytest.mark.asyncio
async def test_return_sync_status_aggregates_counts():
    sync_repo = MagicMock()
    sync_repo.get_all_states = AsyncMock(return_value=[])
    record_repo = MagicMock()
    record_repo.count_by_status = AsyncMock(return_value={"RETURNED": 3, "CANCELLED": 1})
    record_repo.count = AsyncMock(return_value=4)

    response = await sync_status(sync_repo=sync_repo, record_repo=record_repo)

    assert response.total_records == 4
    assert response.counts_by_status["RETURNED"] == 3
