#!/usr/bin/env python
"""Backfill Zoho Purchase Order custom field `Source` from local DB purchase orders.

Behavior:
- Reads local purchase orders in a date window (default: Jan 1 of current year -> today).
- Maps local `purchase_order.source` to one of:
  Ebay, Amazon, Goodwill, AliExpress, Local Pickup, Other
- Updates the matching Zoho purchase order's custom fields.

Notes:
- Default mode is dry-run.
- Use --apply to execute updates.
- If the Source custom field cannot be identified on a PO, pass --source-customfield-id.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient
from app.models.purchasing import PurchaseOrder


VALID_SOURCE_VALUES = {
    "Ebay",
    "Amazon",
    "Goodwill",
    "AliExpress",
    "Local Pickup",
    "Other",
}

EXACT_SOURCE_MAP = {
    "EBAY_MEKONG_API": "Ebay",
    "EBAY_PURCHASING_API": "Ebay",
    "EBAY_USAV_API": "Ebay",
    "EBAY_DRAGON_API": "Ebay",
    "AMAZON_CSV": "Amazon",
    "GOODWILL_SHIPPED": "Goodwill",
    "ALIEXPRESS_JSON": "AliExpress",
    "ALIEXPRESS_CSV": "AliExpress",
    "MANUAL": "Other",
    "ZOHO_IMPORT": "Other",
}


@dataclass
class LocalPORef:
    id: int
    po_number: str
    zoho_id: str
    order_date: date
    source: str


@dataclass
class Stats:
    scanned: int = 0
    skipped_no_zoho_id: int = 0
    skipped_no_line_items: int = 0
    skipped_missing_source_cf: int = 0
    unchanged: int = 0
    would_update: int = 0
    updated: int = 0
    failed: int = 0


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except Exception as exc:
        raise ValueError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def _clean(value: object) -> str:
    return str(value or "").strip()


def _normalize_source_to_dropdown(source: str) -> str:
    text = _clean(source).upper().replace("-", "_").replace(" ", "_")
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


def _resolve_source_value(source: str) -> str:
    normalized = _clean(source).upper()
    mapped = EXACT_SOURCE_MAP.get(normalized)
    if mapped:
        return mapped
    return _normalize_source_to_dropdown(source)


def _build_discovered_source_map(targets: list[LocalPORef]) -> dict[str, str]:
    discovered = sorted({t.source for t in targets if _clean(t.source)})
    return {src: _resolve_source_value(src) for src in discovered}


def _debug(enabled: bool, msg: str) -> None:
    if enabled:
        print(f"[DEBUG] {msg}")


def _build_update_payload(full_po: dict[str, Any], custom_fields: list[dict[str, Any]]) -> dict[str, Any]:
    line_items = full_po.get("line_items") or []
    if not isinstance(line_items, list) or not line_items:
        raise ValueError("purchase order has no line_items")

    payload: dict[str, Any] = {
        "purchaseorder_number": _clean(full_po.get("purchaseorder_number")),
        "vendor_id": _clean(full_po.get("vendor_id")),
        "date": _clean(full_po.get("date")),
        "line_items": line_items,
        "custom_fields": custom_fields,
    }

    optional_keys = [
        "delivery_date",
        "reference_number",
        "is_drop_shipment",
        "is_inclusive_tax",
        "is_backorder",
        "exchange_rate",
        "notes",
        "terms",
        "ship_via",
        "attention",
        "delivery_org_address_id",
        "delivery_customer_id",
        "location_id",
        "branch_id",
        "contact_persons_associated",
        "gst_treatment",
        "gst_no",
        "source_of_supply",
        "destination_of_supply",
    ]
    for key in optional_keys:
        value = full_po.get(key)
        if value not in (None, ""):
            payload[key] = value

    return payload


def _is_source_field_entry(field: dict[str, Any]) -> bool:
    candidates = {
        _clean(field.get("label")).lower(),
        _clean(field.get("name")).lower(),
        _clean(field.get("api_name")).lower(),
    }
    return "source" in candidates or "cf_source" in candidates


def _extract_existing_source_value(full_po: dict[str, Any], custom_fields: list[dict[str, Any]]) -> str:
    # Most explicit shape in your org snapshot.
    direct = _clean(full_po.get("cf_source"))
    if direct:
        return direct

    direct_unformatted = _clean(full_po.get("cf_source_unformatted"))
    if direct_unformatted:
        return direct_unformatted

    for field in custom_fields:
        if isinstance(field, dict) and _is_source_field_entry(field):
            value = _clean(field.get("value"))
            if value:
                return value

    return ""


def _upsert_source_custom_field(
    existing_fields: list[dict[str, Any]],
    *,
    source_value: str,
    source_customfield_id: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return (updated_fields, changed)."""
    updated: list[dict[str, Any]] = [dict(f) for f in (existing_fields or []) if isinstance(f, dict)]
    source_id = _clean(source_customfield_id)

    # 1) Match explicit customfield_id first when provided.
    if source_id:
        for field in updated:
            if _clean(field.get("customfield_id")) == source_id:
                current = _clean(field.get("value"))
                if current == source_value:
                    return updated, False
                field["value"] = source_value
                return updated, True

    # 2) Match by semantic name/api_name/label.
    for field in updated:
        if _is_source_field_entry(field):
            current = _clean(field.get("value"))
            if current == source_value:
                return updated, False
            field["value"] = source_value
            return updated, True

    # 3) Append new entry using customfield_id when available.
    if source_id:
        updated.append({"customfield_id": source_id, "value": source_value})
        return updated, True

    # 4) Fallback: many Inventory endpoints accept api_name for custom fields.
    updated.append({"api_name": "cf_source", "value": source_value})
    return updated, True


