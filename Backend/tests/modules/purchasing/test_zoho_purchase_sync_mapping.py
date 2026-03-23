from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.integrations.zoho.sync_engine import purchase_order_to_zoho_payload
from app.modules.purchasing.routes import (
    _extract_zoho_po_charges,
    _resolve_zoho_external_item_name,
    _upsert_purchase_item,
    import_purchasing_from_zoho,
)
from app.modules.purchasing.schemas import PurchaseFileImportResponse, PurchaseFileImportSource


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
    assert payload["adjustment"] == 10.0
    assert payload["adjustment_description"] == "Shipping Fee + Handling Fee"
    assert "Source: AMAZON_CSV" in payload["notes"]
    assert "Tracking: TRK-123" in payload["notes"]
    assert payload["line_items"][0]["item_id"] == "it-100"


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
    existing_item = SimpleNamespace(id=77, external_item_name="Old Imported Name")

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
