from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.integrations.zoho.sync_engine import order_to_zoho_payload
from app.modules.orders.models import OrderPlatform


def _build_order(*, platform: OrderPlatform, source: str, tax_amount: str, shipping_amount: str, total_amount: str):
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
        items=[item],
        subtotal_amount=Decimal("128.88"),
        tax_amount=Decimal(tax_amount),
        shipping_amount=Decimal(shipping_amount),
        total_amount=Decimal(total_amount),
    )


def test_marketplace_shipstation_order_uses_platform_source_and_includes_tax_plus_handling():
    order = _build_order(
        platform=OrderPlatform.AMAZON,
        source="SHIPSTATION_CSV",
        tax_amount="5.23",
        shipping_amount="37.10",
        total_amount="173.71",
    )

    payload = order_to_zoho_payload(order)

    assert payload["custom_fields"] == [{"api_name": "cf_source", "value": "Amazon"}]
    assert payload["shipping_charge"] == 37.1
    assert payload["adjustment"] == 7.73
    assert payload["adjustment_description"] == "Tax + Handling fee"
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
