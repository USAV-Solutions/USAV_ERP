from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.integrations.zoho.sync_engine import (
    _build_ebay_payment_payload,
    _is_ebay_purchase_source,
    _is_remote_purchase_order_billed,
    purchase_order_metadata_to_zoho_payload,
    purchase_order_to_zoho_payload,
    _verify_purchase_order_sku_parity,
)
from app.modules.purchasing.routes import (
    _extract_zoho_po_charges,
    _import_ebay_purchase_api,
    _import_goodwill_csv,
    _resolve_zoho_external_item_name,
    _upsert_purchase_item,
    import_purchasing_from_zoho,
)
from app.modules.purchasing.schemas import PurchaseFileImportResponse, PurchaseFileImportSource
from app.models import PurchaseOrderItemStatus


def test_extract_zoho_po_charges_supports_non_cf_aliases_in_custom_field_hash():
    payload = {
        "custom_field_hash": {
            "tax_unformatted": "12.50",
            "shipping_fee_unformatted": "4.75",
            "handling_fee_unformatted": "1.25",
        }
    }

    tax_amount, shipping_amount, handling_amount = _extract_zoho_po_charges(payload)

    assert tax_amount == Decimal("12.50")
    assert shipping_amount == Decimal("4.75")
    assert handling_amount == Decimal("1.25")


def test_extract_zoho_po_charges_supports_label_aliases_in_custom_fields():
    payload = {
        "custom_fields": [
            {"label": "tax", "value": "2.00"},
            {"label": "shipping_fee", "value": "3.00"},
            {"label": "handling_fee", "value": "1.00"},
        ]
    }

    tax_amount, shipping_amount, handling_amount = _extract_zoho_po_charges(payload)

    assert tax_amount == Decimal("2.00")
    assert shipping_amount == Decimal("3.00")
    assert handling_amount == Decimal("1.00")


def test_purchase_order_to_zoho_payload_maps_header_custom_and_adjustment_fields():
    po = SimpleNamespace(
        po_number="PO-123",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes="Test notes",
        source="AMAZON_CSV",
        tracking_number="TRK-123",
        tax_amount=Decimal("5.00"),
        shipping_amount=Decimal("7.50"),
        handling_amount=Decimal("2.50"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="External Item",
                quantity=2,
                unit_price=Decimal("10.00"),
                variant=SimpleNamespace(zoho_item_id="it-100"),
            )
        ],
    )

    payload = purchase_order_to_zoho_payload(po)

    assert payload["purchaseorder_number"] == "PO-123"
    assert payload["vendor_id"] == "999001"
    assert payload["reference_number"] == "TRK-123"
    assert payload["adjustment"] == 15.0
    assert payload["adjustment_description"] == "Shipping Fee + Tax + Handling Fee"
    assert "Source: AMAZON_CSV" in payload["notes"]
    assert "Tracking: TRK-123" in payload["notes"]
    assert payload["line_items"][0]["item_id"] == "it-100"

    custom_fields_by_api_name = {field["api_name"]: field for field in payload["custom_fields"]}
    assert custom_fields_by_api_name["cf_source"]["value"] == "Amazon"


def test_purchase_order_to_zoho_payload_keeps_custom_charge_fields_and_rolls_adjustment_with_tax():
    po = SimpleNamespace(
        po_number="PO-124",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes=None,
        source=None,
        tracking_number=None,
        tax_amount=Decimal("1.25"),
        shipping_amount=Decimal("2.50"),
        handling_amount=Decimal("3.75"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="External Item",
                quantity=1,
                unit_price=Decimal("10.00"),
                variant=SimpleNamespace(zoho_item_id="it-100"),
            )
        ],
    )

    payload = purchase_order_to_zoho_payload(po)

    assert payload["adjustment"] == 7.5
    assert payload["adjustment_description"] == "Shipping Fee + Tax + Handling Fee"

    custom_fields_by_api_name = {field["api_name"]: field for field in payload["custom_fields"]}
    assert custom_fields_by_api_name["cf_tax"]["value"] == "1.25"
    assert custom_fields_by_api_name["cf_shipping_fee"]["value"] == "2.50"
    assert custom_fields_by_api_name["cf_handling_fee"]["value"] == "3.75"
    assert custom_fields_by_api_name["cf_source"]["value"] == "Other"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("EBAY_MEKONG_API", "Ebay"),
        ("GOODWILL_CSV", "Goodwill"),
        ("LOCAL_PICKUP", "Local Pickup"),
        ("UNKNOWN_SOURCE", "Other"),
    ],
)
def test_purchase_order_to_zoho_payload_maps_source_custom_field(source, expected):
    po = SimpleNamespace(
        po_number="PO-124A",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes=None,
        source=source,
        tracking_number=None,
        tax_amount=Decimal("0"),
        shipping_amount=Decimal("0"),
        handling_amount=Decimal("0"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="External Item",
                quantity=1,
                unit_price=Decimal("1.00"),
                variant=SimpleNamespace(zoho_item_id="it-100"),
            )
        ],
    )

    payload = purchase_order_to_zoho_payload(po)
    custom_fields_by_api_name = {field["api_name"]: field for field in payload["custom_fields"]}
    assert custom_fields_by_api_name["cf_source"]["value"] == expected


