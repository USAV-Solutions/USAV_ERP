#!/usr/bin/env python
"""Sequentially delete Zoho purchasing dependencies for a purchase-date range.

Flow is purchase anchored:
1) Fetch Zoho purchase orders in the input period.
2) From those purchases, derive attached receives and bills.
3) From those bills, derive attached bill payments.
4) Compare derived IDs with three CSV exports.
5) Delete in strict order: payments -> bills -> receives.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.integrations.zoho.client import ZohoClient


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}")


def _trace_api_call(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[api] {message}")


def _safe_json_compact(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        return str(value)


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

        _trace_api_call(
            enabled,
            (
                f"REQ method={method} api={api} endpoint={endpoint} "
                f"params={_safe_json_compact(params)} payload_mode={payload_mode}"
            ),
        )

        try:
            result = await original_request(method, endpoint, api=api, **kwargs)
        except Exception as exc:
            _trace_api_call(enabled, f"ERR method={method} api={api} endpoint={endpoint} error={exc}")
            raise

        keys = sorted(list(result.keys())) if isinstance(result, dict) else []
        counts: dict[str, int] = {}
        if isinstance(result, dict):
            for key in ("purchaseorders", "purchase_order", "purchase_receives", "purchasereceives", "bills", "bill", "payments"):
                value = result.get(key)
                if isinstance(value, list):
                    counts[key] = len(value)
                elif isinstance(value, dict):
                    counts[key] = 1

        _trace_api_call(
            enabled,
            (
                f"RES method={method} api={api} endpoint={endpoint} "
                f"keys={_safe_json_compact(keys)} counts={_safe_json_compact(counts)}"
            ),
        )
        return result

    client._request = traced_request  # type: ignore[method-assign]


def _parse_iso_date(value: str | None) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    return date.fromisoformat(raw)


def _parse_csv_date(value: str | None) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _in_range(value: Optional[date], start: date, end: date) -> bool:
    if value is None:
        return False
    return start <= value <= end


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@dataclass
class CsvUniverse:
    po_numbers: set[str]
    bill_ids: set[str]
    bill_numbers: set[str]
    payment_vendor_ids: set[str]
    payment_bill_payment_ids: set[str]
    receive_ids: set[str]


def _build_csv_universe_for_purchases(
    *,
    bill_csv: Path,
    payment_csv: Path,
    receive_csv: Path,
    target_po_numbers: set[str],
) -> CsvUniverse:
    po_numbers: set[str] = set()
    bill_ids: set[str] = set()
    bill_numbers: set[str] = set()
    payment_vendor_ids: set[str] = set()
    payment_bill_payment_ids: set[str] = set()
    receive_ids: set[str] = set()

    normalized_target_po_numbers = {str(v or "").strip() for v in target_po_numbers if str(v or "").strip()}

    if not normalized_target_po_numbers:
        return CsvUniverse(
            po_numbers=po_numbers,
            bill_ids=bill_ids,
            bill_numbers=bill_numbers,
            payment_vendor_ids=payment_vendor_ids,
            payment_bill_payment_ids=payment_bill_payment_ids,
            receive_ids=receive_ids,
        )

    for row in _read_csv_rows(bill_csv):
        po_number = _clean_id(row.get("PurchaseOrder") or row.get("Purchase Order Number"))
        if po_number not in normalized_target_po_numbers:
            continue

        po_numbers.add(po_number)

        bill_id = _clean_id(row.get("PayInvoice ID"))
        bill_number = _clean_id(row.get("Bill Number"))

        if bill_id:
            bill_ids.add(bill_id)
        if bill_number:
            bill_numbers.add(bill_number)

    receive_bill_numbers: set[str] = set()
    for row in _read_csv_rows(receive_csv):
        po_number = _clean_id(row.get("PO Number"))
        if po_number not in normalized_target_po_numbers:
            continue

        po_numbers.add(po_number)

        receive_id = _clean_id(row.get("Purchase Receive ID"))
        receive_bill_number = _clean_id(row.get("Bill Number"))
        if receive_id:
            receive_ids.add(receive_id)
        if receive_bill_number:
            receive_bill_numbers.add(receive_bill_number)

    target_bill_numbers = bill_numbers | receive_bill_numbers

    for row in _read_csv_rows(payment_csv):
        bill_number = _clean_id(row.get("Bill Number"))
        if bill_number and bill_number not in target_bill_numbers:
            continue

        vendor_payment_id = _clean_id(row.get("VendorPayment ID"))
        bill_payment_id = _clean_id(row.get("PIPayment ID"))

        if vendor_payment_id:
            payment_vendor_ids.add(vendor_payment_id)
        if bill_payment_id:
            payment_bill_payment_ids.add(bill_payment_id)

    return CsvUniverse(
        po_numbers=po_numbers,
        bill_ids=bill_ids,
        bill_numbers=bill_numbers,
        payment_vendor_ids=payment_vendor_ids,
        payment_bill_payment_ids=payment_bill_payment_ids,
        receive_ids=receive_ids,
    )


def _extract_po_date(po: dict[str, Any]) -> Optional[date]:
    for key in ("date", "purchaseorder_date", "purchase_order_date", "order_date"):
        parsed = _parse_csv_date(_clean_id(po.get(key)))
        if parsed is not None:
            return parsed
    return None


def _extract_po_number(po: dict[str, Any]) -> str:
    return _clean_id(
        po.get("purchaseorder_number")
        or po.get("purchase_order_number")
        or po.get("po_number")
        or po.get("purchaseorder")
    )


def _extract_po_id(po: dict[str, Any]) -> str:
    return _clean_id(po.get("purchaseorder_id") or po.get("purchase_order_id") or po.get("id"))


def _extract_po_status(po: dict[str, Any]) -> str:
    return _clean_id(po.get("status") or po.get("purchaseorder_status") or po.get("order_status"))


async def _fetch_target_purchase_orders(
    client: ZohoClient,
    start_date: date,
    end_date: date,
    debug: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_pos: list[dict[str, Any]] = []
    page = 1
    per_page = 200
    while True:
        chunk = await client.list_purchase_orders(
            page=page,
            per_page=per_page,
            filter_by="Status.All",
        )
        if not chunk:
            break
        all_pos.extend(chunk)
        _debug(debug, f"Fetched purchaseorders page={page} count={len(chunk)}")
        if len(chunk) < per_page:
            break
        page += 1

    diagnostics: dict[str, Any] = {
        "total_fetched": len(all_pos),
        "dated_in_range": 0,
        "dated_outside_range": 0,
        "missing_or_unparsed_date": 0,
        "min_po_date": None,
        "max_po_date": None,
        "sample_first_5": [],
        "sample_near_window": [],
    }

    target: list[dict[str, Any]] = []
    parsed_dates: list[date] = []
    near_window: list[tuple[date, dict[str, Any]]] = []

    for po in all_pos:
        po_date = _extract_po_date(po)
        po_number = _extract_po_number(po)
        po_id = _extract_po_id(po)

        if len(diagnostics["sample_first_5"]) < 5:
            diagnostics["sample_first_5"].append(
                {
                    "purchaseorder_id": po_id,
                    "purchaseorder_number": po_number,
                    "status": _extract_po_status(po),
                    "raw_date_keys": {
                        "date": _clean_id(po.get("date")),
                        "purchaseorder_date": _clean_id(po.get("purchaseorder_date")),
                        "purchase_order_date": _clean_id(po.get("purchase_order_date")),
                        "order_date": _clean_id(po.get("order_date")),
                    },
                    "parsed_date": po_date.isoformat() if po_date else None,
                }
            )

        if po_date is None:
            diagnostics["missing_or_unparsed_date"] += 1
            continue

        parsed_dates.append(po_date)
        near_window.append((po_date, po))

        if _in_range(po_date, start_date, end_date):
            diagnostics["dated_in_range"] += 1
            target.append(po)
        else:
            diagnostics["dated_outside_range"] += 1

    if parsed_dates:
        diagnostics["min_po_date"] = min(parsed_dates).isoformat()
        diagnostics["max_po_date"] = max(parsed_dates).isoformat()

        # Show the nearest records around the requested date window for quick triage.
        near_window_sorted = sorted(near_window, key=lambda x: x[0])
        window_center = start_date

        nearest = sorted(
            near_window_sorted,
            key=lambda x: abs((x[0] - window_center).days),
        )[:10]
        diagnostics["sample_near_window"] = [
            {
                "purchaseorder_id": _extract_po_id(po),
                "purchaseorder_number": _extract_po_number(po),
                "status": _extract_po_status(po),
                "parsed_date": po_date.isoformat(),
            }
            for po_date, po in nearest
        ]

    if debug:
        for po in target:
            _debug(
                True,
                (
                    "Selected PO "
                    f"id={_extract_po_id(po)} number={_extract_po_number(po)} "
                    f"status={_extract_po_status(po)} date={_extract_po_date(po)}"
                ),
            )

    _debug(
        debug,
        (
            "PO filter summary: "
            f"total={diagnostics['total_fetched']} "
            f"in_range={diagnostics['dated_in_range']} "
            f"out_of_range={diagnostics['dated_outside_range']} "
            f"unparsed_date={diagnostics['missing_or_unparsed_date']} "
            f"min_date={diagnostics['min_po_date']} "
            f"max_date={diagnostics['max_po_date']}"
        ),
    )

    return target, diagnostics


async def _fetch_po_dependencies(
    client: ZohoClient,
    target_pos: list[dict[str, Any]],
    progress_every: int,
    debug: bool,
) -> tuple[set[str], set[str], dict[str, str], dict[str, Any]]:
    bill_ids: set[str] = set()
    receive_ids: set[str] = set()
    bill_id_to_number: dict[str, str] = {}
    diagnostics: dict[str, Any] = {
        "target_purchase_orders": len(target_pos),
        "po_without_id": 0,
        "po_get_failures": 0,
        "po_embedded_receives_seen": 0,
        "po_embedded_receives_missing_id": 0,
        "po_dependency_samples": [],
    }

    total = len(target_pos)
    for idx, po in enumerate(target_pos, start=1):
        po_id = _extract_po_id(po)
        if not po_id:
            diagnostics["po_without_id"] += 1
            continue

        try:
            full_po = await client.get_purchase_order(po_id)
        except Exception:
            diagnostics["po_get_failures"] += 1
            if debug:
                _debug(debug, f"Failed to fetch purchaseorder detail for id={po_id}")
            continue

        if debug:
            _debug(
                True,
                (
                    f"PO detail id={po_id} number={_extract_po_number(po)} "
                    f"bills_embedded={len(full_po.get('bills') or [])} "
                    f"receives_embedded={len(full_po.get('purchasereceives') or [])}"
                ),
            )

        po_bill_count_before = len(bill_ids)
        po_receive_count_before = len(receive_ids)

        for bill in full_po.get("bills") or []:
            if not isinstance(bill, dict):
                continue
            bill_id = _clean_id(bill.get("bill_id") or bill.get("id"))
            bill_number = _clean_id(bill.get("bill_number") or bill.get("invoice_number"))
            if bill_id:
                bill_ids.add(bill_id)
                if bill_number:
                    bill_id_to_number[bill_id] = bill_number

        # Use receives embedded in the purchase-order detail response. This keeps
        # scope strictly bound to the PO and avoids endpoint-level filter drift.
        po_receives = full_po.get("purchasereceives") or full_po.get("receives") or []
        for receive in po_receives:
            if not isinstance(receive, dict):
                continue
            diagnostics["po_embedded_receives_seen"] += 1

            receive_id = _clean_id(
                receive.get("receive_id")
                or receive.get("purchase_receive_id")
                or receive.get("purchasereceive_id")
            )
            if not receive_id:
                diagnostics["po_embedded_receives_missing_id"] += 1
                continue

            receive_ids.add(receive_id)
            if debug:
                _debug(
                    True,
                    (
                        f"Receive linked to PO id={po_id} "
                        f"receive_id={receive_id} "
                        f"receive_number={_clean_id(receive.get('receive_number'))} "
                        f"date={_clean_id(receive.get('date'))}"
                    ),
                )

        if len(diagnostics["po_dependency_samples"]) < 10:
            diagnostics["po_dependency_samples"].append(
                {
                    "purchaseorder_id": po_id,
                    "purchaseorder_number": _extract_po_number(po),
                    "bills_found": len(bill_ids) - po_bill_count_before,
                    "receives_found": len(receive_ids) - po_receive_count_before,
                }
            )

        if progress_every > 0 and idx % progress_every == 0:
            print(f"Scanned purchase dependencies: {idx}/{total}")

    _debug(
        debug,
        (
            "Dependency summary: "
            f"target_pos={diagnostics['target_purchase_orders']} "
            f"bill_ids={len(bill_ids)} receive_ids={len(receive_ids)} "
            f"po_without_id={diagnostics['po_without_id']} "
            f"po_get_failures={diagnostics['po_get_failures']} "
            f"po_embedded_receives_seen={diagnostics['po_embedded_receives_seen']} "
            f"po_embedded_receives_missing_id={diagnostics['po_embedded_receives_missing_id']}"
        ),
    )

    return bill_ids, receive_ids, bill_id_to_number, diagnostics


async def _fetch_bill_payment_refs(
    client: ZohoClient,
    bill_ids: Iterable[str],
    progress_every: int,
    debug: bool,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    refs: list[dict[str, str]] = []
    bills_list = [b for b in bill_ids if b]
    total = len(bills_list)
    diagnostics: dict[str, Any] = {
        "bills_scanned": total,
        "bill_fetch_failures": 0,
        "payment_refs_found": 0,
        "payment_refs_missing_bill_payment_id": 0,
    }

    for idx, bill_id in enumerate(bills_list, start=1):
        try:
            full_bill = await client.get_bill(bill_id)
        except Exception:
            diagnostics["bill_fetch_failures"] += 1
            if debug:
                _debug(debug, f"Failed to fetch bill detail for bill_id={bill_id}")
            continue

        for payment in full_bill.get("payments") or []:
            if not isinstance(payment, dict):
                continue
            bill_payment_id = _clean_id(payment.get("bill_payment_id"))
            refs.append(
                {
                    "bill_id": bill_id,
                    "bill_payment_id": bill_payment_id,
                    "payment_id": _clean_id(payment.get("payment_id")),
                    "date": _clean_id(payment.get("date")),
                }
            )
            if debug:
                _debug(
                    True,
                    (
                        f"Payment linked to bill id={bill_id} "
                        f"bill_payment_id={bill_payment_id} "
                        f"payment_id={_clean_id(payment.get('payment_id'))} "
                        f"date={_clean_id(payment.get('date'))}"
                    ),
                )
            diagnostics["payment_refs_found"] += 1
            if not bill_payment_id:
                diagnostics["payment_refs_missing_bill_payment_id"] += 1

        if progress_every > 0 and idx % progress_every == 0:
            print(f"Scanned bill payments: {idx}/{total}")

    valid_refs = [r for r in refs if r["bill_payment_id"]]
    _debug(
        debug,
        (
            "Payment summary: "
            f"bills_scanned={diagnostics['bills_scanned']} "
            f"bill_fetch_failures={diagnostics['bill_fetch_failures']} "
            f"payment_refs_found={diagnostics['payment_refs_found']} "
            f"payment_refs_with_valid_bill_payment_id={len(valid_refs)}"
        ),
    )

    return valid_refs, diagnostics


def _mismatch(csv_ids: set[str], zoho_ids: set[str]) -> dict[str, list[str]]:
    return {
        "csv_missing_in_zoho": sorted(csv_ids - zoho_ids),
        "zoho_missing_in_csv": sorted(zoho_ids - csv_ids),
    }


async def _delete_payments(
    client: ZohoClient,
    payment_refs: list[dict[str, str]],
    dry_run: bool,
    progress_every: int,
) -> dict[str, Any]:
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    total = len(payment_refs)

    for idx, ref in enumerate(payment_refs, start=1):
        bill_id = ref["bill_id"]
        bill_payment_id = ref["bill_payment_id"]
        if dry_run:
            deleted.append(bill_payment_id)
        else:
            try:
                await client.delete_bill_payment(bill_id=bill_id, bill_payment_id=bill_payment_id)
                deleted.append(bill_payment_id)
            except Exception as exc:
                failed.append(
                    {
                        "bill_id": bill_id,
                        "bill_payment_id": bill_payment_id,
                        "error": str(exc),
                    }
                )

        if progress_every > 0 and idx % progress_every == 0:
            print(f"Deleted payments: {idx}/{total}")

    return {
        "attempted": total,
        "deleted_count": len(deleted),
        "failed_count": len(failed),
        "deleted_ids": deleted,
        "failed": failed,
    }


async def _delete_bills(
    client: ZohoClient,
    bill_ids: list[str],
    dry_run: bool,
    progress_every: int,
) -> dict[str, Any]:
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    total = len(bill_ids)

    for idx, bill_id in enumerate(bill_ids, start=1):
        if dry_run:
            deleted.append(bill_id)
        else:
            try:
                await client.delete_bill(bill_id)
                deleted.append(bill_id)
            except Exception as exc:
                failed.append({"bill_id": bill_id, "error": str(exc)})

        if progress_every > 0 and idx % progress_every == 0:
            print(f"Deleted bills: {idx}/{total}")

    return {
        "attempted": total,
        "deleted_count": len(deleted),
        "failed_count": len(failed),
        "deleted_ids": deleted,
        "failed": failed,
    }


async def _delete_receives(
    client: ZohoClient,
    receive_ids: list[str],
    dry_run: bool,
    progress_every: int,
) -> dict[str, Any]:
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    total = len(receive_ids)

    for idx, receive_id in enumerate(receive_ids, start=1):
        if dry_run:
            deleted.append(receive_id)
        else:
            try:
                await client.delete_purchase_receive(receive_id)
                deleted.append(receive_id)
            except Exception as exc:
                failed.append({"receive_id": receive_id, "error": str(exc)})

        if progress_every > 0 and idx % progress_every == 0:
            print(f"Deleted receives: {idx}/{total}")

    return {
        "attempted": total,
        "deleted_count": len(deleted),
        "failed_count": len(failed),
        "deleted_ids": deleted,
        "failed": failed,
    }


async def main() -> None:
    today = date.today()
    jan_first = date(today.year, 1, 1)

    parser = argparse.ArgumentParser(
        description=(
            "Delete Zoho payments, bills, and receives in strict dependency order "
            "for purchase orders created in the input period"
        )
    )
    parser.add_argument("--start-date", default=jan_first.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=today.isoformat(), help="YYYY-MM-DD")
    parser.add_argument(
        "--bill-csv",
        default=str(PROJECT_ROOT / "misc" / "Bill.csv"),
        help="Path to Bill.csv",
    )
    parser.add_argument(
        "--payment-csv",
        default=str(PROJECT_ROOT / "misc" / "Vendor_Payment.csv"),
        help="Path to Vendor_Payment.csv",
    )
    parser.add_argument(
        "--receive-csv",
        default=str(PROJECT_ROOT / "misc" / "Purchase_Receive.csv"),
        help="Path to Purchase_Receive.csv",
    )
    parser.add_argument(
        "--report-path",
        default=str(PROJECT_ROOT / "scripts" / "zoho_delete_report.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--debug", action="store_true", help="Print diagnostics for filtering and dependency discovery")
    parser.add_argument("--trace-api", action="store_true", help="Trace each Zoho API call made by this script")
    parser.add_argument("--dry-run", action="store_true", help="Do not delete anything")
    args = parser.parse_args()

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if start_date is None or end_date is None:
        raise ValueError("start-date and end-date must be valid YYYY-MM-DD")
    if end_date < start_date:
        raise ValueError("end-date must be >= start-date")

    bill_csv = Path(args.bill_csv)
    payment_csv = Path(args.payment_csv)
    receive_csv = Path(args.receive_csv)
    report_path = Path(args.report_path)

    for csv_path in (bill_csv, payment_csv, receive_csv):
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")

    client = ZohoClient()
    _install_api_trace(client, enabled=bool(args.trace_api))
    _debug(
        args.debug,
        f"Window start={start_date.isoformat()} end={end_date.isoformat()} dry_run={bool(args.dry_run)}",
    )
    _debug(
        args.debug,
        (
            f"Zoho client org_id={client.organization_id} "
            f"inventory_base={client.inventory_api_url} books_base={client.books_api_url}"
        ),
    )
    _debug(
        args.debug,
        f"CSV paths bill={bill_csv} payment={payment_csv} receive={receive_csv}",
    )

    print("Fetching purchase orders in range...")
    target_pos, po_filter_diagnostics = await _fetch_target_purchase_orders(
        client,
        start_date,
        end_date,
        debug=bool(args.debug),
    )
    target_po_ids = {_extract_po_id(po) for po in target_pos if _extract_po_id(po)}
    target_po_numbers = {_extract_po_number(po) for po in target_pos if _extract_po_number(po)}
    _debug(args.debug, f"Target purchases selected count={len(target_pos)}")

    print("Fetching attached bills and receives from purchase orders...")
    bill_ids_zoho, receive_ids_zoho, bill_id_to_number, dependency_diagnostics = await _fetch_po_dependencies(
        client,
        target_pos=target_pos,
        progress_every=max(args.progress_every, 0),
        debug=bool(args.debug),
    )

    csv_universe = _build_csv_universe_for_purchases(
        bill_csv=bill_csv,
        payment_csv=payment_csv,
        receive_csv=receive_csv,
        target_po_numbers=target_po_numbers,
    )

    print("Fetching attached payments from derived bills...")
    payment_refs, payment_diagnostics = await _fetch_bill_payment_refs(
        client,
        bill_ids=sorted(bill_ids_zoho),
        progress_every=max(args.progress_every, 0),
        debug=bool(args.debug),
    )
    payment_bill_ids_zoho = {r["bill_payment_id"] for r in payment_refs if r["bill_payment_id"]}
    payment_vendor_ids_zoho = {r["payment_id"] for r in payment_refs if r["payment_id"]}

    bill_numbers_zoho = {
        bill_id_to_number.get(bill_id, "") for bill_id in bill_ids_zoho if bill_id_to_number.get(bill_id, "")
    }

    mismatches = {
        "purchase_orders_by_number": _mismatch(csv_universe.po_numbers, target_po_numbers),
        "bills": _mismatch(csv_universe.bill_ids, bill_ids_zoho),
        "bill_numbers": _mismatch(csv_universe.bill_numbers, bill_numbers_zoho),
        "payments_by_bill_payment_id": _mismatch(
            csv_universe.payment_bill_payment_ids,
            payment_bill_ids_zoho,
        ),
        "payments_by_vendor_payment_id": _mismatch(
            csv_universe.payment_vendor_ids,
            payment_vendor_ids_zoho,
        ),
        "receives": _mismatch(csv_universe.receive_ids, receive_ids_zoho),
    }

    print("Step 1/3: deleting payments...")
    payment_result = await _delete_payments(
        client,
        payment_refs=payment_refs,
        dry_run=args.dry_run,
        progress_every=max(args.progress_every, 0),
    )

    print("Step 2/3: deleting bills...")
    bill_result = await _delete_bills(
        client,
        bill_ids=sorted(bill_ids_zoho),
        dry_run=args.dry_run,
        progress_every=max(args.progress_every, 0),
    )

    print("Step 3/3: deleting receives...")
    receive_target_ids = sorted(receive_ids_zoho)

    receive_result = await _delete_receives(
        client,
        receive_ids=receive_target_ids,
        dry_run=args.dry_run,
        progress_every=max(args.progress_every, 0),
    )

    report = {
        "window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "dry_run": bool(args.dry_run),
        },
        "csv_counts": {
            "purchase_order_numbers": len(csv_universe.po_numbers),
            "bill_ids": len(csv_universe.bill_ids),
            "bill_numbers": len(csv_universe.bill_numbers),
            "payment_vendor_ids": len(csv_universe.payment_vendor_ids),
            "payment_bill_payment_ids": len(csv_universe.payment_bill_payment_ids),
            "receive_ids": len(csv_universe.receive_ids),
        },
        "zoho_counts_before_delete": {
            "purchase_order_ids": len(target_po_ids),
            "purchase_order_numbers": len(target_po_numbers),
            "bill_ids": len(bill_ids_zoho),
            "bill_numbers": len(bill_numbers_zoho),
            "payment_bill_payment_ids": len(payment_bill_ids_zoho),
            "payment_vendor_ids": len(payment_vendor_ids_zoho),
            "receive_ids": len(receive_ids_zoho),
        },
        "mismatches": mismatches,
        "delete_results": {
            "payments": payment_result,
            "bills": bill_result,
            "receives": receive_result,
        },
        "notes": {
            "delete_scope": (
                "payments/bills/receives attached to purchase orders whose purchase date "
                "falls within the input period"
            ),
            "debug_mode": bool(args.debug),
            "trace_api": bool(args.trace_api),
            "diagnostics": {
                "purchase_order_filter": po_filter_diagnostics,
                "dependencies": dependency_diagnostics,
                "payments": payment_diagnostics,
            },
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Done.")
    print(f"Report written to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
