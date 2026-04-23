"""
Zoho two-way sync engine.

Provides:
* **Outbound** – SQLAlchemy event listeners on ``ProductVariant`` and
  ``Customer`` that enqueue background tasks whenever a record is created
  or updated (unless the change originated from an inbound webhook).
* **Inbound** – Functions consumed by the webhook dispatcher to apply
  Zoho-side changes to the local database (with echo-loop prevention).
* **Mappers** – Convert local models to/from Zoho API payloads.

The "queue" is currently ``asyncio.create_task`` which runs in-process
(sufficient for single-instance deployments).  Swapping to Redis/ARQ later
requires only changing ``_enqueue_*`` helpers.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import event

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient, RateLimitError
from app.integrations.zoho.security import generate_payload_hash
from app.models.entities import Customer, ProductVariant, ZohoSyncStatus
from app.models.purchasing import PurchaseOrder, PurchaseOrderItem, Vendor
from app.modules.orders.models import Order, OrderItem

logger = logging.getLogger(__name__)

UNMATCHED_PLACEHOLDER_ITEM_NAME = "unmatched item"
UNMATCHED_PLACEHOLDER_ITEM_SKU = "00000"
EBAY_PO_SOURCE_PREFIX = "EBAY_"
PAYMENT_TERMS_DUE_ON_RECEIPT = 0

VALID_ZOHO_PO_SOURCE_VALUES = {
    "Ebay",
    "Amazon",
    "Goodwill",
    "AliExpress",
    "Local Pickup",
    "Other",
}

EXACT_ZOHO_PO_SOURCE_MAP = {
    "EBAY_MEKONG_API": "Ebay",
    "EBAY_PURCHASING_API": "Ebay",
    "EBAY_USAV_API": "Ebay",
    "EBAY_DRAGON_API": "Ebay",
    "AMAZON_CSV": "Amazon",
    "GOODWILL_CSV": "Goodwill",
    "GOODWILL_PICKUP": "Goodwill",
    "ALIEXPRESS_JSON": "AliExpress",
    "ALIEXPRESS_CSV": "AliExpress",
    "MANUAL": "Other",
    "ZOHO_IMPORT": "Other",
}

_UNMATCHED_PLACEHOLDER_ITEM_ID_CACHE: Optional[str] = None


# =========================================================================
# PAYLOAD MAPPERS  (USAV → Zoho)
# =========================================================================

def variant_to_zoho_payload(variant: ProductVariant) -> dict[str, Any]:
    """Build the Zoho item payload from a *fully‑loaded* ProductVariant."""
    identity = getattr(variant, "identity", None)
    family = identity.family if identity else None

    payload: dict[str, Any] = {
        "name": variant.variant_name or (family.base_name if family else variant.full_sku),
        "sku": variant.full_sku,
        "description": family.description if family else "",
    }

    # Price – take the first available listing price.
    # Some call sites (or legacy code) may accidentally attach a single
    # PlatformListing instance instead of a list; normalize to an iterable
    # to avoid TypeError: 'PlatformListing' object is not iterable.
    listings_attr = getattr(variant, "listings", None) or []
    listings = (
        listings_attr
        if isinstance(listings_attr, (list, tuple))
        else [listings_attr]
    )

    listing_prices = [
        float(listing.listing_price)
        for listing in listings
        if listing and listing.listing_price is not None
    ]
    if listing_prices:
        payload["rate"] = listing_prices[0]

    if identity:
        if identity.weight is not None:
            payload["weight"] = float(identity.weight)
        if identity.dimension_length is not None:
            payload["length"] = float(identity.dimension_length)
        if identity.dimension_width is not None:
            payload["width"] = float(identity.dimension_width)
        if identity.dimension_height is not None:
            payload["height"] = float(identity.dimension_height)

    return {k: v for k, v in payload.items() if v is not None}


def customer_to_zoho_payload(customer: Customer) -> dict[str, Any]:
    """Build a Zoho *contact* payload from a local ``Customer``."""
    payload: dict[str, Any] = {
        "contact_name": customer.name,
        "contact_type": "customer",
    }
    if customer.email:
        payload["email"] = customer.email
    if customer.phone:
        payload["phone"] = customer.phone
    if customer.company_name:
        payload["company_name"] = customer.company_name

    # Billing address
    address: dict[str, str] = {}
    if customer.address_line1:
        address["address"] = customer.address_line1
    if customer.address_line2:
        address["street2"] = customer.address_line2
    if customer.city:
        address["city"] = customer.city
    if customer.state:
        address["state"] = customer.state
    if customer.postal_code:
        address["zip"] = customer.postal_code
    if customer.country:
        address["country"] = customer.country
    if address:
        payload["billing_address"] = address

    return payload


def vendor_to_zoho_payload(vendor: Vendor) -> dict[str, Any]:
    """Build a Zoho contact payload from a local ``Vendor``."""
    payload: dict[str, Any] = {
        "contact_name": vendor.name,
        "contact_type": "vendor",
    }
    if vendor.email:
        payload["email"] = vendor.email
    if vendor.phone:
        payload["phone"] = vendor.phone
    if vendor.address:
        payload["billing_address"] = {"address": vendor.address}
    return payload


def _normalize_source_to_zoho_dropdown(source: str) -> str:
    text = str(source or "").strip().upper().replace("-", "_").replace(" ", "_")
    if "EBAY" in text:
        return "Ebay"
    if "AMAZON" in text:
        return "Amazon"
    if "GOODWILL" in text:
        return "Goodwill"
    if "ALIEXPRESS" in text:
        return "AliExpress"
    if "LOCAL_PICKUP" in text or "LOCALPICKUP" in text:
        return "Local Pickup"
    return "Other"


def _resolve_source_to_zoho_dropdown(source: str) -> str:
    normalized = str(source or "").strip().upper()
    mapped = EXACT_ZOHO_PO_SOURCE_MAP.get(normalized)
    if mapped:
        return mapped

    fallback = _normalize_source_to_zoho_dropdown(source)
    if fallback in VALID_ZOHO_PO_SOURCE_VALUES:
        return fallback
    return "Other"


def purchase_order_to_zoho_payload(
    po: PurchaseOrder,
    *,
    unmatched_item_id: Optional[str] = None,
    existing_notes: Optional[str] = None,
) -> dict[str, Any]:
    """Build a Zoho purchase-order payload from a local ``PurchaseOrder``."""
    vendor = getattr(po, "vendor", None)
    if not (vendor and vendor.zoho_id):
        raise ValueError("PurchaseOrder is missing vendor.zoho_id; sync vendor first.")

    notes_parts: list[str] = []
    if existing_notes and str(existing_notes).strip():
        notes_parts.append(str(existing_notes).strip())

    existing_notes_text_lc = "\n".join(p for p in notes_parts if p).lower()

    def _append_if_missing(line: str) -> None:
        nonlocal existing_notes_text_lc
        normalized = line.strip()
        if not normalized:
            return
        if normalized.lower() in existing_notes_text_lc:
            return
        notes_parts.append(normalized)
        existing_notes_text_lc = "\n".join(p for p in notes_parts if p).lower()

    if po.notes:
        _append_if_missing(str(po.notes).strip())
    if getattr(po, "source", None):
        _append_if_missing(f"Source: {po.source}")
    if getattr(po, "tracking_number", None):
        _append_if_missing(f"Tracking: {po.tracking_number}")
    if getattr(po, "is_stationery", False):
        _append_if_missing("Stationery Purchase: true")

    item_note_lines: list[str] = []
    item_note_lines_added_lc: set[str] = set()
    for item in po.items or []:
        link = str(getattr(item, "purchase_item_link", "") or "").strip()
        if not link:
            continue
        item_name = str(getattr(item, "external_item_name", "") or "").strip() or "Item"
        condition_note = str(getattr(item, "condition_note", "") or "").strip()
        item_line = (
            f"{item_name}: {link}, condition: {condition_note}"
            if condition_note
            else f"{item_name}: {link}"
        )
        normalized_line = item_line.lower()
        if normalized_line in existing_notes_text_lc or normalized_line in item_note_lines_added_lc:
            continue
        item_note_lines.append(item_line)
        item_note_lines_added_lc.add(normalized_line)

    if item_note_lines:
        notes_parts.append("\n".join(item_note_lines))

    payload: dict[str, Any] = {
        "purchaseorder_number": po.po_number,
        "date": po.order_date.strftime("%Y-%m-%d"),
        "vendor_id": vendor.zoho_id,
        "currency_code": po.currency,
        "notes": "\n".join(p for p in notes_parts if p),
    }
    if getattr(po, "tracking_number", None):
        payload["reference_number"] = po.tracking_number
    if po.expected_delivery_date:
        payload["delivery_date"] = po.expected_delivery_date.strftime("%Y-%m-%d")

    def _to_float(value: Any) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    tax_amount = _to_float(getattr(po, "tax_amount", 0))
    shipping_amount = _to_float(getattr(po, "shipping_amount", 0))
    handling_amount = _to_float(getattr(po, "handling_amount", 0))

    custom_fields: list[dict[str, Any]] = []
    tax_field: dict[str, Any] = {"api_name": "cf_tax", "value": f"{tax_amount:.2f}"}
    if settings.zoho_po_cf_tax_id:
        tax_field["customfield_id"] = settings.zoho_po_cf_tax_id
    custom_fields.append(tax_field)

    shipping_field: dict[str, Any] = {
        "api_name": "cf_shipping_fee",
        "value": f"{shipping_amount:.2f}",
    }
    if settings.zoho_po_cf_shipping_fee_id:
        shipping_field["customfield_id"] = settings.zoho_po_cf_shipping_fee_id
    custom_fields.append(shipping_field)

    handling_field: dict[str, Any] = {
        "api_name": "cf_handling_fee",
        "value": f"{handling_amount:.2f}",
    }
    if settings.zoho_po_cf_handling_fee_id:
        handling_field["customfield_id"] = settings.zoho_po_cf_handling_fee_id
    custom_fields.append(handling_field)

    source_value = _resolve_source_to_zoho_dropdown(str(getattr(po, "source", "") or ""))
    source_field: dict[str, Any] = {
        "api_name": "cf_source",
        "value": source_value,
    }
    if settings.zoho_po_cf_source_id:
        source_field["customfield_id"] = settings.zoho_po_cf_source_id
    custom_fields.append(source_field)

    payload["custom_fields"] = custom_fields

    stationery_location_id = (
        str(getattr(settings, "zoho_po_stationery_location_id", "") or "").strip() or None
    )

    if getattr(po, "is_stationery", False):
        if stationery_location_id:
            # Zoho requires line locations to match transaction-level location
            # (or the item's immediate warehouse). Set PO-level location when
            # routing stationery purchases to a dedicated warehouse.
            payload["location_id"] = stationery_location_id
        if settings.zoho_po_stationery_delivery_address:
            payload["delivery_address"] = {
                "address": settings.zoho_po_stationery_delivery_address,
            }

    # Keep legacy adjustment populated, but include tax in the rollup.
    payload["adjustment"] = tax_amount + shipping_amount + handling_amount
    payload["adjustment_description"] = "Shipping Fee + Tax + Handling Fee"

    line_items: list[dict[str, Any]] = []
    for item in po.items or []:
        variant = getattr(item, "variant", None)
        variant_sku = str(getattr(variant, "full_sku", "") or "").upper()
        is_stationery_line = variant_sku.startswith("STAT-")

        li: dict[str, Any] = {
            "name": item.external_item_name,
            "quantity": item.quantity,
            "rate": float(item.unit_price),
        }
        if variant and variant.zoho_item_id:
            li["item_id"] = variant.zoho_item_id
        elif unmatched_item_id:
            li["item_id"] = unmatched_item_id
        if getattr(po, "is_stationery", False) and is_stationery_line and stationery_location_id:
            li["location_id"] = stationery_location_id
        if getattr(po, "is_stationery", False) and settings.zoho_po_stationery_purchase_account_id:
            li["account_id"] = settings.zoho_po_stationery_purchase_account_id
        line_items.append(li)
    payload["line_items"] = line_items

    return payload


def purchase_order_metadata_to_zoho_payload(
    po: PurchaseOrder,
    *,
    existing_notes: Optional[str] = None,
) -> dict[str, Any]:
    """Build a Zoho purchase-order payload limited to metadata fields only."""
    payload = purchase_order_to_zoho_payload(
        po,
        existing_notes=existing_notes,
    )
    payload.pop("line_items", None)
    return payload


def _normalize_sku(raw: Any) -> Optional[str]:
    text = str(raw or "").strip().upper()
    return text or None


def _extract_local_purchase_order_skus(po: PurchaseOrder) -> set[str]:
    skus: set[str] = set()
    for item in po.items or []:
        variant = getattr(item, "variant", None)
        if variant and getattr(variant, "full_sku", None):
            normalized = _normalize_sku(variant.full_sku)
            if normalized:
                skus.add(normalized)
            continue

        placeholder_sku = _normalize_sku(UNMATCHED_PLACEHOLDER_ITEM_SKU)
        if placeholder_sku:
            skus.add(placeholder_sku)

    return skus


async def _extract_remote_purchase_order_skus(
    zoho: ZohoClient,
    remote_po: dict[str, Any],
) -> set[str]:
    skus: set[str] = set()
    item_cache: dict[str, Optional[str]] = {}
    for line in remote_po.get("line_items") or []:
        if not isinstance(line, dict):
            continue

        direct_sku = _normalize_sku(line.get("sku") or line.get("item_sku"))
        if direct_sku:
            skus.add(direct_sku)
            continue

        item_id = str(line.get("item_id") or "").strip()
        if not item_id:
            continue

        if item_id not in item_cache:
            try:
                item = await zoho.get_item(item_id)
            except Exception as exc:
                logger.warning(
                    "sync_po_outbound: failed to resolve Zoho item sku | item_id=%s error=%s",
                    item_id,
                    exc,
                )
                item_cache[item_id] = None
            else:
                item_cache[item_id] = _normalize_sku(item.get("sku") if item else None)

        resolved_sku = item_cache[item_id]
        if resolved_sku:
            skus.add(resolved_sku)

    return skus


async def _verify_purchase_order_sku_parity(
    *,
    po: PurchaseOrder,
    zoho: ZohoClient,
    remote_po: dict[str, Any],
) -> tuple[bool, str]:
    local_skus = _extract_local_purchase_order_skus(po)
    remote_skus = await _extract_remote_purchase_order_skus(zoho, remote_po)

    missing = sorted(local_skus - remote_skus)
    extra = sorted(remote_skus - local_skus)

    if not missing and not extra:
        return True, "sku parity matched"

    missing_preview = ", ".join(missing[:5]) if missing else "none"
    extra_preview = ", ".join(extra[:5]) if extra else "none"
    return False, f"missing_skus={missing_preview}; extra_skus={extra_preview}"


async def _ensure_unmatched_placeholder_item(zoho: ZohoClient) -> Optional[str]:
    """Ensure the unmatched placeholder item exists in Zoho and return its item_id."""
    global _UNMATCHED_PLACEHOLDER_ITEM_ID_CACHE

    if _UNMATCHED_PLACEHOLDER_ITEM_ID_CACHE:
        return _UNMATCHED_PLACEHOLDER_ITEM_ID_CACHE

    item = await zoho.ensure_item_by_sku(
        sku=UNMATCHED_PLACEHOLDER_ITEM_SKU,
        name=UNMATCHED_PLACEHOLDER_ITEM_NAME,
        rate=0.0,
        description="Auto-created placeholder for unmatched purchase-order lines.",
    )
    item_id = str(item.get("item_id") or "").strip()
    if item_id:
        _UNMATCHED_PLACEHOLDER_ITEM_ID_CACHE = item_id
    return item_id or None


async def _resolve_target_zoho_purchase_order(
    zoho: ZohoClient,
    *,
    po: PurchaseOrder,
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """
    Resolve the Zoho purchase-order target using local zoho_id and PO number.

    Resolution order:
    1) If local zoho_id exists, fetch by zoho_id.
       - If remote purchase number matches local po_number, use this record.
       - If mismatch, lookup by po_number and remap local zoho_id when found.
    2) If no/invalid zoho_id, lookup by po_number.
    3) If not found by po_number, return None so caller creates a new PO.
    """
    local_po_number = str(po.po_number or "").strip()
    resolved_id: Optional[str] = None
    resolved_po: Optional[dict[str, Any]] = None

    if po.zoho_id:
        candidate_id = str(po.zoho_id).strip()
        try:
            by_id = await zoho.get_purchase_order(candidate_id)
        except Exception as exc:
            logger.warning(
                "sync_po_outbound: lookup by zoho_id failed | po_id=%s zoho_id=%s error=%s",
                po.id,
                candidate_id,
                exc,
            )
            by_id = None

        if by_id:
            remote_po_number = str(by_id.get("purchaseorder_number") or "").strip()
            if remote_po_number == local_po_number:
                resolved_id = candidate_id
                resolved_po = by_id
            else:
                logger.warning(
                    "sync_po_outbound: zoho_id points to different PO number | po_id=%s local_po_number=%s remote_po_number=%s zoho_id=%s",
                    po.id,
                    local_po_number,
                    remote_po_number,
                    candidate_id,
                )
                po.zoho_id = None
        else:
            po.zoho_id = None

    if not resolved_id:
        try:
            by_number = await zoho.find_purchase_order_by_number(local_po_number)
        except Exception as exc:
            logger.warning(
                "sync_po_outbound: lookup by purchase number failed | po_id=%s po_number=%s error=%s",
                po.id,
                local_po_number,
                exc,
            )
            by_number = None

        if by_number:
            resolved_id = str(by_number.get("purchaseorder_id") or "").strip() or None
            resolved_po = by_number
            if resolved_id:
                po.zoho_id = resolved_id

    if resolved_id and (not resolved_po or "notes" not in resolved_po):
        try:
            full_po = await zoho.get_purchase_order(resolved_id)
            if full_po:
                resolved_po = full_po
        except Exception as exc:
            logger.warning(
                "sync_po_outbound: failed to hydrate resolved purchase order | po_id=%s zoho_id=%s error=%s",
                po.id,
                resolved_id,
                exc,
            )

    return resolved_id, resolved_po


def _is_billed_po_update_error(exc: Exception) -> bool:
    message = str(exc)
    return "36023" in message or "marked as billed" in message.lower()


def _is_bill_has_recorded_payments_delete_error(exc: Exception) -> bool:
    message = str(exc)
    return "1040" in message or "recorded payments cannot be deleted" in message.lower()


def _is_invalid_branch_id_error(exc: Exception) -> bool:
    message = str(exc)
    message_lc = message.lower()
    return "invalid value passed for branch_id" in message_lc or '"code":400002' in message_lc


def _strip_po_location_fields(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {k: v for k, v in payload.items() if k not in {"location_id", "branch_id"}}
    line_items = payload.get("line_items")
    if isinstance(line_items, list):
        sanitized_lines: list[dict[str, Any]] = []
        for line in line_items:
            if isinstance(line, dict):
                sanitized_lines.append({k: v for k, v in line.items() if k not in {"location_id", "branch_id"}})
            else:
                sanitized_lines.append(line)
        sanitized["line_items"] = sanitized_lines
    return sanitized


def _is_ebay_purchase_source(source: Optional[str]) -> bool:
    return str(source or "").strip().upper().startswith(EBAY_PO_SOURCE_PREFIX)


def _to_decimal(value: object, default: str = "0") -> Decimal:
    try:
        text = str(value if value is not None else default).replace("$", "").replace(",", "").strip()
        if not text:
            text = default
        return Decimal(text)
    except Exception:
        return Decimal(default)


def _to_float_money(value: object) -> float:
    return float(_to_decimal(value, default="0"))


def _is_remote_purchase_order_billed(remote_po: Optional[dict[str, Any]]) -> bool:
    if not remote_po:
        return False

    status = str(remote_po.get("status") or "").strip().lower()
    if status == "billed":
        return True

    bills = remote_po.get("bills") or []
    return isinstance(bills, list) and len(bills) > 0


def _build_ebay_bill_payload(po: PurchaseOrder) -> dict[str, Any]:
    if not po.vendor or not po.vendor.zoho_id:
        raise ValueError("vendor is missing zoho_id")

    line_items: list[dict[str, Any]] = []
    if not po.zoho_id:
        for item in po.items or []:
            qty = int(getattr(item, "quantity", 0) or 0)
            if qty <= 0:
                continue

            line: dict[str, Any] = {
                "name": str(getattr(item, "external_item_name", "") or "Imported Item")[:255],
                "quantity": qty,
                "rate": _to_float_money(getattr(item, "unit_price", 0)),
            }
            variant = getattr(item, "variant", None)
            if variant and getattr(variant, "zoho_item_id", None):
                line["item_id"] = str(variant.zoho_item_id)
            else:
                line["description"] = "Auto-sync line without mapped Zoho item ID"

            line_items.append(line)

        if not line_items:
            raise ValueError("no billable line items")

    bill_date = po.order_date.isoformat()
    payload: dict[str, Any] = {
        "vendor_id": str(po.vendor.zoho_id),
        "bill_number": po.po_number,
        "reference_number": po.po_number,
        "date": bill_date,
        "due_date": bill_date,
        "payment_terms": PAYMENT_TERMS_DUE_ON_RECEIPT,
        "currency_code": str(po.currency or "USD"),
    }

    if po.zoho_id:
        payload["purchaseorder_id"] = str(po.zoho_id)
    else:
        payload["line_items"] = line_items

    charge_total = (
        _to_decimal(getattr(po, "tax_amount", 0), "0")
        + _to_decimal(getattr(po, "shipping_amount", 0), "0")
        + _to_decimal(getattr(po, "handling_amount", 0), "0")
    )
    if charge_total != Decimal("0"):
        payload["adjustment"] = float(charge_total)
        payload["adjustment_description"] = "Shipping Fee + Tax + Handling Fee"

    if po.notes:
        payload["notes"] = str(po.notes)

    return payload


def _enrich_bill_payload_with_remote_po_lines(
    *,
    remote_po: dict[str, Any],
    bill_payload: dict[str, Any],
) -> dict[str, Any]:
    purchaseorder_id = str(bill_payload.get("purchaseorder_id") or "").strip()
    if not purchaseorder_id:
        return bill_payload

    po_lines = remote_po.get("line_items") or []
    if not isinstance(po_lines, list) or not po_lines:
        raise ValueError(f"Zoho PO {purchaseorder_id} has no line_items")

    default_account_id = ""
    for line in po_lines:
        if not isinstance(line, dict):
            continue
        candidate = str(line.get("account_id") or "").strip()
        if candidate:
            default_account_id = candidate
            break

    linked_lines: list[dict[str, Any]] = []
    for line in po_lines:
        if not isinstance(line, dict):
            continue

        purchaseorder_item_id = str(line.get("purchaseorder_item_id") or line.get("line_item_id") or "").strip()
        quantity = int(_to_decimal(line.get("quantity"), default="0"))
        if not purchaseorder_item_id or quantity <= 0:
            continue

        line_payload: dict[str, Any] = {
            "purchaseorder_item_id": purchaseorder_item_id,
            "quantity": quantity,
        }

        for key in [
            "item_id",
            "name",
            "description",
            "rate",
            "tax_id",
            "tds_tax_id",
            "location_id",
            "account_id",
        ]:
            value = line.get(key)
            if value is not None and str(value).strip() != "":
                line_payload[key] = value

        if not str(line_payload.get("account_id") or "").strip() and default_account_id:
            line_payload["account_id"] = default_account_id

        linked_lines.append(line_payload)

    if not linked_lines:
        raise ValueError(f"Zoho PO {purchaseorder_id} produced no valid bill line_items")

    enriched = dict(bill_payload)
    enriched["line_items"] = linked_lines

    po_branch_id = str(remote_po.get("branch_id") or "").strip()
    po_location_id = str(remote_po.get("location_id") or "").strip()
    if po_branch_id:
        enriched["branch_id"] = po_branch_id
    if po_location_id:
        enriched["location_id"] = po_location_id

    return enriched


async def _create_bill_with_inventory_fallback(
    zoho: ZohoClient,
    bill_payload: dict[str, Any],
) -> dict[str, Any]:
    result = await zoho._request(
        "POST",
        "/bills",
        api="inventory",
        data={"JSONString": json.dumps(bill_payload)},
    )
    return result.get("bill", {}) or {}


async def _list_bill_payments_with_inventory_fallback(
    zoho: ZohoClient,
    bill_id: str,
) -> list[dict[str, Any]]:
    result = await zoho._request(
        "GET",
        "/vendorpayments",
        api="inventory",
        params={
            "bill_id": bill_id,
            "page": 1,
            "per_page": 200,
        },
    )
    return result.get("vendorpayments", []) or result.get("vendor_payments", []) or []


def _resolve_bill_amount(po: PurchaseOrder, bill: dict[str, Any]) -> float:
    bill_total = _to_float_money(bill.get("total"))
    if bill_total > 0:
        return bill_total

    po_total = _to_float_money(po.total_amount)
    if po_total > 0:
        return po_total

    line_total = sum(
        _to_float_money(getattr(item, "unit_price", 0)) * int(getattr(item, "quantity", 0) or 0)
        for item in (po.items or [])
    )
    if line_total > 0:
        return line_total

    return 0.0


def _build_ebay_payment_payload(po: PurchaseOrder, bill_id: str, amount: float) -> dict[str, Any]:
    if not po.vendor or not po.vendor.zoho_id:
        raise ValueError("vendor is missing zoho_id")
    if amount <= 0:
        raise ValueError("payment amount must be > 0")

    payment_date = po.order_date.isoformat()
    return {
        "vendor_id": str(po.vendor.zoho_id),
        "date": payment_date,
        "payment_mode": "Credit Card",
        "paid_through_account_id": str(settings.zoho_po_ebay_paid_through_account_id),
        "amount": amount,
        "reference_number": po.po_number,
        "description": "Auto-created from eBay purchase-order sync",
        "bills": [
            {
                "bill_id": bill_id,
                "amount_applied": amount,
            }
        ],
    }


async def _sync_ebay_bill_and_payment_for_purchase_order(
    *,
    po: PurchaseOrder,
    zoho: ZohoClient,
    remote_po_hint: Optional[dict[str, Any]] = None,
) -> None:
    if not _is_ebay_purchase_source(getattr(po, "source", None)):
        return

    if po.zoho_bill_created and po.zoho_payment_created:
        return

    if not po.zoho_id:
        raise ValueError("Cannot sync EBAY bill/payment without purchase_order.zoho_id")

    po.zoho_billing_error = None

    bill_id = str(po.zoho_bill_id or "").strip()
    remote_po = remote_po_hint

    if not po.zoho_bill_created:
        if not remote_po:
            remote_po = await zoho.get_purchase_order(str(po.zoho_id))

        po.zoho_billed_checked_at = datetime.now()
        if _is_remote_purchase_order_billed(remote_po):
            po.zoho_bill_created = True
            remote_bills = (remote_po or {}).get("bills") or []
            if isinstance(remote_bills, list):
                for bill_ref in remote_bills:
                    candidate_bill_id = str((bill_ref or {}).get("bill_id") or "").strip()
                    if candidate_bill_id:
                        po.zoho_bill_id = candidate_bill_id
                        break
            return

    if not po.zoho_bill_created:
        bill_payload = _build_ebay_bill_payload(po)
        if po.zoho_id:
            if not remote_po:
                remote_po = await zoho.get_purchase_order(str(po.zoho_id))
            bill_payload = _enrich_bill_payload_with_remote_po_lines(
                remote_po=remote_po,
                bill_payload=bill_payload,
            )

        created_bill = await _create_bill_with_inventory_fallback(zoho, bill_payload)
        bill_id = str(created_bill.get("bill_id") or "").strip()
        if not bill_id:
            raise ValueError("Zoho bill creation succeeded but no bill_id was returned")

        po.zoho_bill_created = True
        po.zoho_bill_id = bill_id
    elif bill_id:
        po.zoho_bill_created = True

    bill_id = str(po.zoho_bill_id or "").strip()
    if not bill_id:
        return

    if po.zoho_payment_created:
        return

    existing_payments = await _list_bill_payments_with_inventory_fallback(zoho, bill_id)
    if existing_payments:
        po.zoho_payment_created = True
        first_payment = existing_payments[0] if isinstance(existing_payments[0], dict) else {}
        payment_id = str(
            first_payment.get("payment_id")
            or first_payment.get("vendorpayment_id")
            or first_payment.get("vendor_payment_id")
            or ""
        ).strip()
        if payment_id:
            po.zoho_payment_id = payment_id
        return

    bill_payload_for_total = await zoho.get_bill(bill_id)
    amount = _resolve_bill_amount(po, bill_payload_for_total or {})
    if amount <= 0:
        raise ValueError("payment amount must be > 0")

    payment_payload = _build_ebay_payment_payload(po, bill_id, amount)
    created_payment = await zoho.create_vendor_payment(payment_payload)

    po.zoho_payment_created = True
    payment_id = str(
        (created_payment or {}).get("payment_id")
        or (created_payment or {}).get("vendorpayment_id")
        or (created_payment or {}).get("vendor_payment_id")
        or ""
    ).strip()
    if payment_id:
        po.zoho_payment_id = payment_id


def _build_bill_recreate_payload(bill: dict[str, Any], *, purchaseorder_id: str) -> dict[str, Any]:
    """Build a safe bill-create payload from an existing Zoho bill payload."""
    payload: dict[str, Any] = {
        "purchaseorder_id": purchaseorder_id,
        "vendor_id": bill.get("vendor_id"),
        "bill_number": bill.get("bill_number"),
        "date": bill.get("date"),
        "due_date": bill.get("due_date"),
    }

    optional_keys = [
        "reference_number",
        "currency_id",
        "exchange_rate",
        "is_item_level_tax_calc",
        "is_inclusive_tax",
        "notes",
        "terms",
        "location_id",
        "custom_fields",
    ]
    for key in optional_keys:
        value = bill.get(key)
        if value is not None:
            payload[key] = value

    line_items_payload: list[dict[str, Any]] = []
    for line in bill.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        line_payload: dict[str, Any] = {}
        for key in [
            "line_item_id",
            "purchaseorder_item_id",
            "receive_item_id",
            "item_id",
            "name",
            "description",
            "account_id",
            "rate",
            "quantity",
            "tax_id",
            "tds_tax_id",
            "location_id",
        ]:
            value = line.get(key)
            if value is not None and value != "":
                line_payload[key] = value

        if "quantity" not in line_payload:
            line_payload["quantity"] = line.get("quantity") or 1
        if "rate" not in line_payload and line.get("item_total") is not None:
            try:
                qty = float(line_payload.get("quantity") or 1)
                if qty > 0:
                    line_payload["rate"] = float(line.get("item_total")) / qty
            except Exception:
                pass

        if line_payload:
            line_items_payload.append(line_payload)

    payload["line_items"] = line_items_payload
    return payload


async def _update_billed_purchase_order_with_unbill_rebill(
    zoho: ZohoClient,
    *,
    purchase_order_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Update a billed PO by deleting linked bills, updating PO, and recreating bills.

    This is intentionally scoped for explicit operator-triggered sync flows.
    """
    zoho_po = await zoho.get_purchase_order(purchase_order_id)
    bills = [b for b in (zoho_po.get("bills") or []) if isinstance(b, dict)]
    if not bills:
        # No linked bills; let normal update path surface any other failure reason.
        return await zoho.update_purchase_order(purchase_order_id, payload)

    bill_snapshots: list[dict[str, Any]] = []
    deleted_bill_ids: list[str] = []

    for bill_ref in bills:
        bill_id = str(bill_ref.get("bill_id") or "").strip()
        if not bill_id:
            continue
        full_bill = await zoho.get_bill(bill_id)
        if full_bill:
            for payment in full_bill.get("payments") or []:
                if isinstance(payment, dict):
                    await zoho.delete_bill_payment_reference(payment)

        try:
            await zoho.delete_bill(bill_id)
        except Exception as exc:
            if _is_bill_has_recorded_payments_delete_error(exc):
                # Retry once after pulling latest payment refs from Zoho.
                retry_bill = await zoho.get_bill(bill_id)
                for payment in retry_bill.get("payments") or []:
                    if isinstance(payment, dict):
                        await zoho.delete_bill_payment_reference(payment)
                await zoho.delete_bill(bill_id)
            else:
                raise

        if full_bill:
            bill_snapshots.append(full_bill)
        deleted_bill_ids.append(bill_id)

    # Some POs are non-billed but still locked due to receive records.
    receive_ids: list[str] = []
    page = 1
    while page <= 50:
        receives = await zoho.list_purchase_receives(
            purchaseorder_id=purchase_order_id,
            page=page,
            per_page=200,
        )
        if not receives:
            break

        for receive in receives:
            receive_id = str(
                (receive or {}).get("receive_id")
                or (receive or {}).get("purchasereceive_id")
                or ""
            ).strip()
            if receive_id:
                receive_ids.append(receive_id)

        if len(receives) < 200:
            break
        page += 1

    for receive_id in receive_ids:
        await zoho.delete_purchase_receive(receive_id)

    try:
        updated_po = await zoho.update_purchase_order(purchase_order_id, payload)
    except Exception:
        # Best-effort recovery: recreate deleted bills if PO update fails.
        for snapshot in bill_snapshots:
            recreate_payload = _build_bill_recreate_payload(snapshot, purchaseorder_id=purchase_order_id)
            try:
                await zoho.create_bill(recreate_payload)
            except Exception:
                logger.exception(
                    "sync_po_outbound: failed to restore bill after PO update failure | po_id=%s",
                    purchase_order_id,
                )
        raise

    for snapshot in bill_snapshots:
        recreate_payload = _build_bill_recreate_payload(snapshot, purchaseorder_id=purchase_order_id)
        await zoho.create_bill(recreate_payload)

    logger.warning(
        "sync_po_outbound: billed/received PO required unbill-receive-rebill flow | po_id=%s bills_processed=%s receives_deleted=%s",
        purchase_order_id,
        len(deleted_bill_ids),
        len(receive_ids),
    )
    return updated_po


