from app.modules.orders.routes import _parse_order_csv


def test_shipstation_order_csv_skips_ecwid_rows_and_keeps_other_platforms():
    csv_text = """Order - Number,Item - Name,Item - Qty,Item - Price,Amount - Order Total,Amount - Order Tax,Amount - Shipping Cost,Store Name,Source Platform
EC-100,Ecwid Item,1,10.00,15.00,1.00,4.00,Ecwid Store,Ecwid
AMZ-200,Amazon Item,1,20.00,25.00,2.00,3.00,Amazon Store,Amazon
"""

    orders, seen, skipped = _parse_order_csv(csv_text)

    assert seen == 2
    assert skipped == 1
    assert len(orders) == 1
    assert orders[0]["platform_name"] == "AMAZON"
    assert orders[0]["platform_order_id"] == "AMZ-200"


def test_shipstation_order_csv_detects_ecwid_from_store_name_before_manual_fallback():
    csv_text = """Order - Number,Item - Name,Item - Qty,Item - Price,Amount - Order Total,Store Name
EC-101,Ecwid Item,1,10.00,10.00,My Ecwid Store
"""

    orders, seen, skipped = _parse_order_csv(csv_text)

    assert seen == 1
    assert skipped == 1
    assert orders == []


def test_shipstation_marketplace_line_total_uses_item_price_not_order_total():
    csv_text = """Order - Number,Item - Name,Item - Qty,Item - Price,Amount - Order Total,Amount - Order Tax,Source Platform
EB-300,eBay Item,1,91.68,107.20,15.52,eBay
"""

    orders, seen, skipped = _parse_order_csv(csv_text)

    assert seen == 1
    assert skipped == 0
    assert len(orders) == 1
    assert orders[0]["items"][0]["unit_price"] == 91.68
    assert orders[0]["items"][0]["total_price"] == 91.68
