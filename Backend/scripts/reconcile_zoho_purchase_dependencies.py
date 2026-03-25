#!/usr/bin/env python
"""Reconcile Zoho purchase dependencies against CSV backups.

Flow:
1) Find purchase orders in input period.
2) Find their linked receives, bills, and bill payments from Zoho.
3) Compare with CSV records for those PO numbers.
4) Optionally restore missing receives/bills/payments through Zoho API.

Default mode is dry-run. Use --apply to perform API writes.
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.integrations.zoho.client import ZohoClient


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}")


def _trace(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[api] {message}")


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


def _in_range(value: Optional[date], start: date, end: date) -> bool:
    return value is not None and start <= value <= end


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


def _install_api_trace(client: ZohoClient, enabled: bool) -> None:
    if not enabled:
        return

    original_request = client._request

    async def traced_request(method: str, endpoint: str, api: str = "inventory", **kwargs: Any) -> dict:
        params = dict(kwargs.get("params") or {})
        params["organization_id"] = client.organization_id
        _trace(enabled, f"REQ method={method} api={api} endpoint={endpoint} params={json.dumps(params, separators=(',', ':'))}")
        try:
            result = await original_request(method, endpoint, api=api, **kwargs)
        except Exception as exc:
            _trace(enabled, f"ERR method={method} api={api} endpoint={endpoint} error={exc}")
            raise

        keys = sorted(list(result.keys())) if isinstance(result, dict) else []
        _trace(enabled, f"RES method={method} api={api} endpoint={endpoint} keys={json.dumps(keys)}")
        return result

    client._request = traced_request  # type: ignore[method-assign]


@dataclass
class CsvScoped:
    bills_by_id: dict[str, list[dict[str, str]]]
    receives_by_id: dict[str, list[dict[str, str]]]
    payments_by_vendor_id: dict[str, dict[str, str]]


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
    debug: bool,
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
            rid = _clean(receive.get("receive_id") or receive.get("purchase_receive_id") or receive.get("purchasereceive_id"))
            if rid:
                receives_by_id[rid] = {
                    **receive,
                    "purchaseorder_id": po_id,
                    "purchaseorder_number": po_number,
                    "vendor_name": _clean(full_po.get("vendor_name")),
                }

        for bill in full_po.get("bills") or []:
            if not isinstance(bill, dict):
                continue
            bid = _clean(bill.get("bill_id") or bill.get("id"))
            if not bid:
                continue
            bill_full = await client.get_bill(bid)
            bills_by_id[bid] = bill_full
            bnum = _clean(bill_full.get("bill_number") or bill.get("bill_number"))
            if bnum:
                bill_number_to_id[bnum] = bid

            for payment in bill_full.get("payments") or []:
                if not isinstance(payment, dict):
                    continue
                pid = _clean(payment.get("payment_id"))
                if pid:
                    payments_by_vendor_id[pid] = {
                        **payment,
                        "bill_id": bid,
                        "bill_number": bnum,
                        "vendor_id": _clean(bill_full.get("vendor_id")),
                        "vendor_name": _clean(bill_full.get("vendor_name")),
                        "currency_code": _clean(bill_full.get("currency_code")),
                        "bill_total": _clean(bill_full.get("total")),
                        "bill_date": _clean(bill_full.get("date")),
                    }

        if debug:
            _debug(
                True,
                f"PO collected number={po_number} bills={len(full_po.get('bills') or [])} receives={len(full_po.get('purchasereceives') or full_po.get('receives') or [])}",
            )

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
    receive_number = _clean(receive_rows[0].get("Receive Number"))
    receive_date = _clean(receive_rows[0].get("Receive Date"))
    notes = _clean(receive_rows[0].get("Notes"))

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

        line_items.append(
            {
                "item_id": item_id,
                "quantity": qty,
                "quantity_received": qty,
            }
        )

    if not line_items:
        return None

    return {
        "purchaseorder_id": po_id,
        "receive_number": receive_number,
        "date": receive_date,
        "notes": notes,
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
    bill_number = _clean(sample.get("Bill Number"))
    bill_date = _clean(sample.get("Bill Date"))
    due_date = _clean(sample.get("Due Date")) or bill_date

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

    return {
        "purchaseorder_id": po_id,
        "vendor_id": vendor_id,
        "bill_number": bill_number,
        "date": bill_date,
        "due_date": due_date,
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
        "bills": [
            {
                "bill_id": bill_id,
                "amount_applied": amount,
            }
        ],
    }

    paid_through = _clean(payment_row.get("Paid Through"))
    if paid_through:
        payload["paid_through_account_name"] = paid_through

    return payload


async def main() -> None:
    today = date.today()
    jan_first = date(today.year, 1, 1)

    parser = argparse.ArgumentParser(description="Reconcile and optionally restore Zoho PO-linked bills/payments/receives")
    parser.add_argument("--start-date", default=jan_first.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=today.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--bill-csv", default=str(PROJECT_ROOT / "misc" / "Bill.csv"))
    parser.add_argument("--receive-csv", default=str(PROJECT_ROOT / "misc" / "Purchase_Receive.csv"))
    parser.add_argument("--payment-csv", default=str(PROJECT_ROOT / "misc" / "Vendor_Payment.csv"))
    parser.add_argument("--report-path", default=str(PROJECT_ROOT / "scripts" / "zoho_reconciliation_report.json"))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--trace-api", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Execute restore operations via API")
    args = parser.parse_args()

    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if start_date is None or end_date is None:
        raise ValueError("start-date and end-date must be YYYY-MM-DD")
    if end_date < start_date:
        raise ValueError("end-date must be >= start-date")

    bill_csv = Path(args.bill_csv)
    receive_csv = Path(args.receive_csv)
    payment_csv = Path(args.payment_csv)
    report_path = Path(args.report_path)
    for p in (bill_csv, receive_csv, payment_csv):
        if not p.exists():
            raise FileNotFoundError(f"CSV not found: {p}")

    client = ZohoClient()
    _install_api_trace(client, enabled=bool(args.trace_api))

    _debug(args.debug, f"org={client.organization_id} inventory_base={client.inventory_api_url}")
    _debug(args.debug, f"window={start_date}..{end_date} apply={bool(args.apply)}")

    target_pos = await _fetch_target_pos(client, start_date, end_date)
    target_po_numbers = {_extract_po_number(po) for po in target_pos if _extract_po_number(po)}
    _debug(args.debug, f"target_pos={len(target_pos)} target_po_numbers={len(target_po_numbers)}")

    po_detail_by_number, zoho_bills, zoho_receives, zoho_payments, bill_number_to_id = await _collect_zoho_dependencies(
        client,
        target_pos,
        debug=bool(args.debug),
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

    # Restore receives first, then bills, then payments.
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

        if args.apply:
            try:
                await client.create_purchase_receive(payload)
                restore_results["receives"]["restored"] += 1
            except Exception as exc:
                restore_results["receives"]["failed"].append({"receive_id": receive_id, "error": str(exc)})
        else:
            restore_results["receives"]["restored"] += 1

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

        payload_vendor_id = _clean(payload.get("vendor_id"))
        if bill_number and payload_vendor_id:
            vendor_id_by_bill_number[bill_number] = payload_vendor_id

        if args.apply:
            try:
                created = await client.create_bill(payload)
                created_id = _clean(created.get("bill_id"))
                if bill_number and created_id:
                    created_bill_id_by_number[bill_number] = created_id
                restore_results["bills"]["restored"] += 1
            except Exception as exc:
                restore_results["bills"]["failed"].append({"bill_id": bill_id, "error": str(exc)})
        else:
            restore_results["bills"]["restored"] += 1

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

        if args.apply:
            try:
                await client.create_vendor_payment(payload)
                restore_results["payments"]["restored"] += 1
            except Exception as exc:
                restore_results["payments"]["failed"].append({"vendor_payment_id": vendor_payment_id, "error": str(exc)})
        else:
            restore_results["payments"]["restored"] += 1

    report = {
        "window": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "apply": bool(args.apply),
        },
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
        "missing_in_zoho": {
            "bill_ids": missing_bill_ids,
            "receive_ids": missing_receive_ids,
            "vendor_payment_ids": missing_payment_vendor_ids,
        },
        "restore_results": restore_results,
        "notes": {
            "restore_order": ["receives", "bills", "payments"],
            "api_trace": bool(args.trace_api),
            "dry_run": not bool(args.apply),
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Done.")
    print(f"Report written to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