# =========================================================================
# INBOUND MAPPERS  (Zoho → USAV)
# =========================================================================

def zoho_contact_to_customer_fields(data: dict) -> dict[str, Any]:
    """Extract Customer-relevant fields from a Zoho contact payload."""
    fields: dict[str, Any] = {}
    if "contact_name" in data:
        fields["name"] = data["contact_name"]
    if "email" in data:
        fields["email"] = data["email"]
    if "phone" in data:
        fields["phone"] = data["phone"]
    if "company_name" in data:
        fields["company_name"] = data["company_name"]
    addr = data.get("billing_address") or {}
    if addr.get("address"):
        fields["address_line1"] = addr["address"]
    if addr.get("street2"):
        fields["address_line2"] = addr["street2"]
    if addr.get("city"):
        fields["city"] = addr["city"]
    if addr.get("state"):
        fields["state"] = addr["state"]
    if addr.get("zip"):
        fields["postal_code"] = addr["zip"]
    if addr.get("country"):
        fields["country"] = addr["country"]
    return fields


# =========================================================================
# OUTBOUND SYNC WORKERS
# =========================================================================

async def sync_variant_outbound(variant_id: int) -> None:
    """
    Push a single ``ProductVariant`` to Zoho Inventory (create or update).

    Uses a fresh DB session so it is safe to call from a background task.
    """
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.models.entities import ProductIdentity

    async with async_session_factory() as db:
        stmt = (
            select(ProductVariant)
            .options(
                selectinload(ProductVariant.identity).selectinload(ProductIdentity.family),
                selectinload(ProductVariant.listings),
            )
            .where(ProductVariant.id == variant_id)
        )
        variant = (await db.execute(stmt)).scalar_one_or_none()
        if variant is None:
            logger.warning("sync_variant_outbound: variant %s not found", variant_id)
            return

        payload = variant_to_zoho_payload(variant)
        new_hash = generate_payload_hash(payload)

        if new_hash == variant.zoho_last_sync_hash:
            logger.debug("sync_variant_outbound: variant %s unchanged (hash match)", variant_id)
            return

        try:
            zoho = ZohoClient()

            identity = getattr(variant, "identity", None)
            if identity and identity.is_stationery:
                payload["purchase_account_id"] = 5623409000000000400

            zoho_item = await zoho.sync_item(
                sku=payload.get("sku", variant.full_sku),
                name=payload.get("name", variant.full_sku),
                rate=float(payload.get("rate", 0) or 0),
                description=payload.get("description", ""),
                **{k: v for k, v in payload.items() if k not in {"name", "sku", "rate", "description"}},
            )

            zoho_item_id = str(zoho_item.get("item_id", ""))
            if zoho_item_id:
                variant.zoho_item_id = zoho_item_id

            variant.zoho_last_sync_hash = new_hash
            variant.zoho_last_synced_at = datetime.now()
            variant.zoho_sync_error = None
            await db.commit()

            logger.info(
                "sync_variant_outbound: variant %s synced to Zoho (item_id=%s)",
                variant_id,
                zoho_item_id,
            )
        except RateLimitError as exc:
            variant.zoho_sync_error = str(exc)
            await db.commit()
            logger.warning("sync_variant_outbound: variant %s rate-limited (retry_after=%s)", variant_id, getattr(exc, "retry_after", None))
            raise
        except Exception as exc:
            variant.zoho_sync_error = str(exc)[:2000]
            await db.commit()
            logger.exception("sync_variant_outbound: variant %s failed", variant_id)


