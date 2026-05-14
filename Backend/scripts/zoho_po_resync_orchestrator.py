#!/usr/bin/env python
"""Orchestrate Zoho purchase-order Q1 resync flow with stage-based execution.

Stages:
- delete: CSV-scoped delete in strict order (payments -> bills -> receives).
- sync-dry-run: list local purchase orders in date window (paged by limit/offset).
- sync-apply: execute outbound PO sync (PO only; no eBay billing side-effects).
- reconcile-check: compare CSV-scoped IDs against Zoho-derived dependencies.
- reconcile-api: same as reconcile-check, then restore missing receives/bills/payments.

Safety:
- --start-date and --end-date are required.
- Default mode is dry-run. Use --apply to execute writes.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import noload, selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient
from app.integrations.zoho.sync_engine import sync_po_outbound
from app.models.purchasing import PurchaseOrder


STAGES = {"delete", "sync-dry-run", "sync-apply", "reconcile-check", "reconcile-api"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


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
        _trace(
            enabled,
            f"REQ method={method} api={api} endpoint={endpoint} params={json.dumps(params, separators=(',', ':'))}",
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


def _parse_iso(value: str | None, *, field_name: str) -> date:
    raw = _clean(value)
    if not raw:
        raise ValueError(f"{field_name} is required (YYYY-MM-DD)")
    try:
        return date.fromisoformat(raw)
    except Exception as exc:
        raise ValueError(f"Invalid {field_name}: {raw}; expected YYYY-MM-DD") from exc


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


def _in_range(value: Optional[date], start_date: date, end_date: date) -> bool:
    return value is not None and start_date <= value <= end_date


def _safe_float(value: str | None, default: float = 0.0) -> float:
    raw = _clean(value)
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _validate_csv_headers(path: Path, required_headers: set[str]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        found = set(reader.fieldnames or [])
    missing = sorted(required_headers - found)
    if missing:
        raise ValueError(f"CSV {path} missing required headers: {missing}")


@dataclass
class CsvScope:
    bill_ids: list[str]
    bill_id_by_number: dict[str, str]
    receive_ids: list[str]
    payment_rows: list[dict[str, str]]
    payment_refs: list[dict[str, str]]


@dataclass
class CsvScoped:
    bills_by_id: dict[str, list[dict[str, str]]]
    receives_by_id: dict[str, list[dict[str, str]]]
    payments_by_vendor_id: dict[str, dict[str, str]]


class BillIdResolver:
    """Resolve bill_id by bill number using CSV map first, API fallback second."""

    def __init__(
        self,
        *,
        client: ZohoClient,
        start_date: date,
        end_date: date,
        initial_map: dict[str, str],
        debug: bool,
    ) -> None:
        self.client = client
        self.start_date = start_date
        self.end_date = end_date
        self.debug = debug
        self._csv_map = {k: v for k, v in initial_map.items() if k and v}
        self._window_map: dict[str, str] = {}
        self._window_loaded = False

    async def _load_window_map(self) -> None:
        if self._window_loaded:
            return

        page = 1
        per_page = 200
        while True:
            rows = await self.client.list_bills(
                date_start=self.start_date.isoformat(),
                date_end=self.end_date.isoformat(),
                page=page,
                per_page=per_page,
            )
            if not rows:
                break
            for row in rows:
                bill_id = _clean(row.get("bill_id") or row.get("id"))
                bill_number = _clean(row.get("bill_number") or row.get("invoice_number"))
                if bill_id and bill_number and bill_number not in self._window_map:
                    self._window_map[bill_number] = bill_id
            if len(rows) < per_page:
                break
            page += 1

        self._window_loaded = True
        _debug(self.debug, f"Window bill map loaded: {len(self._window_map)} bill numbers")

    async def resolve(self, bill_number: str) -> str:
        normalized = _clean(bill_number)
        if not normalized:
            return ""
        if normalized in self._csv_map:
            return self._csv_map[normalized]
        if normalized in self._window_map:
            return self._window_map[normalized]

        await self._load_window_map()
        if normalized in self._window_map:
            return self._window_map[normalized]

        # Final fallback: broad lookup by page scan.
        page = 1
        per_page = 200
        max_pages = 50
        while page <= max_pages:
            rows = await self.client.list_bills(page=page, per_page=per_page)
            if not rows:
                break
            for row in rows:
                row_number = _clean(row.get("bill_number") or row.get("invoice_number"))
                row_id = _clean(row.get("bill_id") or row.get("id"))
                if row_number and row_id and row_number not in self._window_map:
                    self._window_map[row_number] = row_id
                if row_number == normalized and row_id:
                    return row_id
            if len(rows) < per_page:
                break
            page += 1
        return ""


def _build_csv_scope(
    *,
    bill_csv: Path,
    payment_csv: Path,
    receive_csv: Path,
    start_date: date,
    end_date: date,
) -> CsvScope:
    bill_ids: list[str] = []
    bill_id_seen: set[str] = set()
    bill_id_by_number: dict[str, str] = {}

    for row in _read_csv_rows(bill_csv):
        row_date = _parse_csv_date(row.get("Bill Date"))
        if not _in_range(row_date, start_date, end_date):
            continue
        bill_id = _clean(row.get("PayInvoice ID"))
        bill_number = _clean(row.get("Bill Number"))
        if bill_id and bill_id not in bill_id_seen:
            bill_id_seen.add(bill_id)
            bill_ids.append(bill_id)
        if bill_id and bill_number and bill_number not in bill_id_by_number:
            bill_id_by_number[bill_number] = bill_id

    receive_ids: list[str] = []
    receive_seen: set[str] = set()
    for row in _read_csv_rows(receive_csv):
        row_date = _parse_csv_date(row.get("Receive Date"))
        if not _in_range(row_date, start_date, end_date):
            continue
        receive_id = _clean(row.get("Purchase Receive ID"))
        if receive_id and receive_id not in receive_seen:
            receive_seen.add(receive_id)
            receive_ids.append(receive_id)

    payment_rows: list[dict[str, str]] = []
    for row in _read_csv_rows(payment_csv):
        row_date = _parse_csv_date(row.get("Date"))
        if _in_range(row_date, start_date, end_date):
            payment_rows.append(row)

    payment_refs: list[dict[str, str]] = []
    for row in payment_rows:
        payment_id = _clean(row.get("VendorPayment ID"))
        bill_payment_id = _clean(row.get("PIPayment ID"))
        bill_number = _clean(row.get("Bill Number"))
        if not bill_payment_id:
            continue
        payment_refs.append(
            {
                "vendor_payment_id": payment_id,
                "bill_payment_id": bill_payment_id,
                "bill_number": bill_number,
                "payment_number": _clean(row.get("Payment Number")),
                "payment_date": _clean(row.get("Date")),
            }
        )

    return CsvScope(
        bill_ids=bill_ids,
        bill_id_by_number=bill_id_by_number,
        receive_ids=receive_ids,
        payment_rows=payment_rows,
        payment_refs=payment_refs,
    )


async def _delete_stage(
    *,
    client: ZohoClient,
    scope: CsvScope,
    start_date: date,
    end_date: date,
    dry_run: bool,
    progress_every: int,
    debug: bool,
) -> dict[str, Any]:
    resolver = BillIdResolver(
        client=client,
        start_date=start_date,
        end_date=end_date,
        initial_map=scope.bill_id_by_number,
        debug=debug,
    )

    unresolved_payment_rows: list[dict[str, str]] = []
    payment_targets: list[dict[str, str]] = []
    for row in scope.payment_refs:
        bill_number = _clean(row.get("bill_number"))
        bill_id = await resolver.resolve(bill_number)
        if not bill_id:
            unresolved_payment_rows.append(
                {
                    "vendor_payment_id": _clean(row.get("vendor_payment_id")),
                    "bill_payment_id": _clean(row.get("bill_payment_id")),
                    "bill_number": bill_number,
                    "payment_number": _clean(row.get("payment_number")),
                    "reason": "bill_id_not_resolved",
                }
            )
            continue
        payment_targets.append(
            {
                **row,
                "bill_id": bill_id,
            }
        )

    payment_deleted: list[dict[str, str]] = []
    payment_failed: list[dict[str, str]] = []
    total_payments = len(payment_targets)
    for idx, row in enumerate(payment_targets, start=1):
        bill_id = _clean(row.get("bill_id"))
        bill_payment_id = _clean(row.get("bill_payment_id"))
        if dry_run:
            payment_deleted.append(row)
        else:
            try:
                await client.delete_bill_payment(bill_id=bill_id, bill_payment_id=bill_payment_id)
                payment_deleted.append(row)
            except Exception as exc:
                payment_failed.append(
                    {
                        **{k: _clean(v) for k, v in row.items()},
                        "error": str(exc),
                    }
                )
        if progress_every > 0 and idx % progress_every == 0:
            print(f"Stage delete/payments: {idx}/{total_payments}")

    bill_deleted: list[str] = []
    bill_failed: list[dict[str, str]] = []
    total_bills = len(scope.bill_ids)
    for idx, bill_id in enumerate(scope.bill_ids, start=1):
        if dry_run:
            bill_deleted.append(bill_id)
        else:
            try:
                await client.delete_bill(bill_id)
                bill_deleted.append(bill_id)
            except Exception as exc:
                bill_failed.append({"bill_id": bill_id, "error": str(exc)})
        if progress_every > 0 and idx % progress_every == 0:
            print(f"Stage delete/bills: {idx}/{total_bills}")

    receive_deleted: list[str] = []
    receive_failed: list[dict[str, str]] = []
    total_receives = len(scope.receive_ids)
    for idx, receive_id in enumerate(scope.receive_ids, start=1):
        if dry_run:
            receive_deleted.append(receive_id)
        else:
            try:
                await client.delete_purchase_receive(receive_id)
                receive_deleted.append(receive_id)
            except Exception as exc:
                receive_failed.append({"receive_id": receive_id, "error": str(exc)})
        if progress_every > 0 and idx % progress_every == 0:
            print(f"Stage delete/receives: {idx}/{total_receives}")

    return {
        "scope": {
            "bill_ids": len(scope.bill_ids),
            "receive_ids": len(scope.receive_ids),
            "payment_rows_in_window": len(scope.payment_rows),
            "payment_rows_with_bill_payment_id": len(scope.payment_refs),
        },
        "unresolved_payment_rows": unresolved_payment_rows,
        "delete_results": {
            "payments": {
                "attempted": len(payment_targets),
                "deleted_count": len(payment_deleted),
                "failed_count": len(payment_failed),
                "failed": payment_failed,
                "deleted_labels": payment_deleted,
            },
            "bills": {
                "attempted": len(scope.bill_ids),
                "deleted_count": len(bill_deleted),
                "failed_count": len(bill_failed),
                "failed": bill_failed,
                "deleted_ids": bill_deleted,
            },
            "receives": {
                "attempted": len(scope.receive_ids),
                "deleted_count": len(receive_deleted),
                "failed_count": len(receive_failed),
                "failed": receive_failed,
                "deleted_ids": receive_deleted,
            },
        },
        "notes": {
            "order": ["payments", "bills", "receives"],
            "dry_run": dry_run,
        },
    }


async def _load_local_pos(
    *,
    start_date: date,
    end_date: date,
    limit: int,
    offset: int,
) -> list[PurchaseOrder]:
    async with async_session_factory() as db:
        stmt = (
            select(PurchaseOrder)
            .options(
                noload(PurchaseOrder.vendor),
                selectinload(PurchaseOrder.items),
            )
            .where(PurchaseOrder.order_date >= start_date, PurchaseOrder.order_date <= end_date)
            .order_by(PurchaseOrder.order_date.asc(), PurchaseOrder.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return (await db.execute(stmt)).scalars().all()


async def _sync_dry_run_stage(
    *,
    start_date: date,
    end_date: date,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    pos = await _load_local_pos(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    candidates: list[dict[str, Any]] = []
    for po in pos:
        item_count = len(po.items or [])
        predicted = "update" if _clean(po.zoho_id) else "create_or_relink"
        if item_count <= 0:
            predicted = "skip_no_items"
        candidates.append(
            {
                "id": po.id,
                "po_number": po.po_number,
                "order_date": po.order_date.isoformat(),
                "zoho_id": _clean(po.zoho_id),
                "item_count": item_count,
                "predicted_action": predicted,
            }
        )

    return {
        "counts": {
            "selected": len(pos),
            "ready_for_sync": len([c for c in candidates if c["predicted_action"] != "skip_no_items"]),
            "skipped_no_items": len([c for c in candidates if c["predicted_action"] == "skip_no_items"]),
        },
        "candidates": candidates,
        "notes": {
            "dry_run": True,
            "sync_mode": "PO-only",
            "allow_billed_unbill_rebill": False,
            "enable_ebay_billing": False,
        },
    }


async def _sync_apply_stage(
    *,
    start_date: date,
    end_date: date,
    limit: int,
    offset: int,
    progress_every: int,
) -> dict[str, Any]:
    pos = await _load_local_pos(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )

    attempted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    total = len(pos)
    for idx, po in enumerate(pos, start=1):
        item_count = len(po.items or [])
        if item_count <= 0:
            skipped.append(
                {
                    "id": po.id,
                    "po_number": po.po_number,
                    "reason": "no_items",
                }
            )
            continue

        try:
            await sync_po_outbound(po.id, False, False)
            attempted.append(
                {
                    "id": po.id,
                    "po_number": po.po_number,
                }
            )
        except Exception as exc:
            failed.append(
                {
                    "id": po.id,
                    "po_number": po.po_number,
                    "error": str(exc),
                }
            )

        if progress_every > 0 and idx % progress_every == 0:
            print(f"Stage sync-apply: {idx}/{total}")

    return {
        "counts": {
            "selected": len(pos),
            "attempted": len(attempted),
            "failed": len(failed),
            "skipped_no_items": len(skipped),
        },
        "applied": attempted,
        "failed": failed,
        "skipped": skipped,
        "notes": {
            "sync_mode": "PO-only",
            "allow_billed_unbill_rebill": False,
            "enable_ebay_billing": False,
        },
    }


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


async def _fetch_target_pos(client: ZohoClient, start_date: date, end_date: date) -> list[dict[str, Any]]:
    all_pos: list[dict[str, Any]] = []
    page = 1
    per_page = 200
    while True:
        chunk = await client.list_purchase_orders(page=page, per_page=per_page, filter_by="Status.All")
        if not chunk:
            break
        all_pos.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1

    return [po for po in all_pos if _in_range(_extract_po_date(po), start_date, end_date)]


async def _collect_zoho_dependencies(
    client: ZohoClient,
    pos: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    po_detail_by_number: dict[str, dict[str, Any]] = {}
    bills_by_id: dict[str, dict[str, Any]] = {}
    receives_by_id: dict[str, dict[str, Any]] = {}
    payments_by_vendor_id: dict[str, dict[str, Any]] = {}
    bill_number_to_id: dict[str, str] = {}

    for po in pos:
        po_id = _extract_po_id(po)
        po_number = _extract_po_number(po)
        if not po_id:
            continue

        full_po = await client.get_purchase_order(po_id)
        po_detail_by_number[po_number] = full_po

        for receive in full_po.get("purchasereceives") or full_po.get("receives") or []:
            if not isinstance(receive, dict):
                continue
            receive_id = _clean(receive.get("receive_id") or receive.get("purchase_receive_id") or receive.get("purchasereceive_id"))
            if receive_id:
                receives_by_id[receive_id] = {
                    **receive,
                    "purchaseorder_id": po_id,
                    "purchaseorder_number": po_number,
                }

        for bill in full_po.get("bills") or []:
            if not isinstance(bill, dict):
                continue
            bill_id = _clean(bill.get("bill_id") or bill.get("id"))
            if not bill_id:
                continue

            bill_full = await client.get_bill(bill_id)
            bills_by_id[bill_id] = bill_full
            bill_number = _clean(bill_full.get("bill_number") or bill.get("bill_number"))
            if bill_number:
                bill_number_to_id[bill_number] = bill_id

            for payment in bill_full.get("payments") or []:
                if not isinstance(payment, dict):
                    continue
                payment_id = _clean(payment.get("payment_id"))
                if payment_id:
                    payments_by_vendor_id[payment_id] = {
                        **payment,
                        "bill_id": bill_id,
                        "bill_number": bill_number,
                        "vendor_id": _clean(bill_full.get("vendor_id")),
                    }

    return po_detail_by_number, bills_by_id, receives_by_id, payments_by_vendor_id, bill_number_to_id


def _scope_csv_rows(
    bill_csv: Path,
    receive_csv: Path,
    payment_csv: Path,
    target_po_numbers: set[str],
) -> CsvScoped:
    bills_by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    receives_by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    payments_by_vendor_id: dict[str, dict[str, str]] = {}

    bill_number_whitelist: set[str] = set()

    for row in _read_csv_rows(bill_csv):
        po_number = _clean(row.get("PurchaseOrder") or row.get("Purchase Order Number"))
        if po_number not in target_po_numbers:
            continue
        bill_id = _clean(row.get("PayInvoice ID"))
        if bill_id:
            bills_by_id[bill_id].append(row)
        bill_number = _clean(row.get("Bill Number"))
        if bill_number:
            bill_number_whitelist.add(bill_number)

    for row in _read_csv_rows(receive_csv):
        po_number = _clean(row.get("PO Number"))
        if po_number not in target_po_numbers:
            continue
        receive_id = _clean(row.get("Purchase Receive ID"))
        if receive_id:
            receives_by_id[receive_id].append(row)
        bill_number = _clean(row.get("Bill Number"))
        if bill_number:
            bill_number_whitelist.add(bill_number)

    for row in _read_csv_rows(payment_csv):
        bill_number = _clean(row.get("Bill Number"))
        if bill_number and bill_number not in bill_number_whitelist:
            continue
        vendor_payment_id = _clean(row.get("VendorPayment ID"))
        if vendor_payment_id:
            payments_by_vendor_id[vendor_payment_id] = row

    return CsvScoped(
        bills_by_id=dict(bills_by_id),
        receives_by_id=dict(receives_by_id),
        payments_by_vendor_id=payments_by_vendor_id,
    )


def _po_line_item_maps(full_po: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_sku: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for li in full_po.get("line_items") or []:
        if not isinstance(li, dict):
            continue
        sku = _clean(li.get("sku"))
        name = _clean(li.get("name"))
        if sku and sku not in by_sku:
            by_sku[sku] = li
        if name and name not in by_name:
            by_name[name] = li
    return by_sku, by_name


def _build_receive_payload(
    receive_rows: list[dict[str, str]],
    full_po: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if not receive_rows:
        return None

    po_id = _clean(full_po.get("purchaseorder_id"))
    if not po_id:
        return None

    by_sku, by_name = _po_line_item_maps(full_po)
    line_items: list[dict[str, Any]] = []
    for row in receive_rows:
        sku = _clean(row.get("SKU"))
        item_name = _clean(row.get("Item Name"))
        qty = _safe_float(row.get("Quantity Received"), 0.0)
        if qty <= 0:
            continue
        source = by_sku.get(sku) or by_name.get(item_name)
        item_id = _clean((source or {}).get("item_id"))
        if not item_id:
            continue
        line_items.append({"item_id": item_id, "quantity": qty, "quantity_received": qty})

    if not line_items:
        return None

    return {
        "purchaseorder_id": po_id,
        "receive_number": _clean(receive_rows[0].get("Receive Number")),
        "date": _clean(receive_rows[0].get("Receive Date")),
        "notes": _clean(receive_rows[0].get("Notes")),
        "line_items": line_items,
    }


def _build_bill_payload(
    bill_rows: list[dict[str, str]],
    full_po: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if not bill_rows:
        return None

    po_id = _clean(full_po.get("purchaseorder_id"))
    vendor_id = _clean(full_po.get("vendor_id"))
    if not po_id or not vendor_id:
        return None

    by_sku, by_name = _po_line_item_maps(full_po)
    sample = bill_rows[0]
    line_items: list[dict[str, Any]] = []
    for row in bill_rows:
        quantity = _safe_float(row.get("Quantity"), 0.0)
        rate = _safe_float(row.get("Rate"), 0.0)
        if quantity <= 0:
            continue

        item_id = _clean(row.get("Product ID"))
        if not item_id:
            sku = _clean(row.get("SKU"))
            item_name = _clean(row.get("Item Name"))
            source = by_sku.get(sku) or by_name.get(item_name)
            item_id = _clean((source or {}).get("item_id"))
        if not item_id:
            continue

        line_items.append(
            {
                "item_id": item_id,
                "quantity": quantity,
                "rate": rate,
                "name": _clean(row.get("Item Name")),
                "description": _clean(row.get("Description")),
            }
        )

    if not line_items:
        return None

    bill_date = _clean(sample.get("Bill Date"))
    return {
        "purchaseorder_id": po_id,
        "vendor_id": vendor_id,
        "bill_number": _clean(sample.get("Bill Number")),
        "date": bill_date,
        "due_date": _clean(sample.get("Due Date")) or bill_date,
        "line_items": line_items,
    }


def _build_vendor_payment_payload(
    payment_row: dict[str, str],
    vendor_id: str,
    bill_id: str,
) -> Optional[dict[str, Any]]:
    payment_date = _clean(payment_row.get("Date"))
    amount = _safe_float(payment_row.get("Amount"), 0.0)
    if not vendor_id or not bill_id or amount <= 0:
        return None

    payload = {
        "vendor_id": vendor_id,
        "date": payment_date,
        "payment_mode": _clean(payment_row.get("Mode")) or "Cash",
        "amount": amount,
        "reference_number": _clean(payment_row.get("Reference Number")),
        "description": _clean(payment_row.get("Description")),
        "bills": [{"bill_id": bill_id, "amount_applied": amount}],
    }
    paid_through = _clean(payment_row.get("Paid Through"))
    if paid_through:
        payload["paid_through_account_name"] = paid_through
    return payload


def _mismatch(csv_ids: set[str], zoho_ids: set[str]) -> dict[str, list[str]]:
    return {
        "csv_missing_in_zoho": sorted(csv_ids - zoho_ids),
        "zoho_missing_in_csv": sorted(zoho_ids - csv_ids),
    }


async def _reconcile_stage(
    *,
    client: ZohoClient,
    bill_csv: Path,
    receive_csv: Path,
    payment_csv: Path,
    start_date: date,
    end_date: date,
    apply_restore: bool,
) -> dict[str, Any]:
    target_pos = await _fetch_target_pos(client, start_date, end_date)
    target_po_numbers = {_extract_po_number(po) for po in target_pos if _extract_po_number(po)}

    po_detail_by_number, zoho_bills, zoho_receives, zoho_payments, bill_number_to_id = await _collect_zoho_dependencies(
        client,
        target_pos,
    )

    csv_scoped = _scope_csv_rows(
        bill_csv=bill_csv,
        receive_csv=receive_csv,
        payment_csv=payment_csv,
        target_po_numbers=target_po_numbers,
    )

    missing_bill_ids = sorted(set(csv_scoped.bills_by_id.keys()) - set(zoho_bills.keys()))
    missing_receive_ids = sorted(set(csv_scoped.receives_by_id.keys()) - set(zoho_receives.keys()))
    missing_payment_vendor_ids = sorted(set(csv_scoped.payments_by_vendor_id.keys()) - set(zoho_payments.keys()))

    restore_results: dict[str, Any] = {
        "bills": {"attempted": 0, "restored": 0, "failed": []},
        "receives": {"attempted": 0, "restored": 0, "failed": []},
        "payments": {"attempted": 0, "restored": 0, "failed": []},
    }
    created_bill_id_by_number: dict[str, str] = {}
    vendor_id_by_bill_number: dict[str, str] = {}

    if apply_restore:
        for receive_id in missing_receive_ids:
            rows = csv_scoped.receives_by_id.get(receive_id) or []
            if not rows:
                continue
            po_number = _clean(rows[0].get("PO Number"))
            full_po = po_detail_by_number.get(po_number)
            restore_results["receives"]["attempted"] += 1
            if not full_po:
                restore_results["receives"]["failed"].append({"receive_id": receive_id, "error": f"PO not found: {po_number}"})
                continue

            payload = _build_receive_payload(rows, full_po)
            if not payload:
                restore_results["receives"]["failed"].append({"receive_id": receive_id, "error": "Could not build receive payload"})
                continue

            try:
                await client.create_purchase_receive(payload)
                restore_results["receives"]["restored"] += 1
            except Exception as exc:
                restore_results["receives"]["failed"].append({"receive_id": receive_id, "error": str(exc)})

        for bill_id in missing_bill_ids:
            rows = csv_scoped.bills_by_id.get(bill_id) or []
            if not rows:
                continue
            po_number = _clean(rows[0].get("PurchaseOrder") or rows[0].get("Purchase Order Number"))
            bill_number = _clean(rows[0].get("Bill Number"))
            full_po = po_detail_by_number.get(po_number)
            restore_results["bills"]["attempted"] += 1
            if not full_po:
                restore_results["bills"]["failed"].append({"bill_id": bill_id, "error": f"PO not found: {po_number}"})
                continue

            payload = _build_bill_payload(rows, full_po)
            if not payload:
                restore_results["bills"]["failed"].append({"bill_id": bill_id, "error": "Could not build bill payload"})
                continue

            vendor_id = _clean(payload.get("vendor_id"))
            if bill_number and vendor_id:
                vendor_id_by_bill_number[bill_number] = vendor_id

            try:
                created = await client.create_bill(payload)
                created_id = _clean(created.get("bill_id"))
                if bill_number and created_id:
                    created_bill_id_by_number[bill_number] = created_id
                restore_results["bills"]["restored"] += 1
            except Exception as exc:
                restore_results["bills"]["failed"].append({"bill_id": bill_id, "error": str(exc)})

        for vendor_payment_id in missing_payment_vendor_ids:
            row = csv_scoped.payments_by_vendor_id.get(vendor_payment_id)
            if not row:
                continue
            bill_number = _clean(row.get("Bill Number"))
            bill_id = bill_number_to_id.get(bill_number) or created_bill_id_by_number.get(bill_number, "")
            vendor_id = vendor_id_by_bill_number.get(bill_number, "")
            if not vendor_id and bill_id and bill_id in zoho_bills:
                vendor_id = _clean(zoho_bills[bill_id].get("vendor_id"))
            restore_results["payments"]["attempted"] += 1

            payload = _build_vendor_payment_payload(row, vendor_id=vendor_id, bill_id=bill_id)
            if not payload:
                restore_results["payments"]["failed"].append(
                    {
                        "vendor_payment_id": vendor_payment_id,
                        "error": "Could not build vendor payment payload (missing bill/vendor mapping)",
                    }
                )
                continue

            try:
                await client.create_vendor_payment(payload)
                restore_results["payments"]["restored"] += 1
            except Exception as exc:
                restore_results["payments"]["failed"].append({"vendor_payment_id": vendor_payment_id, "error": str(exc)})

    mismatches = {
        "bills": _mismatch(set(csv_scoped.bills_by_id.keys()), set(zoho_bills.keys())),
        "receives": _mismatch(set(csv_scoped.receives_by_id.keys()), set(zoho_receives.keys())),
        "payments_by_vendor_payment_id": _mismatch(set(csv_scoped.payments_by_vendor_id.keys()), set(zoho_payments.keys())),
    }

    return {
        "counts": {
            "target_purchase_orders": len(target_pos),
            "target_purchase_order_numbers": len(target_po_numbers),
            "zoho_bills": len(zoho_bills),
            "zoho_receives": len(zoho_receives),
            "zoho_vendor_payments": len(zoho_payments),
            "csv_scoped_bills": len(csv_scoped.bills_by_id),
            "csv_scoped_receives": len(csv_scoped.receives_by_id),
            "csv_scoped_vendor_payments": len(csv_scoped.payments_by_vendor_id),
        },
        "mismatches": mismatches,
        "missing_in_zoho": {
            "bill_ids": missing_bill_ids,
            "receive_ids": missing_receive_ids,
            "vendor_payment_ids": missing_payment_vendor_ids,
        },
        "restore_results": restore_results,
        "notes": {
            "mode": "reconcile-api" if apply_restore else "reconcile-check",
            "manual_import_first": True,
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Zoho purchase-order resync orchestrator")
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--bill-csv", default=str(PROJECT_ROOT / "misc" / "Bill.csv"))
    parser.add_argument("--payment-csv", default=str(PROJECT_ROOT / "misc" / "Vendor_Payment.csv"))
    parser.add_argument("--receive-csv", default=str(PROJECT_ROOT / "misc" / "Purchase_Receive.csv"))
    parser.add_argument("--limit", type=int, default=100, help="Batch size for sync stages")
    parser.add_argument("--offset", type=int, default=0, help="Pagination offset for sync stages")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--trace-api", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Force dry-run mode")
    parser.add_argument("--apply", action="store_true", help="Execute writes (default is dry-run)")
    parser.add_argument(
        "--report-path",
        default=str(PROJECT_ROOT / "scripts" / "zoho_po_resync_orchestrator_report.json"),
        help="Output JSON report path",
    )
    args = parser.parse_args()

    start_date = _parse_iso(args.start_date, field_name="start-date")
    end_date = _parse_iso(args.end_date, field_name="end-date")
    if end_date < start_date:
        raise ValueError("end-date must be >= start-date")

    if args.limit <= 0:
        raise ValueError("limit must be > 0")
    if args.offset < 0:
        raise ValueError("offset must be >= 0")

    bill_csv = Path(args.bill_csv)
    payment_csv = Path(args.payment_csv)
    receive_csv = Path(args.receive_csv)
    report_path = Path(args.report_path)

    for csv_path in (bill_csv, payment_csv, receive_csv):
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")

    # Validate minimum schema required by all stages.
    _validate_csv_headers(bill_csv, {"Bill Date", "PayInvoice ID", "Bill Number", "PurchaseOrder"})
    _validate_csv_headers(payment_csv, {"Date", "VendorPayment ID", "PIPayment ID", "Bill Number"})
    _validate_csv_headers(receive_csv, {"Receive Date", "Purchase Receive ID", "PO Number", "Bill Number"})

    if args.apply and args.dry_run:
        raise ValueError("Use either --apply or --dry-run, not both")
    dry_run = True if args.dry_run else (not bool(args.apply))
    client = ZohoClient()
    _install_api_trace(client, enabled=bool(args.trace_api))

    _debug(args.debug, f"stage={args.stage} dry_run={dry_run} window={start_date}..{end_date}")
    _debug(args.debug, f"csv bill={bill_csv} payment={payment_csv} receive={receive_csv}")
    _debug(args.debug, f"org={client.organization_id}")

    stage_result: dict[str, Any]
    if args.stage == "delete":
        scope = _build_csv_scope(
            bill_csv=bill_csv,
            payment_csv=payment_csv,
            receive_csv=receive_csv,
            start_date=start_date,
            end_date=end_date,
        )
        stage_result = await _delete_stage(
            client=client,
            scope=scope,
            start_date=start_date,
            end_date=end_date,
            dry_run=dry_run,
            progress_every=max(args.progress_every, 0),
            debug=bool(args.debug),
        )
    elif args.stage == "sync-dry-run":
        stage_result = await _sync_dry_run_stage(
            start_date=start_date,
            end_date=end_date,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.stage == "sync-apply":
        if dry_run:
            raise ValueError("sync-apply requires --apply")
        stage_result = await _sync_apply_stage(
            start_date=start_date,
            end_date=end_date,
            limit=args.limit,
            offset=args.offset,
            progress_every=max(args.progress_every, 0),
        )
    elif args.stage == "reconcile-check":
        stage_result = await _reconcile_stage(
            client=client,
            bill_csv=bill_csv,
            receive_csv=receive_csv,
            payment_csv=payment_csv,
            start_date=start_date,
            end_date=end_date,
            apply_restore=False,
        )
    elif args.stage == "reconcile-api":
        if dry_run:
            raise ValueError("reconcile-api requires --apply")
        stage_result = await _reconcile_stage(
            client=client,
            bill_csv=bill_csv,
            receive_csv=receive_csv,
            payment_csv=payment_csv,
            start_date=start_date,
            end_date=end_date,
            apply_restore=True,
        )
    else:
        raise ValueError(f"Unsupported stage: {args.stage}")

    report = {
        "stage": args.stage,
        "window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "controls": {
            "dry_run": dry_run,
            "apply": bool(args.apply),
            "limit": args.limit,
            "offset": args.offset,
            "progress_every": args.progress_every,
            "trace_api": bool(args.trace_api),
        },
        "paths": {
            "bill_csv": str(bill_csv),
            "payment_csv": str(payment_csv),
            "receive_csv": str(receive_csv),
            "report_path": str(report_path),
        },
        "result": stage_result,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Done.")
    print(f"Stage: {args.stage}")
    print(f"Report written to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
