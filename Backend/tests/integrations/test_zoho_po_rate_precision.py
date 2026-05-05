from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.integrations.zoho.sync_engine import purchase_order_to_zoho_payload


def _build_po_item(*, quantity: int, unit_price: str, total_price: str):
    return SimpleNamespace(
        external_item_name="Lot of 5 Bose Acoustimass Cube Speakers Black",
        quantity=quantity,
        unit_price=Decimal(unit_price),
        total_price=Decimal(total_price),
        variant=None,
        purchase_item_link=None,
        condition_note=None,
    )


def _build_po(item):
    return SimpleNamespace(
        po_number="62158976",
        order_date=date(2026, 4, 19),
        vendor=SimpleNamespace(zoho_id="5623409000001831175"),
        currency="USD",
        notes="Imported from Goodwill open-orders CSV.",
        source="GOODWILL_PICKUP",
        tracking_number=None,
        expected_delivery_date=None,
        is_stationery=False,
        tax_amount=Decimal("2.25"),
        shipping_amount=Decimal("12.08"),
        handling_amount=Decimal("2.00"),
        items=[item],
    )


def test_po_payload_rate_uses_line_total_to_preserve_cent_accurate_total():
    item = _build_po_item(quantity=5, unit_price="5.40", total_price="26.99")
    po = _build_po(item)

    payload = purchase_order_to_zoho_payload(po)

    assert payload["line_items"][0]["rate"] == 5.398


def test_po_payload_rate_falls_back_to_unit_price_when_total_missing():
    item = _build_po_item(quantity=5, unit_price="5.40", total_price="0")
    po = _build_po(item)

    payload = purchase_order_to_zoho_payload(po)

    assert payload["line_items"][0]["rate"] == 5.4