def test_purchase_order_to_zoho_payload_maps_unmatched_lines_to_placeholder_item():
    po = SimpleNamespace(
        po_number="PO-456",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes=None,
        source=None,
        tracking_number=None,
        tax_amount=Decimal("0"),
        shipping_amount=Decimal("0"),
        handling_amount=Decimal("0"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="Unknown Imported Item",
                quantity=1,
                unit_price=Decimal("19.99"),
                variant=None,
            )
        ],
    )

    payload = purchase_order_to_zoho_payload(po, unmatched_item_id="it-placeholder")

    assert payload["line_items"][0]["item_id"] == "it-placeholder"


def test_purchase_order_metadata_to_zoho_payload_excludes_line_items_and_keeps_adjustments():
    po = SimpleNamespace(
        po_number="PO-457",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes=None,
        source=None,
        tracking_number=None,
        tax_amount=Decimal("1.00"),
        shipping_amount=Decimal("2.00"),
        handling_amount=Decimal("3.00"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="Unknown Imported Item",
                quantity=1,
                unit_price=Decimal("19.99"),
                variant=None,
            )
        ],
    )

    payload = purchase_order_metadata_to_zoho_payload(po)

    assert "line_items" not in payload
    assert payload["adjustment"] == 6.0
    assert payload["adjustment_description"] == "Shipping Fee + Tax + Handling Fee"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("EBAY_MEKONG_API", True),
        ("EBAY_USAV_API", True),
        ("AMAZON_API", False),
        (None, False),
    ],
)
def test_is_ebay_purchase_source(source, expected):
    assert _is_ebay_purchase_source(source) is expected


@pytest.mark.parametrize(
    "remote_po,expected",
    [
        ({"status": "billed"}, True),
        ({"status": "open", "bills": [{"bill_id": "123"}]}, True),
        ({"status": "open", "bills": []}, False),
        ({}, False),
        (None, False),
    ],
)
def test_is_remote_purchase_order_billed(remote_po, expected):
    assert _is_remote_purchase_order_billed(remote_po) is expected


def test_build_ebay_payment_payload_maps_required_fields():
    po = SimpleNamespace(
        po_number="PO-980",
        order_date=date(2026, 4, 10),
        vendor=SimpleNamespace(zoho_id="999001"),
    )

    payload = _build_ebay_payment_payload(po, bill_id="bill-100", amount=45.5)

    assert payload["date"] == "2026-04-10"
    assert payload["payment_mode"] == "Credit Card"
    assert payload["paid_through_account_id"]
    assert payload["reference_number"] == "PO-980"
    assert payload["bills"][0]["bill_id"] == "bill-100"
    assert payload["bills"][0]["amount_applied"] == 45.5


@pytest.mark.asyncio
async def test_verify_purchase_order_sku_parity_matches_with_item_lookup_for_missing_line_sku():
    po = SimpleNamespace(
        items=[
            SimpleNamespace(variant=SimpleNamespace(full_sku="ABC-001")),
            SimpleNamespace(variant=None),
        ]
    )

    class _FakeZohoClient:
        async def get_item(self, item_id):
            if item_id == "it-unknown":
                return {"sku": "00000"}
            return {}

    remote_po = {
        "line_items": [
            {"sku": "abc-001"},
            {"item_id": "it-unknown"},
        ]
    }

    has_parity, detail = await _verify_purchase_order_sku_parity(
        po=po,
        zoho=_FakeZohoClient(),
        remote_po=remote_po,
    )

    assert has_parity is True
    assert detail == "sku parity matched"


