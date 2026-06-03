from decimal import Decimal

from app.modules.purchasing.routes import _normalize_purchase_order_item_prices


def test_purchase_item_unit_price_is_derived_from_line_total():
    unit_price, total_price = _normalize_purchase_order_item_prices(
        quantity=5,
        total_price=Decimal("26.99"),
        unit_price=Decimal("99.99"),
    )

    assert unit_price == Decimal("5.398000")
    assert total_price == Decimal("26.99")


def test_purchase_item_unit_price_falls_back_to_input_when_total_missing():
    unit_price, total_price = _normalize_purchase_order_item_prices(
        quantity=4,
        total_price=Decimal("0"),
        unit_price=Decimal("2.50"),
    )

    assert unit_price == Decimal("2.500000")
    assert total_price == Decimal("10.00")


def test_purchase_item_unit_price_handles_repeating_split_with_cent_guardrail():
    unit_price, total_price = _normalize_purchase_order_item_prices(
        quantity=3,
        total_price=Decimal("10.00"),
    )

    assert unit_price == Decimal("3.333333")
    assert total_price == Decimal("10.00")
