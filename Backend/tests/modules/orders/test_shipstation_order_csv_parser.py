import csv
import io

from app.modules.orders import routes


def _build_csv(rows: list[dict[str, str]]) -> str:
    headers = [
        "Order - Number",
        "Bill To - Name",
        "Ship To - Address 1",
        "Ship To - Postal Code",
        "Item - Name",
        "Item - SKU",
        "Item - Qty",
        "Item - Price",
        "Amount - Order Total",
        "Amount - Shipping Cost",
        "Amount - Order Shipping",
        "Date - Order Date",
        "Tracking Number",
        "Source",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def test_shipstation_blank_item_rows_are_skipped_and_unmatched_saved(tmp_path, monkeypatch):
    exception_path = tmp_path / "unmatched_exceptions.csv"
    monkeypatch.setattr(routes, "_UNMATCHED_EXCEPTIONS_CSV_PATH", exception_path)

    csv_text = _build_csv(
        [
            {
                "Order - Number": "A-100",
                "Bill To - Name": "Alice",
                "Ship To - Address 1": "123 Main",
                "Ship To - Postal Code": "10001",
                "Item - Name": "Widget One",
                "Item - SKU": "SKU-1",
                "Item - Qty": "1",
                "Item - Price": "10.00",
                "Amount - Order Total": "12.00",
                "Amount - Shipping Cost": "2.00",
                "Date - Order Date": "4/1/2026 4:42:06 AM",
                "Tracking Number": "TRACK-A100",
                "Source": "amazon",
            },
            {
                "Order - Number": "M-200",
                "Bill To - Name": "Someone Else",
                "Ship To - Address 1": "123 Main",
                "Ship To - Postal Code": "10001",
                "Item - Name": "",
                "Item - SKU": "",
                "Item - Qty": "",
                "Item - Price": "",
                "Amount - Order Total": "0.00",
                "Amount - Shipping Cost": "9.00",
                "Date - Order Date": "4/1/2026 4:42:06 AM",
                "Tracking Number": "TRACK-M200",
                "Source": "shipstation",
            },
            {
                "Order - Number": "M-201",
                "Bill To - Name": "No Parent",
                "Ship To - Address 1": "999 Missing",
                "Ship To - Postal Code": "99999",
                "Item - Name": "",
                "Item - SKU": "",
                "Item - Qty": "",
                "Item - Price": "",
                "Amount - Order Total": "0.00",
                "Amount - Shipping Cost": "8.00",
                "Date - Order Date": "4/1/2026 4:42:06 AM",
                "Tracking Number": "TRACK-M201",
                "Source": "shipstation",
            },
        ]
    )

    parsed, seen, skipped = routes._parse_order_csv(csv_text)

    assert seen == 3
    assert skipped == 2
    assert len(parsed) == 1
    assert parsed[0]["platform_order_number"] == "A-100"
    assert parsed[0]["tracking_number"] == "TRACK-A100"
    assert len(parsed[0]["items"]) == 1

    with exception_path.open(newline="", encoding="utf-8") as handle:
        saved_rows = list(csv.DictReader(handle))
    assert len(saved_rows) == 1
    assert saved_rows[0]["Order - Number"] == "M-201"


def test_shipstation_multiline_order_rows_merge_into_single_order(tmp_path, monkeypatch):
    exception_path = tmp_path / "unmatched_exceptions.csv"
    monkeypatch.setattr(routes, "_UNMATCHED_EXCEPTIONS_CSV_PATH", exception_path)

    csv_text = _build_csv(
        [
            {
                "Order - Number": "SO-500",
                "Bill To - Name": "Bob",
                "Ship To - Address 1": "55 North Ave",
                "Ship To - Postal Code": "30303",
                "Item - Name": "Main Unit",
                "Item - SKU": "MAIN-1",
                "Item - Qty": "1",
                "Item - Price": "100.00",
                "Amount - Order Total": "135.00",
                "Amount - Shipping Cost": "15.00",
                "Date - Order Date": "4/2/2026 10:39:21 AM",
                "Tracking Number": "TRACK-1",
                "Source": "ecwid",
            },
            {
                "Order - Number": "SO-500",
                "Bill To - Name": "Bob",
                "Ship To - Address 1": "55 North Ave",
                "Ship To - Postal Code": "30303",
                "Item - Name": "Warranty",
                "Item - SKU": "WARRANTY",
                "Item - Qty": "1",
                "Item - Price": "35.00",
                "Amount - Order Total": "135.00",
                "Amount - Shipping Cost": "15.00",
                "Date - Order Date": "4/2/2026 10:39:21 AM",
                "Tracking Number": "TRACK-2",
                "Source": "ecwid",
            },
        ]
    )

    parsed, seen, skipped = routes._parse_order_csv(csv_text)

    assert seen == 2
    assert skipped == 0
    assert len(parsed) == 1
    assert parsed[0]["platform_order_number"] == "SO-500"
    assert parsed[0]["total"] == 135.0
    assert parsed[0]["shipping"] == 15.0
    assert parsed[0]["tracking_number"] == "TRACK-1 + TRACK-2"
    assert [item["title"] for item in parsed[0]["items"]] == ["Main Unit", "Warranty"]
    assert [item["platform_sku"] for item in parsed[0]["items"]] == ["MAIN-1", "WARRANTY"]
