import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.orders.models import OrderFulfillmentChannel
from app.modules.orders.routes import list_orders, sync_status


@pytest.mark.asyncio
async def test_list_orders_passes_fulfillment_channel_to_repository():
    order_repo = MagicMock()
    order_repo.list_orders = AsyncMock(return_value=([], 0))

    response = await list_orders(
        fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
        order_repo=order_repo,
    )

    assert response.total == 0
    assert order_repo.list_orders.await_args.kwargs["fulfillment_channel"] == OrderFulfillmentChannel.AMAZON_FBA


@pytest.mark.asyncio
async def test_sync_status_scopes_counts_by_fulfillment_channel():
    sync_repo = MagicMock()
    sync_repo.get_all_states = AsyncMock(return_value=[])
    order_item_repo = MagicMock()
    order_item_repo.count_by_status = AsyncMock(return_value={"UNMATCHED": 3, "MATCHED": 7})
    order_repo = MagicMock()
    order_repo.list_orders = AsyncMock(return_value=([], 5))

    response = await sync_status(
        fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
        sync_repo=sync_repo,
        order_item_repo=order_item_repo,
        order_repo=order_repo,
    )

    assert response.fulfillment_channel == OrderFulfillmentChannel.AMAZON_FBA
    assert response.total_orders == 5
    assert response.total_unmatched_items == 3
    assert response.total_matched_items == 7
    assert order_item_repo.count_by_status.await_args.kwargs["fulfillment_channel"] == OrderFulfillmentChannel.AMAZON_FBA
    assert order_repo.list_orders.await_args.kwargs["fulfillment_channel"] == OrderFulfillmentChannel.AMAZON_FBA