async def sync_customer_outbound(customer_id: int) -> None:
    """
    Push a single ``Customer`` to Zoho Inventory *Contacts* (create or update).
    """
    from sqlalchemy import select

    async with async_session_factory() as db:
        customer = (await db.execute(
            select(Customer).where(Customer.id == customer_id)
        )).scalar_one_or_none()

        if customer is None:
            logger.warning("sync_customer_outbound: customer %s not found", customer_id)
            return

        payload = customer_to_zoho_payload(customer)
        new_hash = generate_payload_hash(payload)

        if new_hash == customer.zoho_last_sync_hash:
            logger.debug("sync_customer_outbound: customer %s unchanged (hash match)", customer_id)
            return

        try:
            zoho = ZohoClient()

            # If no zoho_id but email exists, try to find existing contact by email first
            if not customer.zoho_id and customer.email:
                existing = await zoho.get_contact_by_email(customer.email)
                if existing:
                    customer.zoho_id = str(existing.get("contact_id", ""))

            if customer.zoho_id:
                contact = await zoho.update_contact(customer.zoho_id, payload)
            else:
                contact = await zoho.create_contact(payload)

            contact_id = str(contact.get("contact_id", ""))
            if contact_id:
                customer.zoho_id = contact_id

            # Soft-delete mapping
            if customer.is_active:
                if customer.zoho_id:
                    await zoho.mark_contact_active(customer.zoho_id)
            else:
                if customer.zoho_id:
                    await zoho.mark_contact_inactive(customer.zoho_id)

            customer.zoho_last_sync_hash = new_hash
            customer.zoho_last_synced_at = datetime.now()
            customer.zoho_sync_error = None
            customer._updated_by_sync = True
            await db.commit()

            logger.info(
                "sync_customer_outbound: customer %s synced to Zoho (contact_id=%s)",
                customer_id,
                customer.zoho_id,
            )
        except Exception as exc:
            message = str(exc)
            # Handle duplicate name error by looking up existing contact
            if "3062" in message or "already exists" in message:
                zoho = ZohoClient()
                resolved_id: Optional[str] = None

                if customer.email:
                    existing = await zoho.get_contact_by_email(customer.email)
                    if existing:
                        resolved_id = str(existing.get("contact_id", ""))

                if not resolved_id and customer.name:
                    # Fallback: scan first page of contacts for matching name
                    contacts = await zoho.list_contacts(page=1, per_page=200)
                    for c in contacts:
                        if c.get("contact_name") == customer.name:
                            resolved_id = str(c.get("contact_id", ""))
                            break

                if resolved_id:
                    customer.zoho_id = resolved_id
                    customer.zoho_last_sync_hash = new_hash
                    customer.zoho_last_synced_at = datetime.now()
                    customer.zoho_sync_error = None
                    customer._updated_by_sync = True
                    await db.commit()
                    logger.debug(
                        "[DEBUG.EXTERNAL_API] sync_customer_outbound: customer %s linked to existing Zoho contact %s",
                        customer_id,
                        resolved_id,
                    )
                    return

            customer.zoho_sync_error = message[:2000]
            customer._updated_by_sync = True
            await db.commit()
            logger.exception("sync_customer_outbound: customer %s failed", customer_id)


