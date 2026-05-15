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
from datetime import date, datetime, timezone
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
from app.models.entities import ZohoSyncStatus
from app.models.purchasing import PurchaseOrder


DEFAULT_START_DATE = date(2026, 1, 1)
DEFAULT_END_DATE = date(2026, 3, 31)
DEFAULT_BILL_CSV = PROJECT_ROOT / "misc" / "Bill.csv"
DEFAULT_RECEIVE_CSV = PROJECT_ROOT / "misc" / "Purchase_Receive.csv"
DEFAULT_FAILURE_LOG_PATH = PROJECT_ROOT / "scripts" / "zoho_sync_q1_pos_with_receives_and_bills_failures.json"


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_failure(
    failures: list[dict[str, Any]],
    *,
    po_id: int,
    po_number: str,
    stage: str,
    error: str,
    bill_number: str = "",
    receive_number: str = "",
) -> None:
    failures.append(
        {
            "time_utc": _now_iso(),
            "po_id": po_id,
            "po_number": po_number,
            "stage": stage,
            "bill_number": bill_number,
            "receive_number": receive_number,
            "error": error,
        }
    )


def _write_failure_log(
    *,
    path: Path,
    run_started_at_utc: str,
    run_finished_at_utc: str,
    start_date: date,
    end_date: date,
    dry_run: bool,
    limit: int,
    offset: int,
    summary: dict[str, Any],
    failures: list[dict[str, Any]],
) -> None:
    failed_order_keys: set[tuple[int, str]] = set()
    for item in failures:
        po_id_raw = item.get("po_id")
        po_number = _clean(item.get("po_number"))
        if po_id_raw is None or not po_number:
            continue
        try:
            po_id = int(po_id_raw)
        except Exception:
            continue
        failed_order_keys.add((po_id, po_number))

    failed_orders = [
        {"po_id": po_id, "po_number": po_number}
        for po_id, po_number in sorted(failed_order_keys, key=lambda x: (x[1], x[0]))
    ]

    report = {
        "run_started_at_utc": run_started_at_utc,
        "run_finished_at_utc": run_finished_at_utc,
        "window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "dry_run": dry_run,
            "limit": limit,
            "offset": offset,
        },
        "summary": summary,
        "failure_count": len(failures),
        "failed_order_count": len(failed_orders),
        "failed_orders": failed_orders,
        "failures": failures,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


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
            .where(
                PurchaseOrder.order_date >= start_date,
                PurchaseOrder.order_date <= end_date,
                PurchaseOrder.zoho_sync_status == ZohoSyncStatus.DIRTY,
            )
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


def _build_receive_payload(
    full_po: dict[str, Any],
    *,
    receive_number: str,
    receive_date: str,
    notes: str,
    bill_line_item_by_po_line_id: Optional[dict[str, str]] = None,
) -> Optional[dict[str, Any]]:
    po_id = _clean(full_po.get("purchaseorder_id"))
    if not po_id:
        return None

    bill_line_item_by_po_line_id = bill_line_item_by_po_line_id or {}
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
            bill_line_item_id = _clean(bill_line_item_by_po_line_id.get(line_item_id))
            if bill_line_item_id:
                payload_line["bill_line_item_id"] = bill_line_item_id
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


async def _inventory_create_purchase_receive(client: ZohoClient, payload: dict[str, Any], *, debug: bool) -> dict[str, Any]:
    purchaseorder_id = _clean(payload.get("purchaseorder_id"))
    request_body = {"JSONString": json.dumps(payload)}
    if debug:
        print(
            "[receive-debug] request "
            f"{json.dumps({'method': 'POST', 'api': 'inventory', 'endpoint': '/purchasereceives', 'params': {'purchaseorder_id': purchaseorder_id}, 'data': request_body}, ensure_ascii=False)}"
        )
    try:
        result = await client._request(
            "POST",
            "/purchasereceives",
            api="inventory",
            params={"purchaseorder_id": purchaseorder_id},
            data=request_body,
        )
        if debug:
            print(f"[receive-debug] response {json.dumps(result, default=str, ensure_ascii=False)}")
        receive = result.get("purchasereceive")
        if receive is None:
            receive = result.get("purchase_receive", {})
        return receive or {}
    except Exception as exc:
        if debug:
            print(f"[receive-debug] error {json.dumps({'error': str(exc), 'payload': payload}, default=str, ensure_ascii=False)}")
        raise


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
    }


