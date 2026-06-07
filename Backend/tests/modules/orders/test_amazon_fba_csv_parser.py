from app.modules.orders.routes import _parse_amazon_fba_csv


def test_amazon_fba_csv_groups_rows_and_uses_weekly_columns():
    csv_text = """order-id,purchase-date,buyer-id,buyer-name,product-name,sku,asin,quantity,item-price,item-tax,ship-city,ship-state,ship-postal-code,merchant-order-id,ship-country,order-item-id,tracking-number,carrier,shipment-item-tax,shipment-shipping-price,shipment-item-price
114-1,2026-06-04T04:00:11+00:00,buyer-1,Alice,Widget One,SKU-1,ASIN-1,1,27.88,1.53,Dallas,TX,75001,MERCHANT-114,US,ITEM-1,TBA123,AMZN_US,1.53,0.00,27.88
114-1,2026-06-04T04:00:11+00:00,buyer-1,Alice,Widget Two,SKU-2,ASIN-2,2,10.00,0.80,Dallas,TX,75001,MERCHANT-114,US,ITEM-2,TBA456,AMZN_US,0.80,4.99,10.00
"""

    rows, seen, skipped = _parse_amazon_fba_csv(csv_text)

    assert seen == 2
    assert skipped == 0
    assert len(rows) == 1
    assert rows[0]["platform_name"] == "AMAZON"
    assert rows[0]["platform_order_id"] == "114-1"
    assert rows[0]["platform_order_number"] == "MERCHANT-114"
    assert rows[0]["customer_name"] == "Alice"
    assert rows[0]["customer_external_id"] == "buyer-1"
    assert rows[0]["ship_city"] == "Dallas"
    assert rows[0]["tracking_number"] == "TBA123 + TBA456"
    assert rows[0]["carrier"] == "AMZN_US"
    assert rows[0]["subtotal"] == 47.88
    assert rows[0]["tax"] == 2.33
    assert rows[0]["shipping"] == 4.99
    assert rows[0]["total"] == 55.2
    assert [item["platform_item_id"] for item in rows[0]["items"]] == ["ITEM-1", "ITEM-2"]
    assert [item["total_price"] for item in rows[0]["items"]] == [27.88, 20.0]


def test_amazon_fba_csv_skips_rows_missing_required_identifiers():
    csv_text = """order-id,purchase-date,buyer-name,product-name,sku,asin,quantity,item-price
,2026-06-04T04:00:11+00:00,Alice,Widget One,SKU-1,ASIN-1,1,27.88
114-2,2026-06-04T04:00:11+00:00,Bob,,,ASIN-2,1,18.00
"""

    rows, seen, skipped = _parse_amazon_fba_csv(csv_text)

    assert seen == 2
    assert skipped == 2
    assert rows == []


def test_amazon_fba_csv_derives_buyer_id_from_marketplace_email_when_column_blank():
    csv_text = """order-id,purchase-date,buyer-id,buyer-name,buyer-email,product-name,sku,asin,quantity,item-price
114-3,2026-06-04T04:00:11+00:00,,Alice,buyer-3@marketplace.amazon.com,Widget One,SKU-1,ASIN-1,1,27.88
"""

    rows, seen, skipped = _parse_amazon_fba_csv(csv_text)

    assert seen == 1
    assert skipped == 0
    assert rows[0]["customer_external_id"] == "buyer-3"
