from app.modules.orders.routes import _parse_order_csv


def test_parse_order_csv_groups_rows_by_external_order_id():
    csv_text = """external_order_id,external_order_number,customer_name,item_name,quantity,unit_price,total_amount,currency
SO-1,SO-1,Alice,Item A,1,10,10,USD
SO-1,SO-1,Alice,Item B,2,5,10,USD
SO-2,SO-2,Bob,Item C,1,7,7,USD
"""
    rows, seen, skipped = _parse_order_csv(csv_text)

    assert seen == 3
    assert skipped == 0
    assert len(rows) == 2
    assert rows[0]["platform_order_id"] == "SO-1"
    assert len(rows[0]["items"]) == 2
    assert rows[1]["platform_order_id"] == "SO-2"
    assert len(rows[1]["items"]) == 1