@pytest.mark.asyncio
async def test_verify_purchase_order_sku_parity_reports_mismatch():
    po = SimpleNamespace(
        items=[
            SimpleNamespace(variant=SimpleNamespace(full_sku="ABC-001")),
            SimpleNamespace(variant=SimpleNamespace(full_sku="DEF-002")),
        ]
    )

    class _FakeZohoClient:
        async def get_item(self, item_id):
            return {"sku": "ZZZ-999"}

    remote_po = {
        "line_items": [
            {"sku": "ABC-001"},
            {"item_id": "it-extra"},
        ]
    }

    has_parity, detail = await _verify_purchase_order_sku_parity(
        po=po,
        zoho=_FakeZohoClient(),
        remote_po=remote_po,
    )

    assert has_parity is False
    assert "missing_skus=DEF-002" in detail
    assert "extra_skus=ZZZ-999" in detail


def test_purchase_order_to_zoho_payload_appends_missing_item_links_to_notes():
    po = SimpleNamespace(
        po_number="PO-789",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes="Please process quickly.",
        source=None,
        tracking_number=None,
        tax_amount=Decimal("0"),
        shipping_amount=Decimal("0"),
        handling_amount=Decimal("0"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="Imported Item A",
                purchase_item_link="https://example.com/items/A",
                condition_note="Used",
                quantity=1,
                unit_price=Decimal("12.00"),
                variant=SimpleNamespace(zoho_item_id="it-200"),
            ),
            SimpleNamespace(
                external_item_name="Imported Item B",
                purchase_item_link="",
                quantity=1,
                unit_price=Decimal("7.00"),
                variant=SimpleNamespace(zoho_item_id="it-201"),
            ),
        ],
    )

    payload = purchase_order_to_zoho_payload(po)

    assert "Imported Item A: https://example.com/items/A, condition: Used" in payload["notes"]


def test_purchase_order_to_zoho_payload_does_not_duplicate_existing_item_link_in_notes():
    existing_link = "https://example.com/items/A"
    po = SimpleNamespace(
        po_number="PO-790",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes=f"Existing context with link: {existing_link}",
        source=None,
        tracking_number=None,
        tax_amount=Decimal("0"),
        shipping_amount=Decimal("0"),
        handling_amount=Decimal("0"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="Imported Item A",
                purchase_item_link=existing_link,
                quantity=1,
                unit_price=Decimal("12.00"),
                variant=SimpleNamespace(zoho_item_id="it-200"),
            )
        ],
    )

    payload = purchase_order_to_zoho_payload(po)

    assert payload["notes"].count(existing_link) == 1
    assert "Imported Item A:" not in payload["notes"]


def test_purchase_order_to_zoho_payload_does_not_drop_second_link_with_shared_prefix():
    po = SimpleNamespace(
        po_number="PO-791",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes="Already synced notes with first link https://example.com/items/123",
        source="EBAY_MEKONG_API",
        tracking_number=None,
        tax_amount=Decimal("0"),
        shipping_amount=Decimal("0"),
        handling_amount=Decimal("0"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="Imported Item A",
                purchase_item_link="https://example.com/items/123",
                quantity=1,
                unit_price=Decimal("12.00"),
                variant=SimpleNamespace(zoho_item_id="it-200"),
            ),
            SimpleNamespace(
                external_item_name="Imported Item B",
                purchase_item_link="https://example.com/items/1234",
                quantity=1,
                unit_price=Decimal("7.00"),
                variant=SimpleNamespace(zoho_item_id="it-201"),
            ),
        ],
    )

    payload = purchase_order_to_zoho_payload(po)

    assert "https://example.com/items/1234" in payload["notes"]


def test_purchase_order_to_zoho_payload_preserves_existing_zoho_notes_and_appends_changed_item_line():
    existing_notes = "Receiver note already on Zoho\nImported Item A: https://example.com/items/A, condition: New"
    po = SimpleNamespace(
        po_number="PO-792",
        order_date=date(2026, 3, 17),
        expected_delivery_date=None,
        currency="USD",
        notes="",
        source=None,
        tracking_number=None,
        tax_amount=Decimal("0"),
        shipping_amount=Decimal("0"),
        handling_amount=Decimal("0"),
        vendor=SimpleNamespace(zoho_id="999001"),
        items=[
            SimpleNamespace(
                external_item_name="Imported Item A",
                purchase_item_link="https://example.com/items/A",
                condition_note="Used",
                quantity=1,
                unit_price=Decimal("12.00"),
                variant=SimpleNamespace(zoho_item_id="it-200"),
            )
        ],
    )

    payload = purchase_order_to_zoho_payload(po, existing_notes=existing_notes)

    assert "Receiver note already on Zoho" in payload["notes"]
    assert "Imported Item A: https://example.com/items/A, condition: New" in payload["notes"]
    assert "Imported Item A: https://example.com/items/A, condition: Used" in payload["notes"]


