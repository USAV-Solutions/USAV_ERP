import json
from unittest.mock import AsyncMock

import pytest

from app.integrations.zoho.client import ZohoClient


@pytest.mark.asyncio
async def test_create_sales_return_sends_salesorder_id_as_query_param():
    client = ZohoClient(
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
        organization_id="org",
    )
    client._request = AsyncMock(return_value={"salesreturn": {"salesreturn_id": "SR-1"}})
    payload = {
        "salesorder_id": "SO-1",
        "line_items": [{"item_id": "ITEM-1", "salesorder_item_id": "LINE-1", "quantity": 1}],
    }

    result = await client.create_sales_return(payload)

    assert result == {"salesreturn_id": "SR-1"}
    client._request.assert_awaited_once()
    _, endpoint = client._request.await_args.args
    assert endpoint == "/salesreturns"
    assert client._request.await_args.kwargs["params"] == {"salesorder_id": "SO-1"}
    assert json.loads(client._request.await_args.kwargs["data"]["JSONString"]) == payload


@pytest.mark.asyncio
async def test_create_sales_return_requires_salesorder_id_before_api_call():
    client = ZohoClient(
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
        organization_id="org",
    )
    client._request = AsyncMock()

    with pytest.raises(ValueError, match="salesorder_id is required"):
        await client.create_sales_return({"line_items": []})

    client._request.assert_not_called()
