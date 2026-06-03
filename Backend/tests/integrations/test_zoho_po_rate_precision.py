from datetime import date
from decimal import Decimal, ROUND_HALF_UP
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


def _build_po(item, *, tax_amount: str = "2.25", shipping_amount: str = "12.08", handling_amount: str = "2.00"):
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
        tax_amount=Decimal(tax_amount),
        shipping_amount=Decimal(shipping_amount),
        handling_amount=Decimal(handling_amount),
        items=[item],
    )


def test_po_payload_rate_uses_line_total_to_preserve_cent_accurate_total():
    item = _build_po_item(quantity=5, unit_price="5.40", total_price="26.99")
    po = _build_po(item, tax_amount="0", shipping_amount="0", handling_amount="0")

    payload = purchase_order_to_zoho_payload(po)

    assert payload["line_items"][0]["rate"] == 5.398


def test_po_payload_rate_falls_back_to_unit_price_when_total_missing():
    item = _build_po_item(quantity=5, unit_price="5.40", total_price="0")
    po = _build_po(item, tax_amount="0", shipping_amount="0", handling_amount="0")

    payload = purchase_order_to_zoho_payload(po)

    assert payload["line_items"][0]["rate"] == 5.4


def test_po_payload_spreads_adjustments_across_line_items_and_drops_po_adjustment():
    first_item = _build_po_item(quantity=2, unit_price="10.00", total_price="20.00")
    second_item = _build_po_item(quantity=1, unit_price="5.00", total_price="5.00")
    po = _build_po(
        first_item,
        tax_amount="5.00",
        shipping_amount="10.00",
        handling_amount="0.00",
    )
    po.items = [first_item, second_item]

    payload = purchase_order_to_zoho_payload(po)

    assert "adjustment" not in payload
    assert "adjustment_description" not in payload
    assert payload["line_items"][0]["rate"] == 13.75
    assert payload["line_items"][1]["rate"] == 12.5


def test_po_payload_keeps_total_exact_when_adjustment_share_repeats():
    first_item = _build_po_item(quantity=3, unit_price="1.00", total_price="3.00")
    second_item = _build_po_item(quantity=2, unit_price="2.00", total_price="4.00")
    po = _build_po(
        first_item,
        tax_amount="1.00",
        shipping_amount="0.00",
        handling_amount="0.00",
    )
    po.items = [first_item, second_item]

    payload = purchase_order_to_zoho_payload(po)
    payload_total = sum(
        Decimal(str(line["quantity"])) * Decimal(str(line["rate"]))
        for line in payload["line_items"]
    )

    assert payload_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("8.00")
