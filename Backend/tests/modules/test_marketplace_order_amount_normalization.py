from types import SimpleNamespace

from app.modules.orders.models import OrderPlatform
from app.modules.orders.service import _normalized_item_total, _normalized_order_amounts


def _build_item(*, quantity: int, unit_price: float, total_price: float):
    return SimpleNamespace(quantity=quantity, unit_price=unit_price, total_price=total_price)


def _build_order(*, subtotal: float, tax: float, shipping: float, total: float, items):
    return SimpleNamespace(subtotal=subtotal, tax=tax, shipping=shipping, total=total, items=items)


def test_marketplace_item_total_uses_unit_times_quantity_instead_of_tax_inclusive_total():
    item = _build_item(quantity=1, unit_price=91.68, total_price=107.20)

    normalized_total = _normalized_item_total(item, OrderPlatform.EBAY_USAV)

    assert float(normalized_total) == 91.68


def test_marketplace_order_amounts_exclude_tax_but_keep_shipping_and_handling():
    order = _build_order(
        subtotal=107.20,
        tax=15.52,
        shipping=4.00,
        total=111.20,
        items=[_build_item(quantity=1, unit_price=91.68, total_price=107.20)],
    )

    subtotal, tax, shipping, total = _normalized_order_amounts(order, OrderPlatform.EBAY_USAV)

    assert float(subtotal) == 91.68
    assert float(tax) == 15.52
    assert float(shipping) == 4.0
    assert float(total) == 95.68


def test_non_marketplace_order_amounts_keep_tax_in_total():
    order = _build_order(
        subtotal=91.68,
        tax=6.07,
        shipping=0.0,
        total=97.75,
        items=[_build_item(quantity=1, unit_price=91.68, total_price=97.75)],
    )

    subtotal, tax, shipping, total = _normalized_order_amounts(order, OrderPlatform.SHOPIFY)

    assert float(subtotal) == 91.68
    assert float(total) == 97.75