async def sync_vendor_outbound(vendor_id: int) -> None:
    """Push a single ``Vendor`` to Zoho as a vendor contact."""
    from sqlalchemy import select

    async with async_session_factory() as db:
        vendor = (await db.execute(select(Vendor).where(Vendor.id == vendor_id))).scalar_one_or_none()
        if vendor is None:
            logger.warning("sync_vendor_outbound: vendor %s not found", vendor_id)
            return

        payload = vendor_to_zoho_payload(vendor)
        new_hash = generate_payload_hash(payload)

        if new_hash == vendor.zoho_last_sync_hash:
            logger.debug("sync_vendor_outbound: vendor %s unchanged (hash match)", vendor_id)
            return

        try:
            zoho = ZohoClient()

            if not vendor.zoho_id and vendor.email:
                existing = await zoho.get_contact_by_email(vendor.email)
                if existing and str(existing.get("contact_type", "")).lower() == "vendor":
                    vendor.zoho_id = str(existing.get("contact_id", ""))

            if vendor.zoho_id:
                contact = await zoho.update_contact(vendor.zoho_id, payload)
            else:
                contact = await zoho.create_contact(payload, contact_type="vendor")

            contact_id = str(contact.get("contact_id", ""))
            if contact_id:
                vendor.zoho_id = contact_id

            if vendor.zoho_id:
                if vendor.is_active:
                    await zoho.mark_contact_active(vendor.zoho_id)
                else:
                    await zoho.mark_contact_inactive(vendor.zoho_id)

            vendor.zoho_last_sync_hash = new_hash
            vendor.zoho_last_synced_at = datetime.now()
            vendor.zoho_sync_error = None
            vendor._updated_by_sync = True
            await db.commit()

            logger.info(
                "sync_vendor_outbound: vendor %s synced to Zoho (contact_id=%s)",
                vendor_id,
                vendor.zoho_id,
            )
        except Exception as exc:
            vendor.zoho_sync_error = str(exc)[:2000]
            vendor._updated_by_sync = True
            await db.commit()
            logger.exception("sync_vendor_outbound: vendor %s failed", vendor_id)


