"""Unit tests for ZohoClient SKU conflict handling."""

from unittest.mock import AsyncMock

import pytest

from app.integrations.zoho.client import ZohoClient


@pytest.mark.asyncio
async def test_sync_composite_item_reuses_existing_standard_item(monkeypatch):
    client = ZohoClient()

    monkeypatch.setattr(client, "get_composite_item_by_sku", AsyncMock(return_value=None))
    monkeypatch.setattr(
        client,
        "get_item_by_sku",
        AsyncMock(return_value={"item_id": "12345", "sku": "TEST-SKU"}),
    )
    create_mock = AsyncMock()
    monkeypatch.setattr(client, "create_composite_item", create_mock)

    result = await client.sync_composite_item(
        sku="TEST-SKU",
        name="Test Name",
        rate=1.0,
        component_items=[{"item_id": "1", "quantity": 1}],
    )

    assert result["item_id"] == "12345"
    create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_composite_item_duplicate_create_falls_back_to_existing(monkeypatch):
    client = ZohoClient()

    get_composite = AsyncMock(side_effect=[None, {"composite_item_id": "cmp-1", "sku": "TEST-SKU"}])
    monkeypatch.setattr(client, "get_composite_item_by_sku", get_composite)
    monkeypatch.setattr(client, "get_item_by_sku", AsyncMock(return_value=None))
    monkeypatch.setattr(
        client,
        "create_composite_item",
        AsyncMock(side_effect=Exception('{"code":1001,"message":"already exists"}')),
    )

    result = await client.sync_composite_item(
        sku="TEST-SKU",
        name="Test Name",
        rate=1.0,
        component_items=[{"item_id": "1", "quantity": 1}],
    )

    assert result["composite_item_id"] == "cmp-1"
    assert get_composite.await_count == 2
