from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.integrations.zoho.sync_engine import purchase_order_to_zoho_payload
from app.modules.purchasing.routes import _extract_zoho_po_charges


def test_extract_zoho_po_charges_supports_non_cf_aliases_in_custom_field_hash():
    payload = {
        "custom_field_hash": {
            "tax_unformatted": "12.50",
            "shipping_fee_unformatted": "4.75",
            "handling_fee_unformatted": "1.25",
        }
    }

    tax_amount, shipping_amount, handling_amount = _extract_zoho_po_charges(payload)

    assert tax_amount == Decimal("12.50")
    assert shipping_amount == Decimal("4.75")
    assert handling_amount == Decimal("1.25")


def test_extract_zoho_po_charges_supports_label_aliases_in_custom_fields():
    payload = {
        "custom_fields": [
            {"label": "tax", "value": "2.00"},
            {"label": "shipping_fee", "value": "3.00"},
            {"label": "handling_fee", "value": "1.00"},
        ]
    }

    tax_amount, shipping_amount, handling_amount = _extract_zoho_po_charges(payload)

    assert tax_amount == Decimal("2.00")
    assert shipping_amount == Decimal("3.00")
    assert handling_amount == Decimal("1.00")


def test_purchase_order_to_zoho_payload_maps_header_custom_and_adjustment_fields():
    po = SimpleNamespace(
        po_number="PO-123",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes="Test notes",
        source="AMAZON_CSV",
        tracking_number="TRK-123",
        tax_amount=Decimal("5.00"),
        shipping_amount=Decimal("7.50"),
        handling_amount=Decimal("2.50"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="External Item",
                quantity=2,
                unit_price=Decimal("10.00"),
                variant=SimpleNamespace(zoho_item_id="it-100"),
            )
        ],
    )

    payload = purchase_order_to_zoho_payload(po)

    assert payload["purchaseorder_number"] == "PO-123"
    assert payload["vendor_id"] == "999001"
    assert payload["reference_number"] == "TRK-123"
    assert payload["adjustment"] == 10.0
    assert payload["adjustment_description"] == "Shipping Fee + Handling Fee"
    assert "Source: AMAZON_CSV" in payload["notes"]
    assert "Tracking: TRK-123" in payload["notes"]
    assert payload["line_items"][0]["item_id"] == "it-100"
