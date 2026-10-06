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
        "Market - Store Name",
        "Market - Markeplace Name",
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
                "Source": "amazon",
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
                "Source": "amazon",
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


def test_shipstation_detects_dragon_usav_renew_and_walk_in():
    csv_text = _build_csv(
        [
            {
                "Order - Number": "DRAGON-1",
                "Bill To - Name": "Dragon Buyer",
                "Ship To - Address 1": "100 Dragon Way",
                "Ship To - Postal Code": "10001",
                "Item - Name": "Bose Acoustimass",
                "Item - SKU": "SKU-DRAGON",
                "Item - Qty": "1",
                "Item - Price": "50.00",
                "Amount - Order Total": "50.00",
                "Amount - Shipping Cost": "0.00",
                "Date - Order Date": "4/1/2026 4:42:06 AM",
                "Tracking Number": "TRACK-D1",
                "Source": "eBay Dragon",
            },
            {
                "Order - Number": "USAV-1",
                "Bill To - Name": "USAV Buyer",
                "Ship To - Address 1": "200 USAV Ave",
                "Ship To - Postal Code": "10002",
                "Item - Name": "Bose Bracket",
                "Item - SKU": "SKU-USAV",
                "Item - Qty": "1",
                "Item - Price": "20.00",
                "Amount - Order Total": "20.00",
                "Amount - Shipping Cost": "0.00",
                "Date - Order Date": "4/1/2026 4:42:06 AM",
                "Tracking Number": "TRACK-U1",
                "Source": "eBay USAV",
            },
            {
                "Order - Number": "RENEW-1",
                "Bill To - Name": "Renew Buyer",
                "Ship To - Address 1": "300 Renew Blvd",
                "Ship To - Postal Code": "10003",
                "Item - Name": "Renewed Receiver",
                "Item - SKU": "SKU-RENEW",
                "Item - Qty": "1",
                "Item - Price": "150.00",
                "Amount - Order Total": "150.00",
                "Amount - Shipping Cost": "0.00",
                "Date - Order Date": "4/1/2026 4:42:06 AM",
                "Tracking Number": "TRACK-R1",
                "Source": "Amazon Renewed Store",
            },
            {
                "Order - Number": "WALKIN-1",
                "Bill To - Name": "Walkin Buyer",
                "Ship To - Address 1": "400 Local St",
                "Ship To - Postal Code": "10004",
                "Item - Name": "Speaker Cable",
                "Item - SKU": "SKU-WALK",
                "Item - Qty": "1",
                "Item - Price": "15.00",
                "Amount - Order Total": "15.00",
                "Amount - Shipping Cost": "0.00",
                "Date - Order Date": "4/1/2026 4:42:06 AM",
                "Tracking Number": "",
                "Source": "Walk-in",
            },
            {
                "Order - Number": "AMZ-1",
                "Bill To - Name": "Standard Amazon Buyer",
                "Ship To - Address 1": "500 Prime Way",
                "Ship To - Postal Code": "10005",
                "Item - Name": "Headphones",
                "Item - SKU": "SKU-AMZ",
                "Item - Qty": "1",
                "Item - Price": "100.00",
                "Amount - Order Total": "100.00",
                "Amount - Shipping Cost": "0.00",
                "Date - Order Date": "4/1/2026 4:42:06 AM",
                "Tracking Number": "TRACK-A1",
                "Source": "Amazon.com Store",
            },
        ]
    )

    parsed, seen, skipped = routes._parse_order_csv(csv_text)

    assert seen == 5
    assert skipped == 0
    assert len(parsed) == 5

    by_number = {order["platform_order_number"]: order for order in parsed}
    assert by_number["DRAGON-1"]["platform_name"] == "EBAY_DRAGON"
    assert by_number["USAV-1"]["platform_name"] == "EBAY_USAV"
    assert by_number["RENEW-1"]["platform_name"] == "AMAZON_RENEW"
    assert by_number["WALKIN-1"]["platform_name"] == "WALK_IN"
    assert by_number["AMZ-1"]["platform_name"] == "AMAZON"


def test_shipstation_detects_platforms_from_market_store_name_columns():
    csv_text = _build_csv(
        [
            {
                "Order - Number": "112-9412447-4200216",
                "Bill To - Name": "Alvaro Maya",
                "Ship To - Address 1": "593 BONITO AVE",
                "Ship To - Postal Code": "33037",
                "Item - Name": "Bose SoundTouch Pedestal",
                "Item - SKU": "B0FGB55QXD",
                "Item - Qty": "1",
                "Item - Price": "163.88",
                "Amount - Order Total": "176.17",
                "Amount - Shipping Cost": "0.00",
                "Date - Order Date": "9/6/2026 8:31",
                "Tracking Number": "TRACK-R1",
                "Source": "amazon",
                "Market - Store Name": "Amazon Renewed Store",
                "Market - Markeplace Name": "Amazon",
            },
            {
                "Order - Number": "02-15142-25672",
                "Bill To - Name": "Jonathan Hernandez",
                "Ship To - Address 1": "1414 N SUMNER AVE",
                "Ship To - Postal Code": "18508",
                "Item - Name": "Bose CineMate 520",
                "Item - SKU": "",
                "Item - Qty": "1",
                "Item - Price": "1198.00",
                "Amount - Order Total": "1428.59",
                "Amount - Shipping Cost": "46.56",
                "Date - Order Date": "9/5/2026 7:33",
                "Tracking Number": "TRACK-D1",
                "Source": "ebay_v2",
                "Market - Store Name": "eBay Dragonhn",
                "Market - Markeplace Name": "eBay",
            },
            {
                "Order - Number": "03-15140-76176",
                "Bill To - Name": "Michael Chance",
                "Ship To - Address 1": "4 Bollinger Rd",
                "Ship To - Postal Code": "92270",
                "Item - Name": "Bose Speaker Stands",
                "Item - SKU": "",
                "Item - Qty": "1",
                "Item - Price": "116.00",
                "Amount - Order Total": "124.99",
                "Amount - Shipping Cost": "0.00",
                "Date - Order Date": "9/5/2026 10:53",
                "Tracking Number": "TRACK-M1",
                "Source": "ebay_v2",
                "Market - Store Name": "eBay Mekong",
                "Market - Markeplace Name": "eBay",
            },
            {
                "Order - Number": "09-15129-79463",
                "Bill To - Name": "David Martin",
                "Ship To - Address 1": "770 N Hanover St",
                "Ship To - Postal Code": "17022",
                "Item - Name": "Replacement Power Transformer",
                "Item - SKU": "",
                "Item - Qty": "1",
                "Item - Price": "29.88",
                "Amount - Order Total": "31.68",
                "Amount - Shipping Cost": "0.00",
                "Date - Order Date": "9/5/2026 11:40",
                "Tracking Number": "TRACK-U1",
                "Source": "ebay_v2",
                "Market - Store Name": "eBay USAV",
                "Market - Markeplace Name": "eBay",
            },
        ]
    )

    parsed, seen, skipped = routes._parse_order_csv(csv_text)

    assert seen == 4
    assert skipped == 0
    assert len(parsed) == 4

    by_number = {order["platform_order_number"]: order for order in parsed}
    assert by_number["112-9412447-4200216"]["platform_name"] == "AMAZON_RENEW"
    assert by_number["02-15142-25672"]["platform_name"] == "EBAY_DRAGON"
    assert by_number["03-15140-76176"]["platform_name"] == "EBAY_MEKONG"
    assert by_number["09-15129-79463"]["platform_name"] == "EBAY_USAV"