async def sync_po_outbound(
    po_id: int,
    allow_billed_unbill_rebill: bool = False,
    enable_ebay_billing: bool = False,
) -> None:
    """Push a ``PurchaseOrder`` to Zoho Inventory as a purchase order."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload, undefer

    payload: Optional[dict[str, Any]] = None

    async with async_session_factory() as db:
        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.vendor),
                selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.variant),
                undefer(PurchaseOrder.zoho_bill_created),
                undefer(PurchaseOrder.zoho_payment_created),
                undefer(PurchaseOrder.zoho_billed_checked_at),
                undefer(PurchaseOrder.zoho_bill_id),
                undefer(PurchaseOrder.zoho_payment_id),
                undefer(PurchaseOrder.zoho_billing_error),
            )
            .where(PurchaseOrder.id == po_id)
        )
        po = (await db.execute(stmt)).scalar_one_or_none()
        if po is None:
            logger.warning("sync_po_outbound: purchase_order %s not found", po_id)
            return

        po.zoho_sync_status = ZohoSyncStatus.PENDING
        po._updated_by_sync = True
        await db.commit()
        po._updated_by_sync = False

        vendor = po.vendor
        if vendor is None:
            po.zoho_sync_error = "Cannot sync purchase order: no linked vendor"
            po.zoho_sync_status = ZohoSyncStatus.ERROR
            po._updated_by_sync = True
            await db.commit()
            return

        if not vendor.zoho_id:
            await sync_vendor_outbound(vendor.id)
            await db.refresh(vendor)
            if not vendor.zoho_id:
                po.zoho_sync_error = f"Vendor {vendor.id} missing zoho_id; sync vendor first."
                po.zoho_sync_status = ZohoSyncStatus.ERROR
                po._updated_by_sync = True
                await db.commit()
                return

        try:
            zoho = ZohoClient()

            unmatched_item_id: Optional[str] = None
            if any(getattr(item, "variant", None) is None for item in (po.items or [])):
                unmatched_item_id = await _ensure_unmatched_placeholder_item(zoho)
                if not unmatched_item_id:
                    raise ValueError(
                        "Unable to resolve Zoho placeholder item for unmatched purchase-order lines"
                    )

            resolved_zoho_po_id, resolved_zoho_po = await _resolve_target_zoho_purchase_order(
                zoho,
                po=po,
            )

            remote_notes = None
            if resolved_zoho_po:
                remote_notes = str(resolved_zoho_po.get("notes") or "").strip() or None

            payload = purchase_order_to_zoho_payload(
                po,
                unmatched_item_id=unmatched_item_id,
                existing_notes=remote_notes,
            )
            metadata_payload = purchase_order_metadata_to_zoho_payload(
                po,
                existing_notes=remote_notes,
            )
            new_hash = generate_payload_hash(payload)

            if new_hash == po.zoho_last_sync_hash:
                logger.debug("sync_po_outbound: purchase_order %s unchanged (hash match)", po_id)
                if enable_ebay_billing:
                    try:
                        await _sync_ebay_bill_and_payment_for_purchase_order(
                            po=po,
                            zoho=zoho,
                            remote_po_hint=resolved_zoho_po if resolved_zoho_po_id else None,
                        )
                    except Exception as billing_exc:
                        po.zoho_billing_error = str(billing_exc)[:2000]
                        logger.exception(
                            "sync_po_outbound: ebay bill/payment sync failed on hash-match path | po_id=%s zoho_po_id=%s",
                            po_id,
                            po.zoho_id,
                        )
                po.zoho_sync_error = None
                po.zoho_sync_status = ZohoSyncStatus.SYNCED
                po._updated_by_sync = True
                await db.commit()
                return

            if resolved_zoho_po_id:
                metadata_updated = False
                if metadata_payload:
                    try:
                        await zoho.update_purchase_order(resolved_zoho_po_id, metadata_payload)
                        metadata_updated = True
                    except Exception as metadata_exc:
                        if _is_invalid_branch_id_error(metadata_exc):
                            try:
                                fallback_metadata_payload = _strip_po_location_fields(metadata_payload)
                                await zoho.update_purchase_order(
                                    resolved_zoho_po_id,
                                    fallback_metadata_payload,
                                )
                                metadata_payload = fallback_metadata_payload
                                metadata_updated = True
                                logger.warning(
                                    "sync_po_outbound: metadata update retried without location fields after branch_id validation error | po_id=%s zoho_id=%s",
                                    po_id,
                                    resolved_zoho_po_id,
                                )
                            except Exception:
                                logger.warning(
                                    "sync_po_outbound: metadata update fallback without location fields failed | po_id=%s zoho_id=%s",
                                    po_id,
                                    resolved_zoho_po_id,
                                )
                        if metadata_updated:
                            pass
                        else:
                            logger.warning(
                                "sync_po_outbound: metadata update failed; continuing with full update | po_id=%s zoho_id=%s error=%s",
                                po_id,
                                resolved_zoho_po_id,
                                metadata_exc,
                            )

                try:
                    zoho_po = await zoho.update_purchase_order(resolved_zoho_po_id, payload)
                except Exception as update_exc:
                    handled_locked_lines = False
                    if _is_invalid_branch_id_error(update_exc):
                        fallback_payload = _strip_po_location_fields(payload)
                        zoho_po = await zoho.update_purchase_order(resolved_zoho_po_id, fallback_payload)
                        payload = fallback_payload
                        new_hash = generate_payload_hash(payload)
                        handled_locked_lines = True
                        logger.warning(
                            "sync_po_outbound: purchase-order update retried without location fields after branch_id validation error | po_id=%s zoho_id=%s",
                            po_id,
                            resolved_zoho_po_id,
                        )
                    if _is_billed_po_update_error(update_exc) and metadata_updated:
                        refreshed_zoho_po = await zoho.get_purchase_order(resolved_zoho_po_id)
                        has_parity, parity_detail = await _verify_purchase_order_sku_parity(
                            po=po,
                            zoho=zoho,
                            remote_po=refreshed_zoho_po,
                        )
                        if has_parity:
                            logger.warning(
                                "sync_po_outbound: line-item update locked; metadata synced and SKU parity matched | po_id=%s zoho_id=%s",
                                po_id,
                                resolved_zoho_po_id,
                            )
                            zoho_po = refreshed_zoho_po
                            handled_locked_lines = True
                        else:
                            raise ValueError(
                                "Metadata synced but Zoho line items differ from local SKU set: "
                                f"{parity_detail}"
                            )
                    if handled_locked_lines:
                        pass
                    elif allow_billed_unbill_rebill and _is_billed_po_update_error(update_exc):
                        zoho_po = await _update_billed_purchase_order_with_unbill_rebill(
                            zoho,
                            purchase_order_id=resolved_zoho_po_id,
                            payload=payload,
                        )
                    else:
                        raise
            else:
                try:
                    zoho_po = await zoho.create_purchase_order(payload)
                except Exception as create_exc:
                    if _is_invalid_branch_id_error(create_exc):
                        fallback_payload = _strip_po_location_fields(payload)
                        zoho_po = await zoho.create_purchase_order(fallback_payload)
                        payload = fallback_payload
                        new_hash = generate_payload_hash(payload)
                        logger.warning(
                            "sync_po_outbound: purchase-order create retried without location fields after branch_id validation error | po_id=%s",
                            po_id,
                        )
                    else:
                        raise

            zoho_po_id = str(zoho_po.get("purchaseorder_id", ""))
            if zoho_po_id:
                po.zoho_id = zoho_po_id

            if enable_ebay_billing:
                try:
                    await _sync_ebay_bill_and_payment_for_purchase_order(
                        po=po,
                        zoho=zoho,
                        remote_po_hint=zoho_po if resolved_zoho_po_id else None,
                    )
                except Exception as billing_exc:
                    po.zoho_billing_error = str(billing_exc)[:2000]
                    logger.exception(
                        "sync_po_outbound: ebay bill/payment sync failed | po_id=%s zoho_po_id=%s",
                        po_id,
                        po.zoho_id,
                    )

            po.zoho_last_sync_hash = new_hash
            po.zoho_last_synced_at = datetime.now()
            po.zoho_sync_error = None
            po.zoho_sync_status = ZohoSyncStatus.SYNCED
            po._updated_by_sync = True
            await db.commit()

            logger.info(
                "sync_po_outbound: purchase_order %s synced to Zoho (purchaseorder_id=%s)",
                po_id,
                po.zoho_id,
            )
        except Exception as exc:
            if payload is not None and "27520" in str(exc):
                logger.error(
                    "sync_po_outbound: Zoho 27520 debug payload | po_id=%s payload=%s",
                    po_id,
                    payload,
                )
            po.zoho_sync_error = str(exc)[:2000]
            po.zoho_sync_status = ZohoSyncStatus.ERROR
            po._updated_by_sync = True
            await db.commit()
            logger.exception("sync_po_outbound: purchase_order %s failed", po_id)


async def sync_po_outbound_with_unbill_rebill(po_id: int) -> None:
    """Operator-triggered PO sync that allows unbill/rebill for billed Zoho purchase orders."""
    await sync_po_outbound(po_id, allow_billed_unbill_rebill=True)


# =========================================================================
# INBOUND SYNC WORKERS  (called by webhook dispatcher)
# =========================================================================

async def process_item_inbound(payload: dict) -> None:
    """
    Apply an inbound Zoho item webhook to the local ``ProductVariant``.

    Echo-loop prevention:
    1. Hash the incoming payload — if it matches ``zoho_last_sync_hash``, skip.
    2. Set ``_updated_by_sync = True`` on the entity before commit so that
       the ``after_update`` listener does not re-enqueue an outbound sync.
    """
    from sqlalchemy import select

    item_data = payload.get("item") or payload
    zoho_item_id = str(item_data.get("item_id", ""))
    sku = item_data.get("sku", "")

    if not zoho_item_id and not sku:
        logger.warning("process_item_inbound: payload missing item_id and sku")
        return

    new_hash = generate_payload_hash(item_data)

    async with async_session_factory() as db:
        # Locate by zoho_item_id first, fallback to SKU
        stmt = select(ProductVariant)
        if zoho_item_id:
            stmt = stmt.where(ProductVariant.zoho_item_id == zoho_item_id)
        else:
            stmt = stmt.where(ProductVariant.full_sku == sku)

        variant = (await db.execute(stmt)).scalar_one_or_none()
        if variant is None:
            logger.debug("[DEBUG.INTERNAL_API] process_item_inbound: no local variant for zoho_item_id=%s sku=%s", zoho_item_id, sku)
            return

        if variant.zoho_last_sync_hash == new_hash:
            logger.debug("process_item_inbound: variant %s hash unchanged, skipping", variant.id)
            return

        # Apply fields we care about
        if item_data.get("name"):
            variant.variant_name = item_data["name"]
        if item_data.get("status") == "inactive":
            variant.is_active = False
        elif item_data.get("status") == "active":
            variant.is_active = True

        variant.zoho_item_id = zoho_item_id or variant.zoho_item_id
        variant.zoho_last_sync_hash = new_hash
        variant.zoho_last_synced_at = datetime.now()
        variant.zoho_sync_error = None

        # CRITICAL: prevent echo loop
        variant._updated_by_sync = True
        await db.commit()

        logger.debug("[DEBUG.INTERNAL_API] process_item_inbound: variant %s updated from Zoho", variant.id)


async def process_contact_inbound(payload: dict) -> None:
    """
    Apply an inbound Zoho contact webhook to the local ``Customer``.
    """
    from sqlalchemy import select

    contact_data = payload.get("contact") or payload
    zoho_contact_id = str(contact_data.get("contact_id", ""))

    if not zoho_contact_id:
        logger.warning("process_contact_inbound: missing contact_id in payload")
        return

    new_hash = generate_payload_hash(contact_data)

    async with async_session_factory() as db:
        stmt = select(Customer).where(Customer.zoho_id == zoho_contact_id)
        customer = (await db.execute(stmt)).scalar_one_or_none()

        if customer is None:
            # New contact from Zoho — create locally
            fields = zoho_contact_to_customer_fields(contact_data)
            customer = Customer(
                zoho_id=zoho_contact_id,
                zoho_last_sync_hash=new_hash,
                zoho_last_synced_at=datetime.now(),
                **fields,
            )
            customer._updated_by_sync = True
            db.add(customer)
            await db.commit()
            logger.debug("[DEBUG.INTERNAL_API] process_contact_inbound: created customer from Zoho contact %s", zoho_contact_id)
            return

        if customer.zoho_last_sync_hash == new_hash:
            logger.debug("process_contact_inbound: customer %s hash unchanged", customer.id)
            return

        fields = zoho_contact_to_customer_fields(contact_data)
        for key, value in fields.items():
            setattr(customer, key, value)

        customer.zoho_last_sync_hash = new_hash
        customer.zoho_last_synced_at = datetime.now()
        customer.zoho_sync_error = None
        customer._updated_by_sync = True
        await db.commit()

        logger.debug("[DEBUG.INTERNAL_API] process_contact_inbound: customer %s updated from Zoho", customer.id)


# =========================================================================
# ORDER OUTBOUND SYNC  (dependency-aware)
# =========================================================================

_ORDER_SYNC_MAX_RETRIES = 1  # retained for reference; no auto-retry to preserve Zoho API quota
_ORDER_SYNC_RETRY_DELAY_SECS = 0


def order_to_zoho_payload(order: Order) -> dict[str, Any]:
    """Build a Zoho SalesOrder payload from a local ``Order``."""
    # Hard guard: Zoho requires an existing contact; fail fast if missing
    customer: Optional[Customer] = getattr(order, "customer", None)
    if not (customer and customer.zoho_id):
        raise ValueError("Order is missing customer.zoho_id; sync customer first.")

    payload: dict[str, Any] = {
        "reference_number": order.external_order_id,
        "date": (order.ordered_at or order.created_at).strftime("%Y-%m-%d"),
    }

    # Customer
    payload["customer_id"] = customer.zoho_id

    # Line items
    line_items: list[dict[str, Any]] = []
    for item in (order.items or []):
        li: dict[str, Any] = {
            "name": item.item_name,
            "quantity": item.quantity,
            "rate": float(item.unit_price),
        }
        variant = getattr(item, "variant", None)
        if variant and variant.zoho_item_id:
            li["item_id"] = variant.zoho_item_id
        line_items.append(li)
    payload["line_items"] = line_items

    # Shipping address
    addr_fields = {
        "address": order.shipping_address_line1,
        "street2": order.shipping_address_line2,
        "city": order.shipping_city,
        "state": order.shipping_state,
        "zip": order.shipping_postal_code,
        "country": order.shipping_country,
    }
    shipping = {k: v for k, v in addr_fields.items() if v}
    if shipping:
        payload["shipping_address"] = _sanitize_shipping_address(shipping)

    return payload


def _sanitize_shipping_address(addr: dict[str, str]) -> dict[str, str]:
    """Trim shipping address fields to satisfy Zoho < 100 chars rule."""
    max_total = 95  # keep some headroom below 100
    max_field = 64

    def _trim(value: str, limit: int) -> str:
        return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"

    sanitized = {k: _trim(v, max_field) for k, v in addr.items() if v}

    # Helper to measure total length Zoho seems to enforce (concatenated fields)
    def _total_len(parts: dict[str, str]) -> int:
        ordered = [parts[k] for k in ("address", "street2", "city", "state", "zip", "country") if k in parts]
        return len(", ".join(ordered))

    # First, if total length still exceeds the threshold, drop street2 entirely.
    if _total_len(sanitized) > max_total and "street2" in sanitized:
        sanitized.pop("street2")

    # If still too long, trim the main address field down until we fit or empty.
    if _total_len(sanitized) > max_total and "address" in sanitized:
        while _total_len(sanitized) > max_total and sanitized.get("address"):
            sanitized["address"] = sanitized["address"][:-1]
        if sanitized.get("address") == "":
            sanitized.pop("address")

    return {k: v for k, v in sanitized.items() if v}


async def sync_order_outbound(order_id: int) -> None:
    """
    Push a single ``Order`` to Zoho as a SalesOrder.

    **Dependency checks:**
    - If the linked Customer has no ``zoho_id``, trigger customer sync first
      and requeue with a delay.
    - If any line-item's ProductVariant has no ``zoho_item_id``, trigger
      variant sync first and requeue.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with async_session_factory() as db:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.customer),
                selectinload(Order.items).selectinload(OrderItem.variant),
            )
            .where(Order.id == order_id)
        )
        order = (await db.execute(stmt)).scalar_one_or_none()
        if order is None:
            logger.warning("sync_order_outbound: order %s not found", order_id)
            return

        # Mark as actively syncing
        order.zoho_sync_status = ZohoSyncStatus.PENDING
        order._updated_by_sync = True
        await db.commit()
        order._updated_by_sync = False

        # ---- DEPENDENCY: Customer must exist and have zoho_id ----
        customer = order.customer
        if customer is None:
            order.zoho_sync_error = "Cannot sync order: no linked customer record."
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.error("sync_order_outbound: order %s has no customer", order_id)
            return

        if not customer.zoho_id:
            logger.debug(
                "[DEBUG.INTERNAL_API] sync_order_outbound: order %s waiting on customer %s zoho_id",
                order_id, customer.id,
            )
            await sync_customer_outbound(customer.id)
            await db.refresh(customer)

            if not customer.zoho_id:
                order.zoho_sync_error = f"Customer {customer.id} missing zoho_id; sync customer first."
                order.zoho_sync_status = ZohoSyncStatus.ERROR
                order._updated_by_sync = True
                await db.commit()
                return

        # ---- DEPENDENCY: All line-item variants must have zoho_item_id ----
        missing_variants: list[int] = []
        for item in (order.items or []):
            variant = getattr(item, "variant", None)
            if variant and not variant.zoho_item_id:
                missing_variants.append(variant.id)

        if missing_variants:
            logger.debug(
                "[DEBUG.INTERNAL_API] sync_order_outbound: order %s waiting on %d variants",
                order_id, len(missing_variants),
            )
            for vid in missing_variants:
                try:
                    await sync_variant_outbound(vid)
                except RateLimitError as exc:
                    order.zoho_sync_error = f"Zoho rate limit while syncing variants; retry after {getattr(exc, 'retry_after', 60)}s."
                    order.zoho_sync_status = ZohoSyncStatus.ERROR
                    order._updated_by_sync = True
                    await db.commit()
                    return
            # Refresh variants and re-check once
            refreshed_missing: list[int] = []
            for item in (order.items or []):
                variant = getattr(item, "variant", None)
                if variant:
                    await db.refresh(variant)
                    if not variant.zoho_item_id:
                        refreshed_missing.append(variant.id)

            if refreshed_missing:
                order.zoho_sync_error = (
                    f"Variants {refreshed_missing} missing zoho_item_id; sync variants first."
                )
                order.zoho_sync_status = ZohoSyncStatus.ERROR
                order._updated_by_sync = True
                await db.commit()
                return

        # ---- All dependencies met: build payload & push ----
        payload = order_to_zoho_payload(order)
        new_hash = generate_payload_hash(payload)

        if new_hash == order.zoho_last_sync_hash:
            logger.debug("sync_order_outbound: order %s unchanged (hash match)", order_id)
            order.zoho_sync_status = ZohoSyncStatus.SYNCED
            order.zoho_sync_error = None
            order._updated_by_sync = True
            await db.commit()
            order._updated_by_sync = False
            return

        try:
            zoho = ZohoClient()

            # If we don't yet have a zoho_id, try to locate an existing SalesOrder
            # by reference_number to avoid duplicates when re-queuing the same order.
            if not order.zoho_id:
                existing_so_id: Optional[str] = None
                try:
                    for page in range(1, 4):  # scan first ~600 orders to keep quota safe
                        salesorders = await zoho.list_salesorders(page=page, per_page=200)
                        match = next(
                            (
                                so
                                for so in salesorders
                                if str(so.get("reference_number", "")) == order.external_order_id
                            ),
                            None,
                        )
                        if match:
                            existing_so_id = str(match.get("salesorder_id", "")) or None
                            break
                        if len(salesorders) < 200:
                            break  # no more pages
                except Exception as lookup_exc:
                    logger.warning(
                        "sync_order_outbound: lookup existing salesorder failed: %s",
                        lookup_exc,
                    )

                if existing_so_id:
                    order.zoho_id = existing_so_id

            if order.zoho_id:
                so = await zoho.update_salesorder(order.zoho_id, payload)
            else:
                so = await zoho.create_sales_order(payload)

            so_id = str(so.get("salesorder_id", ""))
            if so_id:
                order.zoho_id = so_id

            order.zoho_last_sync_hash = new_hash
            order.zoho_last_synced_at = datetime.now()
            order.zoho_sync_error = None
            order.zoho_sync_status = ZohoSyncStatus.SYNCED
            order._updated_by_sync = True
            await db.commit()
            order._updated_by_sync = False

            logger.info(
                "sync_order_outbound: order %s synced to Zoho (salesorder_id=%s)",
                order_id, so_id,
            )

            # After the sales order is synced, apply shipping-specific actions
            from app.modules.orders.models import ShippingStatus
            if order.shipping_status in (
                ShippingStatus.PACKED,
                ShippingStatus.SHIPPING,
                ShippingStatus.DELIVERED,
            ):
                try:
                    await sync_shipping_status_to_zoho(order_id)
                except Exception as ship_exc:
                    logger.warning(
                        "sync_order_outbound: shipping status sync failed for order %s: %s",
                        order_id, ship_exc,
                    )
        except RateLimitError as exc:
            order.zoho_sync_error = (
                f"Zoho rate limit hit; retry after {getattr(exc, 'retry_after', 60)}s."
            )[:2000]
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.warning("sync_order_outbound: order %s rate-limited", order_id)
            return
        except Exception as exc:
            logger.error(
                "sync_order_outbound: order %s payload failed | payload=%s",
                order_id,
                payload,
            )
            order.zoho_sync_error = str(exc)[:2000]
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.exception("sync_order_outbound: order %s failed", order_id)


