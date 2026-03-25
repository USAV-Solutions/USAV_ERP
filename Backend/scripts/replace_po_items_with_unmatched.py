#!/usr/bin/env python
"""Replace non-[OLD] purchase-order line items with unmatched placeholder in Zoho.

Flow:
1) Fetch purchase orders in date window.
2) Inspect each PO line item.
3) If line item name or SKU does not start with [OLD], replace line item with:
   - name: unmatched item
   - sku: 00000
   - item_id: placeholder item's Zoho ID
4) Update PO in Zoho (only when --apply is used).

Default mode is dry-run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.integrations.zoho.client import ZohoClient


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _parse_iso_date(value: str | None) -> Optional[date]:
    raw = _clean(value)
    if not raw:
        return None
    return date.fromisoformat(raw)


def _parse_csv_date(value: str | None) -> Optional[date]:
    raw = _clean(value)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}")


def _trace(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[api] {message}")


def _install_api_trace(client: ZohoClient, enabled: bool) -> None:
    if not enabled:
        return

    original_request = client._request

    async def traced_request(method: str, endpoint: str, api: str = "inventory", **kwargs: Any) -> dict:
        params = dict(kwargs.get("params") or {})
        params["organization_id"] = client.organization_id
        payload_mode = "none"
        if "files" in kwargs:
            payload_mode = "files"
        elif "json" in kwargs:
            payload_mode = "json"
        elif "data" in kwargs:
            payload_mode = "data"

        _trace(
            enabled,
            f"REQ method={method} api={api} endpoint={endpoint} params={json.dumps(params, separators=(',', ':'))} payload_mode={payload_mode}",
        )
        try:
            result = await original_request(method, endpoint, api=api, **kwargs)
        except Exception as exc:
            _trace(enabled, f"ERR method={method} api={api} endpoint={endpoint} error={exc}")
            raise

        keys = sorted(list(result.keys())) if isinstance(result, dict) else []
        _trace(enabled, f"RES method={method} api={api} endpoint={endpoint} keys={json.dumps(keys)}")
        return result

    client._request = traced_request  # type: ignore[method-assign]


def _extract_po_date(po: dict[str, Any]) -> Optional[date]:
    for key in ("date", "purchaseorder_date", "purchase_order_date", "order_date"):
        parsed = _parse_csv_date(_clean(po.get(key)))
        if parsed is not None:
            return parsed
    return None


def _extract_po_id(po: dict[str, Any]) -> str:
    return _clean(po.get("purchaseorder_id") or po.get("purchase_order_id") or po.get("id"))


def _extract_po_number(po: dict[str, Any]) -> str:
    return _clean(
        po.get("purchaseorder_number")
        or po.get("purchase_order_number")
        or po.get("po_number")
        or po.get("purchaseorder")
    )


def _has_old_prefix(value: str) -> bool:
    return _clean(value).upper().startswith("[OLD]")


def _line_needs_replacement(line: dict[str, Any]) -> bool:
    sku = _clean(line.get("sku"))
    # User-approved rule: replacement is based on SKU only, regardless of name.
    return not _has_old_prefix(sku)


def _find_placeholder_item(items: list[dict[str, Any]], target_name: str, target_sku: str) -> Optional[dict[str, Any]]:
    exact_both = [
        item
        for item in items
        if _clean(item.get("name")).lower() == target_name.lower()
        and _clean(item.get("sku")) == target_sku
    ]
    if exact_both:
        return exact_both[0]

    exact_name = [item for item in items if _clean(item.get("name")).lower() == target_name.lower()]
    if exact_name:
        return exact_name[0]

    exact_sku = [item for item in items if _clean(item.get("sku")) == target_sku]
    if exact_sku:
        return exact_sku[0]

    return None


async def _get_placeholder_item(
    client: ZohoClient,
    *,
    target_name: str,
    target_sku: str,
    create_if_missing: bool,
) -> dict[str, Any]:
    all_items: list[dict[str, Any]] = []
    page = 1
    per_page = 200
    while True:
        chunk = await client.list_items(page=page, per_page=per_page)
        if not chunk:
            break
        all_items.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1

    found = _find_placeholder_item(all_items, target_name=target_name, target_sku=target_sku)
    if found:
        return found

    if not create_if_missing:
        raise RuntimeError(
            f"Placeholder item not found by name '{target_name}' or sku '{target_sku}'. Use --create-placeholder to create it."
        )

    created = await client.create_item(
        {
            "name": target_name,
            "sku": target_sku,
            "rate": 0,
            "purchase_rate": 0,
            "item_type": "inventory",
            "product_type": "goods",
            "description": "Auto-created placeholder for unmatched purchase items",
        }
    )
    if not created:
        raise RuntimeError("Failed to create placeholder item")
    return created


def _build_update_line_item(
    src_line: dict[str, Any],
    *,
    placeholder_item_id: str,
    placeholder_name: str,
    placeholder_sku: str,
) -> dict[str, Any]:
    updated = dict(src_line)
    updated["item_id"] = placeholder_item_id
    updated["name"] = placeholder_name
    updated["sku"] = placeholder_sku
    return updated


def _build_update_payload(full_po: dict[str, Any], updated_lines: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "purchaseorder_number": _clean(full_po.get("purchaseorder_number")),
        "vendor_id": _clean(full_po.get("vendor_id")),
        "date": _clean(full_po.get("date")),
        "line_items": updated_lines,
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
        "custom_fields",
        "contact_persons_associated",
        "gst_treatment",
        "gst_no",
        "source_of_supply",
        "destination_of_supply",
    ]
    for key in optional_keys:
        if key in full_po and full_po.get(key) not in (None, ""):
            payload[key] = full_po.get(key)

    return payload


async def _fetch_target_pos(client: ZohoClient, start_date: date, end_date: date, debug: bool) -> list[dict[str, Any]]:
    all_pos: list[dict[str, Any]] = []
    page = 1
    per_page = 200

    while True:
        chunk = await client.list_purchase_orders(page=page, per_page=per_page, filter_by="Status.All")
        if not chunk:
            break
        all_pos.extend(chunk)
        _debug(debug, f"Fetched purchaseorders page={page} count={len(chunk)}")
        if len(chunk) < per_page:
            break
        page += 1

    selected: list[dict[str, Any]] = []
    for po in all_pos:
        po_date = _extract_po_date(po)
        if po_date is None:
            continue
        if start_date <= po_date <= end_date:
            selected.append(po)
    return selected


async def main() -> None:
    today = date.today()

    parser = argparse.ArgumentParser(
        description=(
            "Replace purchase-order line items that are not [OLD]-prefixed with unmatched placeholder item in Zoho"
        )
    )
    parser.add_argument("--start-date", default="2026-03-04", help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=today.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--placeholder-name", default="unmatched item")
    parser.add_argument("--placeholder-sku", default="00000")
    parser.add_argument("--create-placeholder", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Testing mode (no Zoho updates)")
    parser.add_argument("--apply", action="store_true", help="Execute PO updates in Zoho")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--trace-api", action="store_true")
    parser.add_argument(
        "--report-path",
        default=str(PROJECT_ROOT / "scripts" / "zoho_po_unmatched_rewrite_report.json"),
        help="Output JSON report path",
    )
    args = parser.parse_args()

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if start_date is None or end_date is None:
        raise ValueError("start-date and end-date must be valid YYYY-MM-DD")
    if end_date < start_date:
        raise ValueError("end-date must be >= start-date")

    client = ZohoClient()
    _install_api_trace(client, enabled=bool(args.trace_api))

    apply_mode = bool(args.apply and not args.dry_run)

    _debug(
        args.debug,
        (
            f"Window start={start_date.isoformat()} end={end_date.isoformat()} "
            f"apply={apply_mode} dry_run={not apply_mode} org_id={client.organization_id}"
        ),
    )

    placeholder = await _get_placeholder_item(
        client,
        target_name=args.placeholder_name,
        target_sku=args.placeholder_sku,
        create_if_missing=bool(args.create_placeholder),
    )
    placeholder_item_id = _clean(placeholder.get("item_id"))
    if not placeholder_item_id:
        raise RuntimeError("Placeholder item has no item_id")

    print("Fetching purchase orders in range...")
    target_pos = await _fetch_target_pos(client, start_date=start_date, end_date=end_date, debug=bool(args.debug))
    print(f"Target purchase orders: {len(target_pos)}")

    attempted_updates = 0
    successful_updates = 0
    failed_updates: list[dict[str, str]] = []
    changed_pos: list[dict[str, Any]] = []

    for po in target_pos:
        po_id = _extract_po_id(po)
        po_number = _extract_po_number(po)
        if not po_id:
            continue

        full_po = await client.get_purchase_order(po_id)
        original_lines = list(full_po.get("line_items") or [])
        if not original_lines:
            continue

        updated_lines: list[dict[str, Any]] = []
        line_changes: list[dict[str, str]] = []

        for line in original_lines:
            if not isinstance(line, dict):
                continue

            line_id = _clean(line.get("line_item_id"))
            old_name = _clean(line.get("name"))
            old_sku = _clean(line.get("sku"))

            if _line_needs_replacement(line):
                replaced = _build_update_line_item(
                    line,
                    placeholder_item_id=placeholder_item_id,
                    placeholder_name=args.placeholder_name,
                    placeholder_sku=args.placeholder_sku,
                )
                updated_lines.append(replaced)
                line_changes.append(
                    {
                        "line_item_id": line_id,
                        "from_name": old_name,
                        "from_sku": old_sku,
                        "to_name": args.placeholder_name,
                        "to_sku": args.placeholder_sku,
                    }
                )
            else:
                updated_lines.append(dict(line))

        if not line_changes:
            continue

        attempted_updates += 1
        if apply_mode:
            payload = _build_update_payload(full_po, updated_lines)
            try:
                await client.update_purchase_order(po_id, payload)
                successful_updates += 1
            except Exception as exc:
                failed_updates.append(
                    {
                        "purchaseorder_id": po_id,
                        "purchaseorder_number": po_number,
                        "error": str(exc),
                    }
                )
                continue
        else:
            successful_updates += 1

        changed_pos.append(
            {
                "purchaseorder_id": po_id,
                "purchaseorder_number": po_number,
                "lines_changed": len(line_changes),
                "line_changes": line_changes,
            }
        )

        _debug(
            args.debug,
            (
                f"PO changed id={po_id} number={po_number} "
                f"lines_changed={len(line_changes)} apply={apply_mode}"
            ),
        )

    report = {
        "window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "apply": apply_mode,
            "dry_run": not apply_mode,
        },
        "placeholder": {
            "item_id": placeholder_item_id,
            "name": args.placeholder_name,
            "sku": args.placeholder_sku,
            "create_if_missing": bool(args.create_placeholder),
        },
        "summary": {
            "target_purchase_orders": len(target_pos),
            "purchase_orders_with_changes": len(changed_pos),
            "attempted_updates": attempted_updates,
            "successful_updates": successful_updates,
            "failed_updates": len(failed_updates),
        },
        "changed_purchase_orders": changed_pos,
        "failed": failed_updates,
    }

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Done.")
    print(f"Report written to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
