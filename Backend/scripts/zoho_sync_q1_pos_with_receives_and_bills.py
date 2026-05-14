#!/usr/bin/env python
"""Sync Q1 purchase orders to Zoho, then create missing receives and bills from CSV metadata.

Flow per purchase order:
1) Upsert purchase order via existing sync engine.
2) Resolver order before sync: local zoho_id -> fallback by Zoho reference_number == local po_number.
3) Create missing purchase receives from Purchase_Receive.csv metadata.
4) Create missing bills from Bill.csv metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import noload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient
from app.integrations.zoho.sync_engine import PAYMENT_TERMS_DUE_ON_RECEIPT, sync_po_outbound
from app.models.purchasing import PurchaseOrder


DEFAULT_START_DATE = date(2026, 1, 1)
DEFAULT_END_DATE = date(2026, 3, 31)
DEFAULT_BILL_CSV = PROJECT_ROOT / "misc" / "Bill.csv"
DEFAULT_RECEIVE_CSV = PROJECT_ROOT / "misc" / "Purchase_Receive.csv"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _parse_iso(value: str, field_name: str) -> date:
    raw = _clean(value)
    if not raw:
        raise ValueError(f"{field_name} is required")
    try:
        return date.fromisoformat(raw)
    except Exception as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD: {raw}") from exc


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _validate_csv_headers(path: Path, required: set[str]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        headers = set(csv.DictReader(f).fieldnames or [])
    missing = sorted(required - headers)
    if missing:
        raise ValueError(f"{path} missing required headers: {missing}")


def _build_receive_scope(rows: list[dict[str, str]]) -> dict[str, dict[str, dict[str, str]]]:
    scope: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        po_number = _clean(row.get("PO Number"))
        receive_number = _clean(row.get("Receive Number"))
        if not po_number or not receive_number:
            continue
        current = scope[po_number].get(receive_number)
        if current is None:
            scope[po_number][receive_number] = {
                "receive_number": receive_number,
                "receive_date": _clean(row.get("Receive Date")),
                "notes": _clean(row.get("Notes")),
            }
            continue

        if not current["receive_date"]:
            current["receive_date"] = _clean(row.get("Receive Date"))
        if not current["notes"]:
            current["notes"] = _clean(row.get("Notes"))
    return scope


def _build_bill_scope(rows: list[dict[str, str]]) -> dict[str, dict[str, dict[str, str]]]:
    scope: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        po_number = _clean(
            row.get("PurchaseOrder")
            or row.get("Purchase Order Number")
            or row.get("Reference Number")
        )
        bill_number = _clean(row.get("Bill Number")) or po_number
        if not po_number or not bill_number:
            continue
        current = scope[po_number].get(bill_number)
        if current is None:
            scope[po_number][bill_number] = {
                "bill_number": bill_number,
                "bill_date": _clean(row.get("Bill Date")),
            }
            continue

        if not current["bill_date"]:
            current["bill_date"] = _clean(row.get("Bill Date"))
    return scope


async def _load_local_pos(start_date: date, end_date: date, *, limit: int, offset: int) -> list[PurchaseOrder]:
    async with async_session_factory() as db:
        stmt = (
            select(PurchaseOrder)
            .options(noload(PurchaseOrder.vendor), noload(PurchaseOrder.items))
            .where(PurchaseOrder.order_date >= start_date, PurchaseOrder.order_date <= end_date)
            .order_by(PurchaseOrder.order_date.asc(), PurchaseOrder.id.asc())
            .offset(offset)
        )
        if limit > 0:
            stmt = stmt.limit(limit)
        return (await db.execute(stmt)).scalars().all()


async def _load_po_state(po_id: int) -> Optional[dict[str, str]]:
    async with async_session_factory() as db:
        po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))).scalar_one_or_none()
        if po is None:
            return None
        return {
            "po_number": _clean(po.po_number),
            "zoho_id": _clean(po.zoho_id),
            "currency_code": _clean(po.currency or "USD"),
            "sync_status": _clean(getattr(po.zoho_sync_status, "value", po.zoho_sync_status)),
            "sync_error": _clean(po.zoho_sync_error),
        }


async def _set_local_zoho_id(po_id: int, zoho_id: str) -> None:
    async with async_session_factory() as db:
        po = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))).scalar_one_or_none()
        if po is None:
            return
        po.zoho_id = zoho_id
        po._updated_by_sync = True
        await db.commit()


async def _find_purchase_order_by_reference(
    client: ZohoClient,
    *,
    reference_number: str,
    reference_cache: dict[str, str],
    max_pages: int = 50,
    per_page: int = 200,
) -> Optional[dict[str, Any]]:
    normalized = _clean(reference_number)
    if not normalized:
        return None

    cached = _clean(reference_cache.get(normalized))
    if cached:
        return {"purchaseorder_id": cached}

    page = 1
    while page <= max_pages:
        purchase_orders = await client.list_purchase_orders(page=page, per_page=per_page)
        if not purchase_orders:
            return None

        for remote_po in purchase_orders:
            if not isinstance(remote_po, dict):
                continue
            remote_ref = _clean(remote_po.get("reference_number"))
            remote_id = _clean(remote_po.get("purchaseorder_id"))
            if remote_ref and remote_id and remote_ref not in reference_cache:
                reference_cache[remote_ref] = remote_id
            if remote_ref == normalized and remote_id:
                return remote_po

        if len(purchase_orders) < per_page:
            return None
        page += 1

    return None


async def _resolve_target_zoho_id(
    client: ZohoClient,
    *,
    po_number: str,
    local_zoho_id: str,
    reference_cache: dict[str, str],
) -> tuple[Optional[str], str]:
    candidate_id = _clean(local_zoho_id)
    if candidate_id:
        try:
            remote_po = await client.get_purchase_order(candidate_id)
        except Exception:
            remote_po = None
        if remote_po:
            remote_number = _clean(remote_po.get("purchaseorder_number"))
            remote_ref = _clean(remote_po.get("reference_number"))
            if remote_number == po_number or remote_ref == po_number:
                return candidate_id, "used_local_zoho_id"

    by_reference = await _find_purchase_order_by_reference(
        client,
        reference_number=po_number,
        reference_cache=reference_cache,
    )
    resolved = _clean((by_reference or {}).get("purchaseorder_id"))
    if resolved:
        return resolved, "resolved_by_reference_number"

    return None, "no_existing_zoho_po_found"


def _existing_receive_numbers(full_po: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for row in full_po.get("purchasereceives") or full_po.get("receives") or []:
        if not isinstance(row, dict):
            continue
        number = _clean(row.get("receive_number"))
        if number:
            values.add(number)
    return values


def _existing_bill_numbers(full_po: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for row in full_po.get("bills") or []:
        if not isinstance(row, dict):
            continue
        number = _clean(row.get("bill_number"))
        if number:
            values.add(number)
    return values


def _build_receive_payload(full_po: dict[str, Any], *, receive_number: str, receive_date: str, notes: str) -> Optional[dict[str, Any]]:
    po_id = _clean(full_po.get("purchaseorder_id"))
    if not po_id:
        return None

    line_items: list[dict[str, Any]] = []
    for line in full_po.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        item_id = _clean(line.get("item_id"))
        line_item_id = _clean(line.get("line_item_id") or line.get("purchaseorder_item_id"))
        quantity_raw = line.get("quantity") or line.get("quantity_received") or 0
        try:
            quantity = float(quantity_raw)
        except Exception:
            quantity = 0.0
        if not item_id or quantity <= 0:
            continue

        payload_line: dict[str, Any] = {
            "item_id": item_id,
            "quantity": quantity,
            "quantity_received": quantity,
        }
        if line_item_id:
            payload_line["line_item_id"] = line_item_id
        line_items.append(payload_line)

    if not line_items:
        return None

    payload: dict[str, Any] = {
        "purchaseorder_id": po_id,
        "receive_number": receive_number,
        "line_items": line_items,
    }
    if receive_date:
        payload["date"] = receive_date
    if notes:
        payload["notes"] = notes
    return payload


def _build_bill_payload(
    full_po: dict[str, Any],
    *,
    po_number: str,
    currency_code: str,
    bill_number: str,
    bill_date: str,
) -> Optional[dict[str, Any]]:
    po_id = _clean(full_po.get("purchaseorder_id"))
    vendor_id = _clean(full_po.get("vendor_id"))
    if not po_id or not vendor_id:
        return None

    line_items: list[dict[str, Any]] = []
    for line in full_po.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        quantity_raw = line.get("quantity") or 0
        try:
            quantity = float(quantity_raw)
        except Exception:
            quantity = 0.0
        if quantity <= 0:
            continue

        payload_line: dict[str, Any] = {"quantity": quantity}
        po_item_id = _clean(line.get("purchaseorder_item_id") or line.get("line_item_id"))
        item_id = _clean(line.get("item_id"))
        rate = line.get("purchase_rate") or line.get("rate") or line.get("bcy_rate")
        if po_item_id:
            payload_line["purchaseorder_item_id"] = po_item_id
        if item_id:
            payload_line["item_id"] = item_id
        if rate is not None and _clean(rate) != "":
            payload_line["rate"] = rate
        line_items.append(payload_line)

    if not line_items:
        return None

    normalized_bill_date = _clean(bill_date) or _clean(full_po.get("date"))
    if not normalized_bill_date:
        return None

    return {
        "purchaseorder_id": po_id,
        "vendor_id": vendor_id,
        "bill_number": bill_number,
        "reference_number": po_number,
        "date": normalized_bill_date,
        "due_date": normalized_bill_date,
        "payment_terms": PAYMENT_TERMS_DUE_ON_RECEIPT,
        "currency_code": currency_code or "USD",
        "line_items": line_items,
    }


async def _inventory_create_bill(client: ZohoClient, payload: dict[str, Any]) -> dict[str, Any]:
    result = await client._request(
        "POST",
        "/bills",
        api="inventory",
        data={"JSONString": json.dumps(payload)},
    )
    return result.get("bill", {}) or {}


async def _run(
    *,
    start_date: date,
    end_date: date,
    bill_csv: Path,
    receive_csv: Path,
    dry_run: bool,
    progress_every: int,
    limit: int,
    offset: int,
) -> int:
    _validate_csv_headers(receive_csv, {"PO Number", "Receive Number", "Receive Date", "Notes"})
    _validate_csv_headers(bill_csv, {"PurchaseOrder", "Bill Number", "Bill Date"})

    receive_scope = _build_receive_scope(_read_csv_rows(receive_csv))
    bill_scope = _build_bill_scope(_read_csv_rows(bill_csv))

    local_pos = await _load_local_pos(start_date, end_date, limit=limit, offset=offset)
    if not local_pos:
        print("No local purchase orders found in requested date range.")
        return 0

    print(
        f"Selected {len(local_pos)} local purchase orders in range {start_date.isoformat()}..{end_date.isoformat()} "
        f"(dry_run={dry_run})"
    )

    summary = {
        "po_processed": 0,
        "po_sync_ok": 0,
        "po_sync_failed": 0,
        "po_relinked_by_reference": 0,
        "receive_created": 0,
        "receive_skipped_existing": 0,
        "receive_failed": 0,
        "bill_created": 0,
        "bill_skipped_existing": 0,
        "bill_failed": 0,
    }

    reference_cache: dict[str, str] = {}
    client = ZohoClient()

    for idx, po in enumerate(local_pos, start=1):
        po_number = _clean(po.po_number)
        summary["po_processed"] += 1

        local_state = await _load_po_state(po.id)
        if local_state is None:
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] failed: local record missing at runtime")
            continue

        resolved_zoho_id, resolve_reason = await _resolve_target_zoho_id(
            client,
            po_number=po_number,
            local_zoho_id=_clean(local_state.get("zoho_id")),
            reference_cache=reference_cache,
        )
        if resolve_reason == "resolved_by_reference_number" and resolved_zoho_id:
            summary["po_relinked_by_reference"] += 1
            if not dry_run:
                await _set_local_zoho_id(po.id, resolved_zoho_id)

        if dry_run:
            planned_receives = len(receive_scope.get(po_number, {}))
            planned_bills = len(bill_scope.get(po_number, {}))
            print(
                f"[po {po.id} {po_number}] dry-run: resolver={resolve_reason} "
                f"planned_receives={planned_receives} planned_bills={planned_bills}"
            )
            continue

        await sync_po_outbound(
            po.id,
            allow_billed_unbill_rebill=False,
            enable_ebay_billing=False,
        )

        synced_state = await _load_po_state(po.id)
        sync_status = _clean((synced_state or {}).get("sync_status"))
        sync_error = _clean((synced_state or {}).get("sync_error"))
        if sync_status != "SYNCED":
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] PO upsert failed: status={sync_status or 'unknown'} error={sync_error}")
            continue

        summary["po_sync_ok"] += 1
        zoho_id = _clean((synced_state or {}).get("zoho_id"))
        currency_code = _clean((synced_state or {}).get("currency_code") or "USD")
        if not zoho_id:
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] PO upsert failed: local zoho_id is empty after sync")
            continue

        try:
            full_po = await client.get_purchase_order(zoho_id)
        except Exception as exc:
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] failed to fetch synced Zoho PO: {exc}")
            continue

        existing_receive_numbers = _existing_receive_numbers(full_po)
        for receive_number, meta in sorted(receive_scope.get(po_number, {}).items()):
            if receive_number in existing_receive_numbers:
                summary["receive_skipped_existing"] += 1
                continue
            payload = _build_receive_payload(
                full_po,
                receive_number=receive_number,
                receive_date=_clean(meta.get("receive_date")),
                notes=_clean(meta.get("notes")),
            )
            if not payload:
                summary["receive_failed"] += 1
                print(f"[po {po.id} {po_number}] receive create skipped: invalid payload for {receive_number}")
                continue
            try:
                await client.create_purchase_receive(payload)
                summary["receive_created"] += 1
                existing_receive_numbers.add(receive_number)
            except Exception as exc:
                summary["receive_failed"] += 1
                print(f"[po {po.id} {po_number}] receive create failed ({receive_number}): {exc}")

        try:
            full_po_after_receive = await client.get_purchase_order(zoho_id)
        except Exception:
            full_po_after_receive = full_po
        existing_bill_numbers = _existing_bill_numbers(full_po_after_receive)

        for bill_number, meta in sorted(bill_scope.get(po_number, {}).items()):
            if bill_number in existing_bill_numbers:
                summary["bill_skipped_existing"] += 1
                continue
            payload = _build_bill_payload(
                full_po_after_receive,
                po_number=po_number,
                currency_code=currency_code or "USD",
                bill_number=bill_number,
                bill_date=_clean(meta.get("bill_date")),
            )
            if not payload:
                summary["bill_failed"] += 1
                print(f"[po {po.id} {po_number}] bill create skipped: invalid payload for {bill_number}")
                continue
            try:
                await _inventory_create_bill(client, payload)
                summary["bill_created"] += 1
                existing_bill_numbers.add(bill_number)
            except Exception as exc:
                summary["bill_failed"] += 1
                print(f"[po {po.id} {po_number}] bill create failed ({bill_number}): {exc}")

        if progress_every > 0 and (idx % progress_every == 0):
            print(
                f"[progress] processed={idx}/{len(local_pos)} "
                f"synced={summary['po_sync_ok']} receive_created={summary['receive_created']} bill_created={summary['bill_created']}"
            )

    print(json.dumps(summary, indent=2))
    return 0 if summary["po_sync_failed"] == 0 else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync local Q1 purchase orders to Zoho and create receives/bills from CSV metadata.",
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE.isoformat(), help="YYYY-MM-DD (default: 2026-01-01)")
    parser.add_argument("--end-date", default=DEFAULT_END_DATE.isoformat(), help="YYYY-MM-DD (default: 2026-03-31)")
    parser.add_argument("--bill-csv", default=str(DEFAULT_BILL_CSV), help="Path to Bill.csv")
    parser.add_argument("--receive-csv", default=str(DEFAULT_RECEIVE_CSV), help="Path to Purchase_Receive.csv")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no writes")
    parser.add_argument("--progress-every", type=int, default=25, help="Print progress every N purchase orders")
    parser.add_argument("--limit", type=int, default=0, help="Max number of local purchase orders to process (0 = all)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N local purchase orders in date-range ordering")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    start_date = _parse_iso(args.start_date, "start-date")
    end_date = _parse_iso(args.end_date, "end-date")
    if end_date < start_date:
        raise ValueError("end-date must be >= start-date")
    if int(args.limit) < 0:
        raise ValueError("limit must be >= 0")
    if int(args.offset) < 0:
        raise ValueError("offset must be >= 0")

    return asyncio.run(
        _run(
            start_date=start_date,
            end_date=end_date,
            bill_csv=Path(args.bill_csv),
            receive_csv=Path(args.receive_csv),
            dry_run=bool(args.dry_run),
            progress_every=int(args.progress_every),
            limit=int(args.limit),
            offset=int(args.offset),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