# =========================================================================
# SHIPPING STATUS SYNC  (Package / Shipment / Delivered)
# =========================================================================

async def sync_shipping_status_to_zoho(order_id: int) -> None:
    """
    Push the local shipping status to Zoho as package / shipment actions.

    - PACKED or SHIPPING → ensure a package exists (marks SO as "packed").
    - SHIPPING → also create a shipment order if none exists.
    - DELIVERED → ensure a shipment exists and mark it as delivered.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.modules.orders.models import ShippingStatus

    async with async_session_factory() as db:
        stmt = (
            select(Order)
            .options(
                selectinload(Order.customer),
                selectinload(Order.items).selectinload(OrderItem.variant),
            )
            .where(Order.id == order_id)
        )
        order = (await db.execute(stmt)).scalar_one_or_none()
        if order is None:
            logger.warning("sync_shipping_status: order %s not found", order_id)
            return

        if not order.zoho_id:
            logger.debug("[DEBUG.INTERNAL_API] sync_shipping_status: order %s has no zoho_id — sync order first", order_id)
            return

        zoho = ZohoClient()

        try:
            if order.shipping_status in (
                ShippingStatus.PACKED,
                ShippingStatus.SHIPPING,
                ShippingStatus.DELIVERED,
            ):
                # Ensure a package exists (idempotent — skip if already present)
                existing_packages = await zoho.list_packages(order.zoho_id)
                if not existing_packages:
                    # Fetch the full SO to get line_item IDs
                    so = await zoho.get_salesorder(order.zoho_id)
                    so_line_items = so.get("line_items", [])
                    pkg_lines = [
                        {
                            "so_line_item_id": li["line_item_id"],
                            "quantity": li.get("quantity", 1),
                        }
                        for li in so_line_items
                        if li.get("line_item_id")
                    ]
                    if pkg_lines:
                        await zoho.create_package(order.zoho_id, pkg_lines)
                        logger.debug("[DEBUG.EXTERNAL_API] sync_shipping_status: created package for order %s", order_id)
                    else:
                        logger.warning(
                            "sync_shipping_status: order %s SO has no line items for packaging",
                            order_id,
                        )

            if order.shipping_status in (ShippingStatus.SHIPPING, ShippingStatus.DELIVERED):
                # Ensure a shipment order exists
                existing_shipments = await zoho.list_shipment_orders(order.zoho_id)
                if not existing_shipments:
                    packages = await zoho.list_packages(order.zoho_id)
                    pkg_ids = [str(p.get("package_id", "")) for p in packages if p.get("package_id")]
                    if pkg_ids:
                        await zoho.create_shipment_order(
                            order.zoho_id,
                            pkg_ids,
                            tracking_number=order.tracking_number,
                            delivery_method=order.carrier,
                        )
                        logger.debug("[DEBUG.EXTERNAL_API] sync_shipping_status: created shipment for order %s", order_id)

            if order.shipping_status == ShippingStatus.DELIVERED:
                shipments = await zoho.list_shipment_orders(order.zoho_id)
                for shipment in shipments:
                    so_status = str(shipment.get("status", "")).lower()
                    if so_status != "delivered":
                        shipment_id = str(shipment.get("shipment_id", ""))
                        if shipment_id:
                            await zoho.mark_shipment_delivered(shipment_id)
                            logger.debug(
                                "[DEBUG.EXTERNAL_API] sync_shipping_status: marked shipment %s delivered for order %s",
                                shipment_id, order_id,
                            )

            # Mark order as synced
            order.zoho_sync_status = ZohoSyncStatus.SYNCED
            order.zoho_sync_error = None
            order.zoho_last_synced_at = datetime.now()
            order._updated_by_sync = True
            await db.commit()
            order._updated_by_sync = False

        except RateLimitError as exc:
            order.zoho_sync_error = (
                f"Zoho rate limit during shipping sync; retry after {getattr(exc, 'retry_after', 60)}s."
            )[:2000]
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.warning("sync_shipping_status: order %s rate-limited", order_id)
        except Exception as exc:
            order.zoho_sync_error = str(exc)[:2000]
            order.zoho_sync_status = ZohoSyncStatus.ERROR
            order._updated_by_sync = True
            await db.commit()
            logger.exception("sync_shipping_status: order %s failed", order_id)


# =========================================================================
# ORDER INBOUND SYNC
# =========================================================================

async def process_order_inbound(payload: dict) -> None:
    """
    Apply an inbound Zoho SalesOrder webhook to the local ``Order``.

    Only updates *status* and selected metadata fields — we do NOT
    overwrite line-items from the Zoho side.
    """
    from sqlalchemy import select

    so_data = payload.get("salesorder") or payload
    zoho_so_id = str(so_data.get("salesorder_id", ""))

    if not zoho_so_id:
        logger.warning("process_order_inbound: missing salesorder_id")
        return

    new_hash = generate_payload_hash(so_data)

    async with async_session_factory() as db:
        stmt = select(Order).where(Order.zoho_id == zoho_so_id)
        order = (await db.execute(stmt)).scalar_one_or_none()
        if order is None:
            logger.debug("[DEBUG.INTERNAL_API] process_order_inbound: no local order for zoho_id=%s", zoho_so_id)
            return

        if order.zoho_last_sync_hash == new_hash:
            logger.debug("process_order_inbound: order %s hash unchanged", order.id)
            return

        # Map Zoho status → local status (broad mapping)
        _ZOHO_STATUS_MAP = {
            "draft": "PENDING",
            "confirmed": "PROCESSING",
            "packed": "READY_TO_SHIP",
            "shipped": "SHIPPED",
            "delivered": "DELIVERED",
            "void": "CANCELLED",
        }
        zoho_status = so_data.get("status", "").lower()
        if zoho_status in _ZOHO_STATUS_MAP:
            from app.modules.orders.models import OrderStatus
            order.status = OrderStatus(_ZOHO_STATUS_MAP[zoho_status])

        # Map Zoho status → local shipping status
        _ZOHO_SHIPPING_MAP = {
            "packed": "PACKED",
            "shipped": "SHIPPING",
            "delivered": "DELIVERED",
            "void": "CANCELLED",
        }
        if zoho_status in _ZOHO_SHIPPING_MAP:
            from app.modules.orders.models import ShippingStatus
            order.shipping_status = ShippingStatus(_ZOHO_SHIPPING_MAP[zoho_status])

        order.zoho_last_sync_hash = new_hash
        order.zoho_last_synced_at = datetime.now()
        order.zoho_sync_error = None
        order.zoho_sync_status = ZohoSyncStatus.SYNCED
        order._updated_by_sync = True
        await db.commit()

        logger.debug("[DEBUG.INTERNAL_API] process_order_inbound: order %s updated from Zoho", order.id)


# =========================================================================
# BACKGROUND TASK DISPATCHING HELPERS
# =========================================================================

def _enqueue_variant_sync(variant_id: int) -> None:
    """Fire-and-forget background task for variant outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_variant_outbound(variant_id))
    except RuntimeError:
        logger.debug("_enqueue_variant_sync: no running event loop, skipping")