def _po_bill_id_map(full_po: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in full_po.get("bills") or []:
        if not isinstance(row, dict):
            continue
        bill_number = _clean(row.get("bill_number"))
        bill_id = _clean(row.get("bill_id"))
        if bill_number and bill_id and bill_number not in values:
            values[bill_number] = bill_id
    return values


def _build_po_line_to_bill_line_map(bills: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for bill in bills:
        if not isinstance(bill, dict):
            continue
        for line in bill.get("line_items") or []:
            if not isinstance(line, dict):
                continue
            po_line_id = _clean(line.get("purchaseorder_item_id"))
            bill_line_id = _clean(line.get("line_item_id"))
            if po_line_id and bill_line_id and po_line_id not in mapping:
                mapping[po_line_id] = bill_line_id
    return mapping


def _enrich_bill_payload_with_po_lines(
    *,
    remote_po: dict[str, Any],
    bill_payload: dict[str, Any],
) -> dict[str, Any]:
    purchaseorder_id = _clean(bill_payload.get("purchaseorder_id"))
    if not purchaseorder_id:
        return bill_payload

    po_lines = remote_po.get("line_items") or []
    if not isinstance(po_lines, list) or not po_lines:
        raise ValueError(f"Zoho PO {purchaseorder_id} has no line_items")

    line_items: list[dict[str, Any]] = []
    for line in po_lines:
        if not isinstance(line, dict):
            continue
        po_item_id = _clean(line.get("purchaseorder_item_id") or line.get("line_item_id"))
        qty_raw = line.get("quantity") or 0
        try:
            qty = int(float(qty_raw))
        except Exception:
            qty = 0
        if not po_item_id or qty <= 0:
            continue

        payload_line: dict[str, Any] = {
            "purchaseorder_item_id": po_item_id,
            "quantity": qty,
        }
        for key in ["item_id", "name", "description", "rate", "tax_id", "tds_tax_id", "location_id", "account_id"]:
            value = line.get(key)
            if value is not None and _clean(value):
                payload_line[key] = value

        line_items.append(payload_line)

    if not line_items:
        raise ValueError(f"Zoho PO {purchaseorder_id} produced no valid bill line_items")

    enriched = dict(bill_payload)
    enriched["line_items"] = line_items

    po_branch_id = _clean(remote_po.get("branch_id"))
    po_location_id = _clean(remote_po.get("location_id"))
    if po_branch_id:
        enriched["branch_id"] = po_branch_id
    if po_location_id:
        enriched["location_id"] = po_location_id
    return enriched


def _is_location_locked_bill_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "27523" in text or "location in this bill cannot be modified" in text


def _strip_bill_location_fields(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = {k: v for k, v in payload.items() if k not in {"location_id", "branch_id"}}
    line_items = payload.get("line_items")
    if isinstance(line_items, list):
        sanitized_lines: list[dict[str, Any]] = []
        for row in line_items:
            if isinstance(row, dict):
                sanitized_lines.append({k: v for k, v in row.items() if k not in {"location_id", "branch_id"}})
            else:
                sanitized_lines.append(row)
        sanitized["line_items"] = sanitized_lines
    return sanitized


async def _inventory_create_bill(client: ZohoClient, payload: dict[str, Any], *, debug: bool) -> dict[str, Any]:
    request_body = {"JSONString": json.dumps(payload)}
    if debug:
        print(
            "[bill-debug] request "
            f"{json.dumps({'method': 'POST', 'api': 'inventory', 'endpoint': '/bills', 'data': request_body}, ensure_ascii=False)}"
        )
    try:
        result = await client._request(
            "POST",
            "/bills",
            api="inventory",
            data=request_body,
        )
        if debug:
            print(f"[bill-debug] response {json.dumps(result, default=str, ensure_ascii=False)}")
        return result.get("bill", {}) or {}
    except Exception as exc:
        if debug:
            print(f"[bill-debug] error {json.dumps({'error': str(exc), 'payload': payload}, default=str, ensure_ascii=False)}")
        raise


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
    debug: bool,
    failure_log_path: Path,
) -> int:
    run_started_at_utc = _now_iso()
    _validate_csv_headers(receive_csv, {"PO Number", "Receive Number", "Receive Date", "Notes"})
    _validate_csv_headers(bill_csv, {"PurchaseOrder", "Bill Number", "Bill Date"})

    receive_scope = _build_receive_scope(_read_csv_rows(receive_csv))
    bill_scope = _build_bill_scope(_read_csv_rows(bill_csv))

    local_pos = await _load_local_pos(start_date, end_date, limit=limit, offset=offset)
    if not local_pos:
        print("No local purchase orders found in requested date range.")
        return 0

    print(
        f"Selected {len(local_pos)} local purchase orders with zoho_sync_status=DIRTY "
        f"in range {start_date.isoformat()}..{end_date.isoformat()} (dry_run={dry_run})"
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
    failures: list[dict[str, Any]] = []

    for idx, po in enumerate(local_pos, start=1):
        po_number = _clean(po.po_number)
        summary["po_processed"] += 1

        local_state = await _load_po_state(po.id)
        if local_state is None:
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] failed: local record missing at runtime")
            _record_failure(
                failures,
                po_id=po.id,
                po_number=po_number,
                stage="po_upload",
                error="local record missing at runtime",
            )
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

        try:
            await sync_po_outbound(
                po.id,
                allow_billed_unbill_rebill=False,
                enable_ebay_billing=False,
            )
        except Exception as exc:
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] PO upsert raised exception: {exc}")
            _record_failure(
                failures,
                po_id=po.id,
                po_number=po_number,
                stage="po_upload",
                error=f"sync_po_outbound exception: {exc}",
            )
            continue

        synced_state = await _load_po_state(po.id)
        sync_status = _clean((synced_state or {}).get("sync_status"))
        sync_error = _clean((synced_state or {}).get("sync_error"))
        if sync_status != "SYNCED":
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] PO upsert failed: status={sync_status or 'unknown'} error={sync_error}")
            _record_failure(
                failures,
                po_id=po.id,
                po_number=po_number,
                stage="po_upload",
                error=f"status={sync_status or 'unknown'} error={sync_error}",
            )
            continue

        summary["po_sync_ok"] += 1
        zoho_id = _clean((synced_state or {}).get("zoho_id"))
        currency_code = _clean((synced_state or {}).get("currency_code") or "USD")
        if not zoho_id:
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] PO upsert failed: local zoho_id is empty after sync")
            _record_failure(
                failures,
                po_id=po.id,
                po_number=po_number,
                stage="po_upload",
                error="local zoho_id is empty after sync",
            )
            continue

        try:
            full_po = await client.get_purchase_order(zoho_id)
        except Exception as exc:
            summary["po_sync_failed"] += 1
            print(f"[po {po.id} {po_number}] failed to fetch synced Zoho PO: {exc}")
            _record_failure(
                failures,
                po_id=po.id,
                po_number=po_number,
                stage="po_upload",
                error=f"failed to fetch synced Zoho PO: {exc}",
            )
            continue

        full_po_before_bill = full_po
        existing_bill_numbers = _existing_bill_numbers(full_po_before_bill)
        existing_bill_ids_by_number = _po_bill_id_map(full_po_before_bill)
        bill_details_by_number: dict[str, dict[str, Any]] = {}
        for bill_number, meta in sorted(bill_scope.get(po_number, {}).items()):
            if bill_number in existing_bill_numbers:
                summary["bill_skipped_existing"] += 1
                existing_bill_id = _clean(existing_bill_ids_by_number.get(bill_number))
                if existing_bill_id:
                    try:
                        bill_details_by_number[bill_number] = await client.get_bill(existing_bill_id)
                    except Exception as exc:
                        print(
                            f"[po {po.id} {po_number}] warning: failed to load existing bill detail "
                            f"({bill_number}, bill_id={existing_bill_id}): {exc}"
                        )
                continue
            payload = _build_bill_payload(
                full_po_before_bill,
                po_number=po_number,
                currency_code=currency_code or "USD",
                bill_number=bill_number,
                bill_date=_clean(meta.get("bill_date")),
            )
            if not payload:
                summary["bill_failed"] += 1
                print(f"[po {po.id} {po_number}] bill create skipped: invalid payload for {bill_number}")
                _record_failure(
                    failures,
                    po_id=po.id,
                    po_number=po_number,
                    stage="bill",
                    bill_number=bill_number,
                    error="invalid payload",
                )
                continue
            try:
                payload = _enrich_bill_payload_with_po_lines(
                    remote_po=full_po_before_bill,
                    bill_payload=payload,
                )
            except Exception as exc:
                summary["bill_failed"] += 1
                print(f"[po {po.id} {po_number}] bill create skipped: could_not_enrich_line_items ({bill_number}) error={exc}")
                _record_failure(
                    failures,
                    po_id=po.id,
                    po_number=po_number,
                    stage="bill",
                    bill_number=bill_number,
                    error=f"could_not_enrich_line_items: {exc}",
                )
                continue
            try:
                created_bill = await _inventory_create_bill(client, payload, debug=debug)
                summary["bill_created"] += 1
                existing_bill_numbers.add(bill_number)
                created_bill_id = _clean(created_bill.get("bill_id"))
                if created_bill_id:
                    existing_bill_ids_by_number[bill_number] = created_bill_id
                    try:
                        bill_details_by_number[bill_number] = await client.get_bill(created_bill_id)
                    except Exception:
                        bill_details_by_number[bill_number] = created_bill
            except Exception as exc:
                if _is_location_locked_bill_error(exc):
                    retry_payload = _strip_bill_location_fields(payload)
                    try:
                        created_bill = await _inventory_create_bill(client, retry_payload, debug=debug)
                        summary["bill_created"] += 1
                        existing_bill_numbers.add(bill_number)
                        created_bill_id = _clean(created_bill.get("bill_id"))
                        if created_bill_id:
                            existing_bill_ids_by_number[bill_number] = created_bill_id
                            try:
                                bill_details_by_number[bill_number] = await client.get_bill(created_bill_id)
                            except Exception:
                                bill_details_by_number[bill_number] = created_bill
                        continue
                    except Exception as retry_exc:
                        summary["bill_failed"] += 1
                        print(
                            f"[po {po.id} {po_number}] bill create failed after location-strip retry "
                            f"({bill_number}): {retry_exc}"
                        )
                        _record_failure(
                            failures,
                            po_id=po.id,
                            po_number=po_number,
                            stage="bill",
                            bill_number=bill_number,
                            error=f"failed after location-strip retry: {retry_exc}",
                        )
                        continue
                summary["bill_failed"] += 1
                print(f"[po {po.id} {po_number}] bill create failed ({bill_number}): {exc}")
                _record_failure(
                    failures,
                    po_id=po.id,
                    po_number=po_number,
                    stage="bill",
                    bill_number=bill_number,
                    error=str(exc),
                )

        try:
            full_po_after_bill = await client.get_purchase_order(zoho_id)
        except Exception:
            full_po_after_bill = full_po_before_bill

        bill_line_item_by_po_line_id = _build_po_line_to_bill_line_map(list(bill_details_by_number.values()))
        if bill_scope.get(po_number) and not bill_line_item_by_po_line_id:
            print(
                f"[po {po.id} {po_number}] warning: no bill_line_item_id mapping resolved from bill responses; "
                "receive creation will continue without bill_line_item_id"
            )

        existing_receive_numbers = _existing_receive_numbers(full_po_after_bill)
        for receive_number, meta in sorted(receive_scope.get(po_number, {}).items()):
            if receive_number in existing_receive_numbers:
                summary["receive_skipped_existing"] += 1
                continue
            payload = _build_receive_payload(
                full_po_after_bill,
                receive_number=receive_number,
                receive_date=_clean(meta.get("receive_date")),
                notes=_clean(meta.get("notes")),
                bill_line_item_by_po_line_id=bill_line_item_by_po_line_id,
            )
            if not payload:
                summary["receive_failed"] += 1
                print(f"[po {po.id} {po_number}] receive create skipped: invalid payload for {receive_number}")
                _record_failure(
                    failures,
                    po_id=po.id,
                    po_number=po_number,
                    stage="receive",
                    receive_number=receive_number,
                    error="invalid payload",
                )
                continue
            try:
                await _inventory_create_purchase_receive(client, payload, debug=debug)
                summary["receive_created"] += 1
                existing_receive_numbers.add(receive_number)
            except Exception as exc:
                summary["receive_failed"] += 1
                print(f"[po {po.id} {po_number}] receive create failed ({receive_number}): {exc}")
                _record_failure(
                    failures,
                    po_id=po.id,
                    po_number=po_number,
                    stage="receive",
                    receive_number=receive_number,
                    error=str(exc),
                )

        if progress_every > 0 and (idx % progress_every == 0):
            print(
                f"[progress] processed={idx}/{len(local_pos)} "
                f"synced={summary['po_sync_ok']} receive_created={summary['receive_created']} bill_created={summary['bill_created']}"
            )

    run_finished_at_utc = _now_iso()
    _write_failure_log(
        path=failure_log_path,
        run_started_at_utc=run_started_at_utc,
        run_finished_at_utc=run_finished_at_utc,
        start_date=start_date,
        end_date=end_date,
        dry_run=dry_run,
        limit=limit,
        offset=offset,
        summary=summary,
        failures=failures,
    )
    print(f"Failure report written to: {failure_log_path}")
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
    parser.add_argument("--debug", action="store_true", help="Enable verbose [bill-debug]/[receive-debug] payload logs")
    parser.add_argument("--progress-every", type=int, default=25, help="Print progress every N purchase orders")
    parser.add_argument("--limit", type=int, default=0, help="Max number of local purchase orders to process (0 = all)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N local purchase orders in date-range ordering")
    parser.add_argument("--failure-log", default=str(DEFAULT_FAILURE_LOG_PATH), help="Path to JSON failure report file written after each run")
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
            debug=bool(args.debug),
            failure_log_path=Path(args.failure_log),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
