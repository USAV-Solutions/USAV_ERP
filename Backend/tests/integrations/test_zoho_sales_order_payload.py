from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.integrations.zoho.sync_engine import (
    _is_salesorder_transaction_level_location_error,
    _strip_salesorder_location_fields,
    order_to_zoho_payload,
)
from app.modules.orders.models import OrderFulfillmentChannel, OrderPlatform


def _build_order(
    *,
    platform: OrderPlatform,
    source: str,
    tax_amount: str,
    shipping_amount: str,
    total_amount: str,
    fulfillment_channel: OrderFulfillmentChannel = OrderFulfillmentChannel.SELF_FULFILLED,
):
    customer = SimpleNamespace(zoho_id="contact-1", email="buyer@example.com")
    item = SimpleNamespace(
        item_name="Lifestyle SA-3 Amplifier",
        quantity=1,
        unit_price=Decimal("128.88"),
        external_sku="00246",
        external_item_id="111-2689626-8973035",
        external_asin=None,
        variant=None,
    )
    return SimpleNamespace(
        customer=customer,
        external_order_number="SO-1001",
        external_order_id="EXT-1001",
        tracking_number=None,
        ordered_at=datetime(2026, 6, 2, 12, 0, 0),
        created_at=datetime(2026, 6, 2, 12, 0, 0),
        shipped_at=None,
        carrier=None,
        platform=platform,
        source=source,
        fulfillment_channel=fulfillment_channel,
        items=[item],
        subtotal_amount=Decimal("128.88"),
        tax_amount=Decimal(tax_amount),
        shipping_amount=Decimal(shipping_amount),
        total_amount=Decimal(total_amount),
    )


def test_marketplace_shipstation_order_uses_platform_source_and_excludes_tax_from_zoho_total():
    order = _build_order(
        platform=OrderPlatform.AMAZON,
        source="SHIPSTATION_CSV",
        tax_amount="5.23",
        shipping_amount="37.10",
        total_amount="165.98",
    )

    payload = order_to_zoho_payload(order)

    assert payload["custom_fields"] == [{"api_name": "cf_source", "value": "Amazon"}]
    assert payload["shipping_charge"] == 37.1
    assert payload["adjustment"] == 0.0
    assert payload["adjustment_description"] == "Handling fee"
    assert payload["line_items"][0]["tax_percentage"] == 0.0


def test_shopify_shipstation_order_uses_platform_source_instead_of_shipstation():
    order = _build_order(
        platform=OrderPlatform.SHOPIFY,
        source="SHIPSTATION_CSV",
        tax_amount="4.50",
        shipping_amount="10.00",
        total_amount="145.38",
    )

    payload = order_to_zoho_payload(order)

    assert payload["custom_fields"] == [{"api_name": "cf_source", "value": "Shopify"}]
    assert payload["shipping_charge"] == 10.0
    assert payload["adjustment"] == 6.5
    assert payload["adjustment_description"] == "Tax + Handling fee"
    assert "tax_percentage" not in payload["line_items"][0]


def test_amazon_fba_order_sets_fba_line_item_location_id():
    order = _build_order(
        platform=OrderPlatform.AMAZON,
        source="AMAZON_FBA_CSV",
        tax_amount="2.10",
        shipping_amount="0.00",
        total_amount="130.98",
        fulfillment_channel=OrderFulfillmentChannel.AMAZON_FBA,
    )

    payload = order_to_zoho_payload(order)

    assert "location_id" not in payload
    assert payload["line_items"][0]["location_id"] == "5623409000001937413"


def test_salesorder_location_error_detection_matches_zoho_27520_message():
    exc = Exception(
        'Zoho API error: {"code":27520,"message":"You cannot associate an Item-Level location at a transaction level."}'
    )

    assert _is_salesorder_transaction_level_location_error(exc) is True


def test_strip_salesorder_location_fields_removes_transaction_level_location_only():
    payload = {
        "salesorder_number": "SO-1001",
        "location_id": "5623409000001937413",
        "branch_id": "branch-1",
        "line_items": [{"name": "Lifestyle SA-3 Amplifier", "quantity": 1, "rate": 128.88}],
    }

    sanitized = _strip_salesorder_location_fields(payload)

    assert "location_id" not in sanitized
    assert "branch_id" not in sanitized
    assert sanitized["line_items"] == payload["line_items"]