def _enqueue_customer_sync(customer_id: int) -> None:
    """Fire-and-forget background task for customer outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_customer_outbound(customer_id))
    except RuntimeError:
        logger.debug("_enqueue_customer_sync: no running event loop, skipping")


def _enqueue_order_sync(order_id: int) -> None:
    """Fire-and-forget background task for order outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_order_outbound(order_id))
    except RuntimeError:
        logger.debug("_enqueue_order_sync: no running event loop, skipping")


def _enqueue_vendor_sync(vendor_id: int) -> None:
    """Fire-and-forget background task for vendor outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_vendor_outbound(vendor_id))
    except RuntimeError:
        logger.debug("_enqueue_vendor_sync: no running event loop, skipping")


def _enqueue_po_sync(po_id: int) -> None:
    """Fire-and-forget background task for purchase-order outbound sync."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_po_outbound(po_id))
    except RuntimeError:
        logger.debug("_enqueue_po_sync: no running event loop, skipping")


# =========================================================================
# SQLALCHEMY EVENT LISTENERS
# =========================================================================

def _on_variant_after_write(mapper, connection, target: ProductVariant):
    """Enqueue outbound sync unless this write originated from an inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_variant_sync(target.id)


def _on_customer_after_write(mapper, connection, target: Customer):
    """Enqueue outbound sync unless this write originated from an inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_customer_sync(target.id)


