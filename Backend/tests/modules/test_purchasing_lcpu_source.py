from decimal import Decimal
from types import SimpleNamespace
from datetime import date

from app.modules.purchasing.routes import _extract_custom_field_string
from app.modules.purchasing.schemas.purchasing import (
    PurchaseOrderCreate,
    PurchaseFileImportSource,
)
from app.integrations.zoho.sync_engine import purchase_order_to_zoho_payload


def test_extract_custom_field_string_from_custom_fields_array():
    payload = {
        "custom_fields": [
            {"api_name": "cf_source", "value": "Local Pickup", "label": "Source"},
            {"api_name": "cf_notes", "value": "Test notes", "label": "Notes"},
        ]
    }
    extracted = _extract_custom_field_string(payload, "source", "po_source", "cf_source")
    assert extracted == "Local Pickup"


def test_extract_custom_field_string_from_hash():
    payload = {
        "custom_field_hash": {
            "cf_source": "Local Pickup",
        }
    }
    extracted = _extract_custom_field_string(payload, "source", "po_source", "cf_source")
    assert extracted == "Local Pickup"


def test_extract_custom_field_string_top_level_fallback():
    payload = {
        "cf_source": "Local Pickup",
    }
    extracted = _extract_custom_field_string(payload, "source", "po_source", "cf_source")
    assert extracted == "Local Pickup"


def test_purchase_order_create_schema_supports_lcpu_source():
    po = PurchaseOrderCreate(
        po_number="PO-9999",
        vendor_id=1,
        order_date=date(2026, 6, 2),
        source="LCPU",
    )
    assert po.source == "LCPU"


def test_purchase_file_import_source_enum_has_lcpu():
    assert PurchaseFileImportSource.LCPU == "lcpu"
    assert "lcpu" in [s.value for s in PurchaseFileImportSource]


def test_purchase_order_outbound_payload_sets_local_pickup_dropdown():
    vendor = SimpleNamespace(zoho_id="vendor-123", name="Local Vendor")
    po = SimpleNamespace(
        po_number="PO-LCPU-1",
        vendor=vendor,
        order_date=date(2026, 6, 2),
        currency="USD",
        tracking_number=None,
        expected_delivery_date=None,
        tax_amount=Decimal("0.00"),
        shipping_amount=Decimal("0.00"),
        handling_amount=Decimal("0.00"),
        source="LCPU",
        is_stationery=False,
        notes=None,
        items=[],
    )
    payload = purchase_order_to_zoho_payload(po)
    cf_fields = payload.get("custom_fields", [])
    source_field = next((cf for cf in cf_fields if cf.get("api_name") == "cf_source"), None)
    assert source_field is not None
    assert source_field["value"] == "Local Pickup"
