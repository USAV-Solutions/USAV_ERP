import pytest
from unittest.mock import AsyncMock

from app.integrations.base import BasePlatformClient, ExternalOrder
from app.integrations.shopify.client import ShopifyClient
from app.modules.orders.routes import _IMPORT_SOURCE_TO_PLATFORM
from app.modules.orders.schemas.sync import SalesImportApiSource
from app.modules.orders.service import _ORDER_TO_ENTITY_PLATFORM, OrderPlatform, Platform


def test_shopify_client_implements_base_platform_client():
    client = ShopifyClient(
        shop_url="test-shop.myshopify.com",
        access_token="shpat_test123",
        api_version="2024-10",
    )
    assert isinstance(client, BasePlatformClient)
    assert client.platform_name == "SHOPIFY"
    assert client.is_configured is True


def test_sales_import_api_source_includes_shopify():
    assert SalesImportApiSource.SHOPIFY == "SHOPIFY"
    assert _IMPORT_SOURCE_TO_PLATFORM[SalesImportApiSource.SHOPIFY] == "SHOPIFY"
    assert _ORDER_TO_ENTITY_PLATFORM[OrderPlatform.SHOPIFY] == Platform.SHOPIFY


def test_parse_shopify_order():
    client = ShopifyClient("test.myshopify.com", "token")

    raw_node = {
        "id": "gid://shopify/Order/1001",
        "name": "#1001",
        "createdAt": "2026-09-10T08:00:00Z",
        "currencyCode": "USD",
        "email": "customer@example.com",
        "subtotalPriceSet": {"shopMoney": {"amount": "250.00"}},
        "totalTaxSet": {"shopMoney": {"amount": "20.00"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "15.00"}},
        "totalPriceSet": {"shopMoney": {"amount": "285.00"}},
        "customer": {
            "id": "gid://shopify/Customer/501",
            "firstName": "John",
            "lastName": "Doe",
            "email": "john@example.com",
            "phone": "+15551234567",
        },
        "shippingAddress": {
            "name": "John Doe",
            "address1": "123 Main St",
            "address2": "Apt 4B",
            "city": "Dallas",
            "provinceCode": "TX",
            "zip": "75001",
            "countryCodeV2": "US",
            "company": "Acme Inc",
            "phone": "+15551234567",
        },
        "fulfillments": [
            {
                "trackingInfo": [
                    {"number": "1Z9999999999999999", "company": "UPS"}
                ]
            }
        ],
        "lineItems": {
            "edges": [
                {
                    "node": {
                        "id": "gid://shopify/LineItem/1",
                        "sku": "00031-G",
                        "title": "Bose Wave Music System III",
                        "quantity": 1,
                        "variant": {"id": "gid://shopify/ProductVariant/901"},
                        "originalUnitPriceSet": {"shopMoney": {"amount": "250.00"}},
                        "discountedTotalSet": {"shopMoney": {"amount": "250.00"}},
                    }
                }
            ]
        },
    }

    order: ExternalOrder = client._parse_shopify_order(raw_node)

    assert order.platform_order_id == "gid://shopify/Order/1001"
    assert order.platform_order_number == "#1001"
    assert order.customer_name == "John Doe"
    assert order.customer_email == "john@example.com"
    assert order.customer_phone == "+15551234567"
    assert order.customer_company == "Acme Inc"
    assert order.customer_source == "SHOPIFY_API"
    assert order.ship_address_line1 == "123 Main St"
    assert order.ship_address_line2 == "Apt 4B"
    assert order.ship_city == "Dallas"
    assert order.ship_state == "TX"
    assert order.ship_postal_code == "75001"
    assert order.ship_country == "US"
    assert order.subtotal == 250.00
    assert order.tax == 20.00
    assert order.shipping == 15.00
    assert order.total == 285.00
    assert order.currency == "USD"
    assert order.tracking_number == "1Z9999999999999999"
    assert order.carrier == "UPS"

    assert len(order.items) == 1
    item = order.items[0]
    assert item.platform_item_id == "gid://shopify/ProductVariant/901"
    assert item.platform_sku == "00031-G"
    assert item.title == "Bose Wave Music System III"
    assert item.quantity == 1
    assert item.unit_price == 250.00
    assert item.total_price == 250.00


@pytest.mark.asyncio
async def test_fetch_orders_paginated():
    client = ShopifyClient("test.myshopify.com", "token")
    mock_response = {
        "data": {
            "orders": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {
                        "node": {
                            "id": "gid://shopify/Order/2001",
                            "name": "#2001",
                            "createdAt": "2026-09-10T10:00:00Z",
                            "currencyCode": "USD",
                            "lineItems": {"edges": []},
                        }
                    }
                ],
            }
        }
    }
    client._graphql = AsyncMock(return_value=mock_response)

    orders = await client.fetch_orders()
    assert len(orders) == 1
    assert orders[0].platform_order_id == "gid://shopify/Order/2001"
    assert orders[0].platform_order_number == "#2001"