def test_resolve_zoho_external_item_name_prefers_existing_local_name():
    resolved = _resolve_zoho_external_item_name("Existing Local Name")
    assert resolved == "Existing Local Name"


def test_resolve_zoho_external_item_name_uses_placeholder_when_no_local_name():
    resolved = _resolve_zoho_external_item_name(None)
    assert resolved == "Imported Item"


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        PurchaseFileImportSource.GOODWILL,
        PurchaseFileImportSource.AMAZON,
        PurchaseFileImportSource.ALIEXPRESS,
    ],
)
async def test_upsert_purchase_item_updates_existing_name_when_different(source):
    local_po = SimpleNamespace(zoho_sync_status=None, zoho_sync_error="old-error")
    existing_item = SimpleNamespace(
        id=77,
        external_item_name="Old Imported Name",
        variant_id=321,
        status=PurchaseOrderItemStatus.MATCHED,
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=local_po)
    db.execute = AsyncMock(return_value=_ScalarResult(existing_item))
    db.add = MagicMock()

    po_item_repo = AsyncMock()
    result = PurchaseFileImportResponse(source=source)

    await _upsert_purchase_item(
        local_po_id=10,
        item_id="item-1",
        purchase_item_link="https://example.com/item/1",
        item_name="New Imported Name",
        quantity=2,
        unit_price=Decimal("9.50"),
        po_item_repo=po_item_repo,
        db=db,
        result=result,
    )

    po_item_repo.update.assert_awaited_once()
    payload = po_item_repo.update.await_args.args[1]
    assert payload["external_item_name"] == "New Imported Name"
    assert payload["variant_id"] == 321
    assert payload["status"] == PurchaseOrderItemStatus.MATCHED
    assert result.purchase_order_items_updated == 1
    assert result.purchase_order_items_created == 0


@pytest.mark.asyncio
async def test_upsert_purchase_item_matches_by_purchase_link_when_item_id_missing():
    local_po = SimpleNamespace(zoho_sync_status=None, zoho_sync_error="old-error")
    existing_item = SimpleNamespace(id=88, external_item_name="Old Imported Name")

    db = AsyncMock()
    db.get = AsyncMock(return_value=local_po)
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(None),
            _ScalarResult(existing_item),
        ]
    )
    db.add = MagicMock()

    po_item_repo = AsyncMock()
    result = PurchaseFileImportResponse(source=PurchaseFileImportSource.AMAZON)

    await _upsert_purchase_item(
        local_po_id=10,
        item_id=None,
        purchase_item_link="https://example.com/item/1",
        item_name="Renamed Imported Name",
        quantity=1,
        unit_price=Decimal("12.00"),
        po_item_repo=po_item_repo,
        db=db,
        result=result,
    )

    po_item_repo.update.assert_awaited_once()
    payload = po_item_repo.update.await_args.args[1]
    assert payload["external_item_name"] == "Renamed Imported Name"
    assert payload["purchase_item_link"] == "https://example.com/item/1"
    assert result.purchase_order_items_updated == 1
    assert result.purchase_order_items_created == 0