async def _fetch_local_targets(start_date: date, end_date: date, limit: int | None) -> list[LocalPORef]:
    async with async_session_factory() as session:
        stmt = (
            select(PurchaseOrder.id, PurchaseOrder.po_number, PurchaseOrder.zoho_id, PurchaseOrder.order_date, PurchaseOrder.source)
            .where(
                PurchaseOrder.order_date >= start_date,
                PurchaseOrder.order_date <= end_date,
            )
            .order_by(PurchaseOrder.order_date.asc(), PurchaseOrder.id.asc())
        )
        if limit and limit > 0:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).all()
        result: list[LocalPORef] = []
        for row in rows:
            result.append(
                LocalPORef(
                    id=int(row[0]),
                    po_number=_clean(row[1]),
                    zoho_id=_clean(row[2]),
                    order_date=row[3],
                    source=_clean(row[4]),
                )
            )
        return result


async def main() -> None:
    today = date.today()
    jan_first = date(today.year, 1, 1)

    parser = argparse.ArgumentParser(description="Backfill Zoho PO custom field Source from local PO source")
    parser.add_argument("--start-date", default=jan_first.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=today.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--source-customfield-id", default="", help="Zoho customfield_id for Source (recommended)")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on rows to process")
    parser.add_argument("--apply", action="store_true", help="Execute updates in Zoho")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if end_date < start_date:
        raise ValueError("end-date must be >= start-date")

    apply_mode = bool(args.apply)
    limit = args.limit if args.limit and args.limit > 0 else None
    source_customfield_id = _clean(args.source_customfield_id)

    print(f"Window: {start_date.isoformat()} -> {end_date.isoformat()}")
    print(f"Mode: {'APPLY' if apply_mode else 'DRY-RUN'}")
    if source_customfield_id:
        print(f"Source customfield_id: {source_customfield_id}")
    else:
        print("Source customfield_id: <auto-detect from existing PO custom_fields>")
    if limit:
        print(f"Limit: {limit}")

    targets = await _fetch_local_targets(start_date, end_date, limit)
    print(f"Local purchase orders in window: {len(targets)}")

    if not targets:
        print("Nothing to process.")
        return

    discovered_source_map = _build_discovered_source_map(targets)
    if discovered_source_map:
        print("Discovered local source values and Zoho Source mapping:")
        for src, mapped in discovered_source_map.items():
            print(f"- {src} -> {mapped}")

    client = ZohoClient()
    stats = Stats()

    for local_po in targets:
        stats.scanned += 1

        if not local_po.zoho_id:
            stats.skipped_no_zoho_id += 1
            continue

        source_value = _resolve_source_value(local_po.source)
        if source_value not in VALID_SOURCE_VALUES:
            source_value = "Other"

        try:
            full_po = await client.get_purchase_order(local_po.zoho_id)
            line_items = full_po.get("line_items") or []
            if not isinstance(line_items, list) or not line_items:
                stats.skipped_no_line_items += 1
                _debug(args.debug, f"Skip {local_po.po_number}: no line_items in Zoho PO {local_po.zoho_id}")
                continue

            existing_custom_fields = full_po.get("custom_fields") or []
            existing_source_value = _extract_existing_source_value(full_po, existing_custom_fields)
            if existing_source_value == source_value:
                stats.unchanged += 1
                continue

            new_custom_fields, changed = _upsert_source_custom_field(
                existing_custom_fields,
                source_value=source_value,
                source_customfield_id=source_customfield_id or None,
            )

            if not changed:
                stats.skipped_missing_source_cf += 1
                _debug(
                    args.debug,
                    f"Skip {local_po.po_number}: unable to build Source custom field update",
                )
                continue

            payload = _build_update_payload(full_po, new_custom_fields)
            _debug(
                args.debug,
                f"PO {local_po.po_number} source='{local_po.source}' mapped='{source_value}' payload_keys={list(payload.keys())}",
            )

            if apply_mode:
                await client.update_purchase_order(local_po.zoho_id, payload)
                stats.updated += 1
            else:
                stats.would_update += 1

        except Exception as exc:
            stats.failed += 1
            print(f"[ERROR] PO {local_po.po_number} (zoho_id={local_po.zoho_id}) failed: {exc}")

    print("\nSummary")
    print(f"- scanned: {stats.scanned}")
    print(f"- skipped_no_zoho_id: {stats.skipped_no_zoho_id}")
    print(f"- skipped_no_line_items: {stats.skipped_no_line_items}")
    print(f"- skipped_missing_source_cf: {stats.skipped_missing_source_cf}")
    print(f"- unchanged: {stats.unchanged}")
    print(f"- would_update: {stats.would_update}")
    print(f"- updated: {stats.updated}")
    print(f"- failed: {stats.failed}")


if __name__ == "__main__":
    asyncio.run(main())