def _on_order_after_write(mapper, connection, target: Order):
    """Enqueue outbound sync unless this write originated from an inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_order_sync(target.id)


def _on_vendor_after_write(mapper, connection, target: Vendor):
    """Enqueue vendor outbound sync unless this write came from inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_vendor_sync(target.id)


def _on_purchase_order_after_write(mapper, connection, target: PurchaseOrder):
    """Enqueue purchase-order outbound sync unless this write came from inbound sync."""
    if target._updated_by_sync:
        return
    _enqueue_po_sync(target.id)


def register_sync_listeners() -> None:
    """
    Attach SQLAlchemy ``after_insert`` / ``after_update`` listeners.

    Call once at application startup (e.g. inside the lifespan handler).
    """
    event.listen(ProductVariant, "after_insert", _on_variant_after_write)
    event.listen(ProductVariant, "after_update", _on_variant_after_write)
    event.listen(Customer, "after_insert", _on_customer_after_write)
    event.listen(Customer, "after_update", _on_customer_after_write)
    event.listen(Order, "after_insert", _on_order_after_write)
    event.listen(Order, "after_update", _on_order_after_write)
    event.listen(Vendor, "after_insert", _on_vendor_after_write)
    event.listen(Vendor, "after_update", _on_vendor_after_write)
    event.listen(PurchaseOrder, "after_insert", _on_purchase_order_after_write)
    event.listen(PurchaseOrder, "after_update", _on_purchase_order_after_write)
    logger.info("Zoho sync event listeners registered")