@pytest.mark.asyncio
async def test_import_goodwill_csv_supports_open_orders_format_and_skips_rows_without_order_number(monkeypatch):
    content = (
        '"Status","Order #","Item #","Item","Seller","Qty","Price","Ended (PT)"\n'
        '"View Order","61595664","259341242","Bose Solo 5 TV Sound System","Goodwill - West Texas","1","$29.97","03/29/2026 06:02:00 PM"\n'
        '"Pay","","260268073","Bose Companion 5 Multimedia Speaker System","Goodwill of Central & Southern Indiana","1","$89.57","04/08/2026 07:12:00 PM"\n'
    )

    vendor_repo = AsyncMock()
    vendor_repo.get_by_field.return_value = SimpleNamespace(id=11)
    po_repo = AsyncMock()
    po_repo.create.return_value = SimpleNamespace(id=101, zoho_sync_status=None, zoho_sync_error=None)
    po_item_repo = AsyncMock()
    db = AsyncMock()

    async def _fake_find_existing_po(_db, _po_number):
        return None

    captured_item_calls = []

    async def _fake_upsert_purchase_item(**kwargs):
        captured_item_calls.append(kwargs)
        return True

    monkeypatch.setattr("app.modules.purchasing.routes._find_existing_po_by_external_id", _fake_find_existing_po)
    monkeypatch.setattr("app.modules.purchasing.routes._upsert_purchase_item", _fake_upsert_purchase_item)

    result = await _import_goodwill_csv(content, vendor_repo, po_repo, po_item_repo, db)

    assert result.source_rows_seen == 2
    assert result.source_rows_skipped == 1
    assert result.purchase_orders_created == 1

    po_repo.create.assert_awaited_once()
    po_payload = po_repo.create.await_args.args[0]
    assert po_payload["po_number"] == "61595664"
    assert po_payload["tax_amount"] == Decimal("0")
    assert po_payload["shipping_amount"] == Decimal("0")
    assert po_payload["handling_amount"] == Decimal("0")

    assert len(captured_item_calls) == 1
    item_call = captured_item_calls[0]
    assert item_call["item_id"] == "259341242"
    assert item_call["quantity"] == 1
    assert item_call["unit_price"] == Decimal("29.97")


@pytest.mark.asyncio
async def test_import_purchasing_from_zoho_requires_date_range():
    with pytest.raises(HTTPException) as exc_info:
        await import_purchasing_from_zoho(
            _current_user=SimpleNamespace(),
            order_date_from=None,
            order_date_to=None,
            vendor_repo=AsyncMock(),
            po_repo=AsyncMock(),
            po_item_repo=AsyncMock(),
            db=AsyncMock(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "order_date_from and order_date_to are required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "expected_po_source"),
    [
        (PurchaseFileImportSource.EBAY_MEKONG, "EBAY_MEKONG_API"),
        (PurchaseFileImportSource.EBAY_PURCHASING, "EBAY_PURCHASING_API"),
    ],
)
async def test_import_ebay_purchase_api_sets_distinct_po_source(monkeypatch, source, expected_po_source):
    class _FakeClient:
        async def fetch_buying_orders_xml(self, since, until):
            return [
                {
                    "po_number": "EB-PO-1",
                    "vendor_name": "eBay Vendor",
                    "order_date": date(2026, 3, 20),
                    "currency": "USD",
                    "tracking_number": "TRACK-1",
                    "tax_amount": "0",
                    "shipping_amount": "0",
                    "handling_amount": "0",
                    "total_amount": "10.00",
                    "items": [
                        {
                            "external_item_id": "1234567890",
                            "external_item_name": "Test Item",
                            "quantity": 1,
                            "unit_price": "10.00",
                        }
                    ],
                }
            ]

    monkeypatch.setattr("app.modules.purchasing.routes._build_ebay_purchase_client", lambda _source: _FakeClient())

    async def _fake_find_existing_po(_db, _po_number):
        return None

    monkeypatch.setattr("app.modules.purchasing.routes._find_existing_po_by_external_id", _fake_find_existing_po)

    created_payloads = []

    async def _fake_create(payload):
        created_payloads.append(payload)
        return SimpleNamespace(id=100)

    po_repo = AsyncMock()
    po_repo.create = AsyncMock(side_effect=_fake_create)
    po_repo.update = AsyncMock()

    po_item_repo = AsyncMock()
    po_item_repo.create = AsyncMock(return_value=SimpleNamespace(id=200))
    po_item_repo.update = AsyncMock()

    vendor_repo = AsyncMock()
    vendor_repo.get_by_name = AsyncMock(return_value=None)
    vendor_repo.create = AsyncMock(return_value=SimpleNamespace(id=50, name="eBay Vendor"))

    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.get = AsyncMock(return_value=SimpleNamespace(zoho_sync_status=None, zoho_sync_error=None))
    db.add = MagicMock()

    result = await _import_ebay_purchase_api(
        source=source,
        order_date_from=date(2026, 3, 1),
        order_date_to=date(2026, 3, 31),
        vendor_repo=vendor_repo,
        po_repo=po_repo,
        po_item_repo=po_item_repo,
        db=db,
    )

    assert result.purchase_orders_created == 1
    assert created_payloads and created_payloads[0]["source"] == expected_po_source
