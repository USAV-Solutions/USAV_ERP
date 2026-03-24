#!/usr/bin/env python
"""Sequentially delete Zoho purchasing dependencies for a date range.

Delete order is strict:
1) Bill payments
2) Bills
3) Purchase receives

The script cross-checks Zoho records against three CSV exports and writes a
report for any IDs that are missing from CSV or missing in Zoho.
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
    bill_ids: set[str]
    payment_vendor_ids: set[str]
    payment_bill_payment_ids: set[str]
    receive_ids: set[str]


def _build_csv_universe(
    *,
    bill_csv: Path,
    payment_csv: Path,
    receive_csv: Path,
    start_date: date,
    end_date: date,
) -> CsvUniverse:
    bill_ids: set[str] = set()
    payment_vendor_ids: set[str] = set()
    payment_bill_payment_ids: set[str] = set()
    receive_ids: set[str] = set()

    for row in _read_csv_rows(bill_csv):
        row_date = _parse_csv_date(row.get("Bill Date"))
        if not _in_range(row_date, start_date, end_date):
            continue
        bill_id = _clean_id(row.get("PayInvoice ID"))
        if bill_id:
            bill_ids.add(bill_id)

    for row in _read_csv_rows(payment_csv):
        row_date = _parse_csv_date(row.get("Date"))
        if not _in_range(row_date, start_date, end_date):
            continue

        vendor_payment_id = _clean_id(row.get("VendorPayment ID"))
        bill_payment_id = _clean_id(row.get("PIPayment ID"))

        if vendor_payment_id:
            payment_vendor_ids.add(vendor_payment_id)
        if bill_payment_id:
            payment_bill_payment_ids.add(bill_payment_id)

    for row in _read_csv_rows(receive_csv):
        row_date = _parse_csv_date(row.get("Receive Date"))
        if not _in_range(row_date, start_date, end_date):
            continue
        receive_id = _clean_id(row.get("Purchase Receive ID"))
        if receive_id:
            receive_ids.add(receive_id)

    return CsvUniverse(
        bill_ids=bill_ids,
        payment_vendor_ids=payment_vendor_ids,
        payment_bill_payment_ids=payment_bill_payment_ids,
        receive_ids=receive_ids,
    )


async def _fetch_bills(client: ZohoClient, start_date: date, end_date: date) -> list[dict[str, Any]]:
    all_bills: list[dict[str, Any]] = []
    page = 1
    per_page = 200

    while True:
        chunk = await client.list_bills(
            date_start=start_date.isoformat(),
            date_end=end_date.isoformat(),
            page=page,
            per_page=per_page,
        )
        if not chunk:
            break
        all_bills.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1

    return all_bills


async def _fetch_bill_payment_refs(
    client: ZohoClient,
    bills: Iterable[dict[str, Any]],
    start_date: date,
    end_date: date,
    progress_every: int,
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    bills_list = list(bills)
    total = len(bills_list)
    for idx, bill in enumerate(bills_list, start=1):
        bill_id = _clean_id(bill.get("bill_id"))
        if not bill_id:
            continue
        full_bill = await client.get_bill(bill_id)
        for payment in full_bill.get("payments") or []:
            if not isinstance(payment, dict):
                continue
            pay_date = _parse_csv_date(_clean_id(payment.get("date")))
            if pay_date is not None and not _in_range(pay_date, start_date, end_date):
                continue

            refs.append(
                {
                    "bill_id": bill_id,
                    "bill_payment_id": _clean_id(payment.get("bill_payment_id")),
                    "payment_id": _clean_id(payment.get("payment_id")),
                    "date": _clean_id(payment.get("date")),
                }
            )

        if progress_every > 0 and idx % progress_every == 0:
            print(f"Scanned bill payments: {idx}/{total}")

    return [r for r in refs if r["bill_payment_id"]]


async def _fetch_purchase_receives(
    client: ZohoClient,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    all_receives: list[dict[str, Any]] = []
    page = 1
    per_page = 200
    while True:
        chunk = await client.list_purchase_receives(
            date_start=start_date.isoformat(),
            date_end=end_date.isoformat(),
            page=page,
            per_page=per_page,
        )
        if not chunk:
            break
        all_receives.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1
    return all_receives


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
    bills: list[dict[str, Any]],
    dry_run: bool,
    progress_every: int,
) -> dict[str, Any]:
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    total = len(bills)

    for idx, bill in enumerate(bills, start=1):
        bill_id = _clean_id(bill.get("bill_id"))
        if not bill_id:
            continue
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
        description="Delete Zoho payments, bills, and receives in strict dependency order"
    )
    parser.add_argument("--start-date", default=jan_first.isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=today.isoformat(), help="YYYY-MM-DD")
    parser.add_argument(
        "--bill-csv",
        default=str(PROJECT_ROOT.parent / "misc" / "Bill.csv"),
        help="Path to Bill.csv",
    )
    parser.add_argument(
        "--payment-csv",
        default=str(PROJECT_ROOT.parent / "misc" / "Vendor_Payment.csv"),
        help="Path to Vendor_Payment.csv",
    )
    parser.add_argument(
        "--receive-csv",
        default=str(PROJECT_ROOT.parent / "misc" / "Purchase_Receive.csv"),
        help="Path to Purchase_Receive.csv",
    )
    parser.add_argument(
        "--report-path",
        default=str(PROJECT_ROOT / "scripts" / "zoho_delete_report.json"),
        help="Output JSON report path",
    )
    parser.add_argument("--progress-every", type=int, default=50)
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

    csv_universe = _build_csv_universe(
        bill_csv=bill_csv,
        payment_csv=payment_csv,
        receive_csv=receive_csv,
        start_date=start_date,
        end_date=end_date,
    )

    client = ZohoClient()

    print("Fetching Zoho bills and payments...")
    bills = await _fetch_bills(client, start_date, end_date)
    bill_ids_zoho = {_clean_id(b.get("bill_id")) for b in bills if _clean_id(b.get("bill_id"))}

    payment_refs = await _fetch_bill_payment_refs(
        client,
        bills=bills,
        start_date=start_date,
        end_date=end_date,
        progress_every=max(args.progress_every, 0),
    )
    payment_bill_ids_zoho = {r["bill_payment_id"] for r in payment_refs if r["bill_payment_id"]}
    payment_vendor_ids_zoho = {r["payment_id"] for r in payment_refs if r["payment_id"]}

    print("Fetching Zoho purchase receives...")
    receive_fetch_error: Optional[str] = None
    receives: list[dict[str, Any]] = []
    try:
        receives = await _fetch_purchase_receives(client, start_date, end_date)
    except Exception as exc:
        receive_fetch_error = str(exc)
        print(f"Warning: could not list purchase receives; fallback to CSV IDs for delete target. {exc}")

    receive_ids_zoho = {
        _clean_id(r.get("receive_id") or r.get("purchasereceive_id"))
        for r in receives
        if _clean_id(r.get("receive_id") or r.get("purchasereceive_id"))
    }

    mismatches = {
        "bills": _mismatch(csv_universe.bill_ids, bill_ids_zoho),
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
    bills_after_payment = await _fetch_bills(client, start_date, end_date)
    bill_result = await _delete_bills(
        client,
        bills=bills_after_payment,
        dry_run=args.dry_run,
        progress_every=max(args.progress_every, 0),
    )

    print("Step 3/3: deleting receives...")
    if receive_ids_zoho:
        receive_target_ids = sorted(receive_ids_zoho)
    else:
        # Fallback when listing endpoint is unavailable for this tenant.
        receive_target_ids = sorted(csv_universe.receive_ids)

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
            "bill_ids": len(csv_universe.bill_ids),
            "payment_vendor_ids": len(csv_universe.payment_vendor_ids),
            "payment_bill_payment_ids": len(csv_universe.payment_bill_payment_ids),
            "receive_ids": len(csv_universe.receive_ids),
        },
        "zoho_counts_before_delete": {
            "bill_ids": len(bill_ids_zoho),
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
            "receive_fetch_error": receive_fetch_error,
            "receives_delete_target": "zoho_list" if receive_ids_zoho else "csv_fallback",
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Done.")
    print(f"Report written to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
