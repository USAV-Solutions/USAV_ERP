"""Unit tests for the FBA merge pipeline (port of FBA/main.py steps 1-3)."""
import csv
import io

import pytest

from app.modules.fba.pipeline import (
    PipelineError,
    build_merged_rows,
    merge_rows,
    pick_period_days,
    rows_to_csv_text,
)

ALL_ORDERS_HEADERS = [
    "amazon-order-id", "merchant-order-id", "purchase-date", "order-status",
    "fulfillment-channel", "product-name", "sku", "asin", "quantity",
    "item-price", "item-tax", "ship-city", "ship-state", "ship-postal-code",
    "order-item-id",
]


def _tsv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=ALL_ORDERS_HEADERS, delimiter="\t")
    w.writeheader()
    for r in rows:
        w.writerow({h: r.get(h, "") for h in ALL_ORDERS_HEADERS})
    return buf.getvalue()


FULFILLMENT_HEADERS = [
    "Amazon Order Id", "Merchant Order Id", "Amazon Order Item Id", "Purchase Date",
    "Payments Date", "Shipment Date", "Buyer Email", "Buyer Name", "Merchant SKU",
    "Title", "Shipped Quantity", "Item Price", "Carrier", "Tracking Number",
]


def _csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FULFILLMENT_HEADERS)
    w.writeheader()
    for r in rows:
        w.writerow({h: r.get(h, "") for h in FULFILLMENT_HEADERS})
    return buf.getvalue()


def test_only_amazon_shipped_rows_are_kept():
    txt = _tsv([
        {"amazon-order-id": "A1", "merchant-order-id": "A1", "order-status": "Shipped",
         "fulfillment-channel": "Amazon", "sku": "S1", "quantity": "1", "item-price": "10"},
        {"amazon-order-id": "B2", "merchant-order-id": "B2", "order-status": "Shipped",
         "fulfillment-channel": "Merchant", "sku": "S2", "quantity": "1", "item-price": "5"},
        {"amazon-order-id": "C3", "merchant-order-id": "C3", "order-status": "Pending",
         "fulfillment-channel": "Amazon", "sku": "S3", "quantity": "1", "item-price": "7"},
    ])
    ff = _csv([
        {"Amazon Order Id": "A1", "Merchant Order Id": "A1", "Buyer Name": "Jane Doe",
         "Buyer Email": "jane@marketplace.amazon.com", "Merchant SKU": "S1",
         "Tracking Number": "1Z999", "Carrier": "UPS"},
    ])
    fieldnames, rows, stats = build_merged_rows(txt, ff)

    assert stats.all_order_rows == 3
    assert stats.fba_order_rows == 1          # only A1 (Amazon + Shipped)
    assert [r["order-id"] for r in rows] == ["A1"]
    assert rows[0]["buyer-name"] == "Jane Doe"
    assert rows[0]["tracking-number"] == "1Z999"
    assert rows[0]["buyer-id"] == "jane"      # local-part of buyer-email
    assert fieldnames[0] == "order-id" and fieldnames[1] == "buyer-name"


def test_missing_buyer_name_is_counted_and_survives():
    txt = _tsv([
        {"amazon-order-id": "A1", "merchant-order-id": "A1", "order-status": "Shipping",
         "fulfillment-channel": "Amazon", "sku": "S1", "quantity": "2", "item-price": "10"},
    ])
    ff = _csv([{"Amazon Order Id": "A1", "Merchant Order Id": "A1", "Merchant SKU": "S1"}])
    _fn, rows, stats = build_merged_rows(txt, ff)
    assert stats.rows_missing_buyer_name == 1
    assert rows[0]["order-id"] == "A1"
    assert rows[0].get("buyer-name", "") == ""


def test_all_orders_without_matching_shipment_still_merges():
    txt = _tsv([
        {"amazon-order-id": "A1", "merchant-order-id": "M1", "order-status": "Shipped",
         "fulfillment-channel": "Amazon", "sku": "S1", "quantity": "1", "item-price": "9"},
    ])
    ff = _csv([])  # header only
    _fn, rows, _stats = build_merged_rows(txt, ff)
    assert len(rows) == 1
    assert rows[0]["order-id"] == "A1"


def test_bad_input_raises_pipeline_error():
    with pytest.raises(PipelineError):
        build_merged_rows("not\ta\treport\n", _csv([]))
    with pytest.raises(PipelineError):
        build_merged_rows(_tsv([]), "nope,not,a,shipment,report\n")


def test_roundtrip_csv_is_parseable_by_amazon_fba_parser():
    from app.modules.orders.routes import _parse_amazon_fba_csv

    txt = _tsv([
        {"amazon-order-id": "A1", "merchant-order-id": "A1", "order-status": "Shipped",
         "fulfillment-channel": "Amazon", "sku": "S1", "asin": "AS1", "product-name": "Widget",
         "quantity": "3", "item-price": "12", "purchase-date": "2026-08-01T00:00:00Z"},
    ])
    ff = _csv([
        {"Amazon Order Id": "A1", "Merchant Order Id": "A1", "Merchant SKU": "S1",
         "Buyer Name": "Sam Smith", "Shipped Quantity": "3", "Item Price": "12",
         "Tracking Number": "TRK1", "Carrier": "USPS"},
    ])
    fieldnames, rows, _stats = build_merged_rows(txt, ff)
    text = rows_to_csv_text(fieldnames, rows)
    parsed, seen, skipped = _parse_amazon_fba_csv(text)
    assert seen == 1 and skipped == 0
    assert parsed[0]["platform_order_id"] == "A1"
    assert parsed[0]["customer_name"] == "Sam Smith"
    assert parsed[0]["items"][0]["quantity"] == 3


def test_merge_rows_prefers_shipment_buyer_name_over_blank():
    merged = merge_rows(
        {"amazon-order-id": "A1", "product-name": "X"},
        {"amazon-order-id": "A1", "buyer-name": "Pat Lee", "title": "X"},
    )
    assert merged["buyer-name"] == "Pat Lee"
    assert merged["order-id"] == "A1"


@pytest.mark.parametrize(
    "days_needed,expected",
    [(1, 7), (7, 7), (8, 15), (15, 15), (30, 30), (45, 60), (999, 60)],
)
def test_pick_period_days(days_needed, expected):
    assert pick_period_days(days_needed) == expected
