#!/usr/bin/env python
"""
Offline audit script to find Purchase Orders with Zoho Bill total discrepancies / double-counting.

Audit Logic:
1. Fetches all Purchase Orders from a start date (default: 2026-05-01) to end date (default: today).
2. For each PO, fetches the remote Zoho PO and its linked Zoho Bills via API.
3. Compares PO total against Bill total and checks:
   - Sum of shipping + tax + handling on the PO.
   - Bill adjustment and adjustment_description.
   - Flags confirmed double-counting where charges were factored into line rates AND added as a bill adjustment.
   - Identifies edge cases: partial billing, void/draft bills, multi-bill POs, manual adjustments.
4. Outputs a console summary and saves a detailed CSV report.

Usage:
    python scripts/audit_po_bill_double_counting.py [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--all]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sys
from typing import Any, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

env_path = PROJECT_ROOT.parent / ".env"
if not env_path.exists():
    env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=env_path)

from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient
from app.models.purchasing import PurchaseOrder

MONEY_ROUND = Decimal("0.01")


def to_dec(val: Any, default: str = "0") -> Decimal:
    """Convert any monetary representation to Decimal with clean formatting."""
    if val is None:
        return Decimal(default)
    try:
        clean = str(val).replace("$", "").replace(",", "").strip()
        return Decimal(clean) if clean else Decimal(default)
    except Exception:
        return Decimal(default)


def quantize_dec(val: Decimal) -> Decimal:
    return val.quantize(MONEY_ROUND, rounding=ROUND_HALF_UP)


@dataclass
class AuditRecord:
    po_number: str
    po_date: str
    po_source: str
    vendor_name: str
    po_zoho_id: str
    db_po_total: Decimal
    zoho_po_total: Decimal
    shipping_amount: Decimal
    tax_amount: Decimal
    handling_amount: Decimal
    total_charges: Decimal
    bill_count: int
    bill_id: str
    bill_number: str
    bill_status: str
    bill_subtotal: Decimal
    bill_adjustment: Decimal
    bill_adjustment_desc: str
    bill_total: Decimal
    total_diff: Decimal
    classification: str
    notes: str


def classify_discrepancy(
    *,
    bill_count: int,
    bill_status: str,
    po_total: Decimal,
    bill_total: Decimal,
    total_charges: Decimal,
    bill_adjustment: Decimal,
    bill_adj_desc: str,
) -> tuple[str, str]:
    """
    Classify the order and detect double counting vs edge cases.

    Returns:
        (classification_code, explanation_notes)
    """
    if bill_count == 0:
        return "UNBILLED", "PO has no linked bills in Zoho"

    if bill_status.lower() in {"void", "draft"}:
        return "INACTIVE_BILL", f"Bill is in {bill_status.upper()} status"

    diff = quantize_dec(bill_total - po_total)
    charges_dec = quantize_dec(total_charges)
    adj_dec = quantize_dec(bill_adjustment)

    is_exact_charge_diff = charges_dec > Decimal("0") and abs(diff - charges_dec) <= Decimal("0.02")
    is_matching_adjustment = charges_dec > Decimal("0") and abs(adj_dec - charges_dec) <= Decimal("0.02")
    has_charge_adj_desc = (
        "shipping" in bill_adj_desc.lower()
        or "handling" in bill_adj_desc.lower()
        or "tax" in bill_adj_desc.lower()
    )

    if abs(diff) <= Decimal("0.02"):
        if adj_dec == Decimal("0"):
            return "MATCH", "Bill total perfectly matches PO total"
        else:
            return "MATCH_WITH_ADJ", f"Bill total matches PO total, but has adjustment={adj_dec:.2f}"

    # Discrepancy present
    if is_exact_charge_diff or (is_matching_adjustment and has_charge_adj_desc):
        return (
            "DOUBLE_COUNT_CONFIRMED",
            f"Overbilled by {diff:.2f}: Bill has {adj_dec:.2f} adjustment for charges already distributed in PO lines",
        )

    if diff > Decimal("0"):
        if adj_dec > Decimal("0"):
            return (
                "OVERBILLED_CUSTOM_ADJ",
                f"Bill total exceeds PO total by {diff:.2f} (bill adjustment={adj_dec:.2f}, charges={charges_dec:.2f})",
            )
        else:
            return (
                "OVERBILLED_LINE_DIFF",
                f"Bill total exceeds PO total by {diff:.2f} with 0 bill adjustment (check line item quantities/rates)",
            )
    else:
        # diff < 0
        if bill_count > 1:
            return "PARTIAL_OR_MULTI_BILL", f"Multiple bills on PO; single bill diff is {diff:.2f}"
        return (
            "UNDERBILLED_PARTIAL",
            f"Bill total is lower than PO total by {abs(diff):.2f} (partial receive/billing or vendor credit)",
        )


async def fetch_po_bill_audit(
    start_date: date,
    end_date: date,
    *,
    concurrency: int = 5,
) -> list[AuditRecord]:
    zoho = ZohoClient()
    records: list[AuditRecord] = []
    semaphore = asyncio.Semaphore(concurrency)

    # 1. Fetch DB Purchase Orders
    print(f"[*] Querying database for Purchase Orders between {start_date} and {end_date}...")
    db_pos_by_number: dict[str, PurchaseOrder] = {}
    db_pos_by_zoho_id: dict[str, PurchaseOrder] = {}

    try:
        async with async_session_factory() as session:
            stmt = (
                select(PurchaseOrder)
                .where(
                    PurchaseOrder.order_date >= start_date,
                    PurchaseOrder.order_date <= end_date,
                )
                .options(
                    undefer(PurchaseOrder.zoho_bill_created),
                    undefer(PurchaseOrder.zoho_bill_id),
                    undefer(PurchaseOrder.zoho_billed_checked_at),
                )
                .order_by(PurchaseOrder.order_date.asc())
            )
            result = await session.execute(stmt)
            for po in result.scalars().all():
                if po.po_number:
                    db_pos_by_number[po.po_number] = po
                if po.zoho_id:
                    db_pos_by_zoho_id[str(po.zoho_id)] = po

        print(f"[+] Loaded {len(db_pos_by_number)} Purchase Orders from database.")
    except Exception as exc:
        print(f"[!] Warning: Could not query DB ({exc}). Proceeding with Zoho API directly...")

    # 2. Fetch Zoho Purchase Orders in Date Range
    print(f"[*] Fetching Zoho Purchase Orders from {start_date} to {end_date} via API...")
    zoho_pos: list[dict[str, Any]] = []
    page = 1
    per_page = 200
    while True:
        try:
            batch = await zoho.list_purchase_orders(
                date_start=start_date.isoformat(),
                date_end=end_date.isoformat(),
                page=page,
                per_page=per_page,
            )
            if not batch:
                break
            zoho_pos.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        except Exception as exc:
            print(f"[!] Error fetching Zoho PO list page {page}: {exc}")
            break

    print(f"[+] Retrieved {len(zoho_pos)} POs from Zoho.")

    # 3. For each Zoho PO, fetch full details and linked bills
    print(f"[*] Fetching PO details and linked Bills (concurrency limit={concurrency})...")

    async def process_single_po(basic_po: dict[str, Any]) -> list[AuditRecord]:
        zoho_po_id = str(basic_po.get("purchaseorder_id") or "").strip()
        po_number = str(basic_po.get("purchaseorder_number") or "").strip()
        if not zoho_po_id:
            return []

        async with semaphore:
            try:
                full_po = await zoho.get_purchase_order(zoho_po_id)
            except Exception as e:
                print(f"[!] Error fetching PO {po_number} ({zoho_po_id}): {e}")
                full_po = basic_po

            # Link with local DB record if exists
            local_po = db_pos_by_number.get(po_number) or db_pos_by_zoho_id.get(zoho_po_id)

            po_date = str(full_po.get("date") or getattr(local_po, "order_date", "") or "")
            po_source = str(getattr(local_po, "source", "") or full_po.get("cf_source", "UNKNOWN"))
            vendor_name = str(
                full_po.get("vendor_name")
                or (local_po.vendor.name if local_po and getattr(local_po, "vendor", None) else "Unknown")
            )

            zoho_po_total = to_dec(full_po.get("total"))
            db_po_total = to_dec(getattr(local_po, "total_amount", None)) if local_po else zoho_po_total

            # Charges
            shipping_amt = (
                to_dec(getattr(local_po, "shipping_amount", None))
                if local_po
                else to_dec(full_po.get("shipping_charge", 0))
            )
            tax_amt = (
                to_dec(getattr(local_po, "tax_amount", None))
                if local_po
                else to_dec(full_po.get("tax_total", 0))
            )
            handling_amt = (
                to_dec(getattr(local_po, "handling_amount", None))
                if local_po
                else Decimal("0")
            )
            total_charges = shipping_amt + tax_amt + handling_amt

            bills_summary = full_po.get("bills") or []
            if not isinstance(bills_summary, list):
                bills_summary = []

            if not bills_summary:
                cls, notes = classify_discrepancy(
                    bill_count=0,
                    bill_status="",
                    po_total=zoho_po_total,
                    bill_total=Decimal("0"),
                    total_charges=total_charges,
                    bill_adjustment=Decimal("0"),
                    bill_adj_desc="",
                )
                return [
                    AuditRecord(
                        po_number=po_number,
                        po_date=po_date,
                        po_source=po_source,
                        vendor_name=vendor_name,
                        po_zoho_id=zoho_po_id,
                        db_po_total=quantize_dec(db_po_total),
                        zoho_po_total=quantize_dec(zoho_po_total),
                        shipping_amount=quantize_dec(shipping_amt),
                        tax_amount=quantize_dec(tax_amt),
                        handling_amount=quantize_dec(handling_amt),
                        total_charges=quantize_dec(total_charges),
                        bill_count=0,
                        bill_id="",
                        bill_number="",
                        bill_status="UNBILLED",
                        bill_subtotal=Decimal("0.00"),
                        bill_adjustment=Decimal("0.00"),
                        bill_adjustment_desc="",
                        bill_total=Decimal("0.00"),
                        total_diff=Decimal("0.00"),
                        classification=cls,
                        notes=notes,
                    )
                ]

            po_records: list[AuditRecord] = []
            for b_summary in bills_summary:
                b_id = str((b_summary or {}).get("bill_id") or "").strip()
                if not b_id:
                    continue
                try:
                    full_bill = await zoho.get_bill(b_id)
                except Exception as e:
                    full_bill = b_summary or {}

                b_number = str(full_bill.get("bill_number") or b_summary.get("bill_number") or "").strip()
                b_status = str(full_bill.get("status") or b_summary.get("status") or "").strip()
                b_total = to_dec(full_bill.get("total") if "total" in full_bill else b_summary.get("total"))
                b_subtotal = to_dec(full_bill.get("sub_total", 0))
                b_adj = to_dec(full_bill.get("adjustment", 0))
                b_adj_desc = str(full_bill.get("adjustment_description", "") or "")

                diff = quantize_dec(b_total - zoho_po_total)
                cls, notes = classify_discrepancy(
                    bill_count=len(bills_summary),
                    bill_status=b_status,
                    po_total=zoho_po_total,
                    bill_total=b_total,
                    total_charges=total_charges,
                    bill_adjustment=b_adj,
                    bill_adj_desc=b_adj_desc,
                )

                po_records.append(
                    AuditRecord(
                        po_number=po_number,
                        po_date=po_date,
                        po_source=po_source,
                        vendor_name=vendor_name,
                        po_zoho_id=zoho_po_id,
                        db_po_total=quantize_dec(db_po_total),
                        zoho_po_total=quantize_dec(zoho_po_total),
                        shipping_amount=quantize_dec(shipping_amt),
                        tax_amount=quantize_dec(tax_amt),
                        handling_amount=quantize_dec(handling_amt),
                        total_charges=quantize_dec(total_charges),
                        bill_count=len(bills_summary),
                        bill_id=b_id,
                        bill_number=b_number,
                        bill_status=b_status,
                        bill_subtotal=quantize_dec(b_subtotal),
                        bill_adjustment=quantize_dec(b_adj),
                        bill_adjustment_desc=b_adj_desc,
                        bill_total=quantize_dec(b_total),
                        total_diff=diff,
                        classification=cls,
                        notes=notes,
                    )
                )

            return po_records

    tasks = [process_single_po(po) for po in zoho_pos]
    results = await asyncio.gather(*tasks)
    for rec_list in results:
        records.extend(rec_list)

    return records


def export_csv(records: list[AuditRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "po_number",
        "po_date",
        "po_source",
        "vendor_name",
        "po_zoho_id",
        "db_po_total",
        "zoho_po_total",
        "shipping_amount",
        "tax_amount",
        "handling_amount",
        "total_charges",
        "bill_count",
        "bill_id",
        "bill_number",
        "bill_status",
        "bill_subtotal",
        "bill_adjustment",
        "bill_adjustment_desc",
        "bill_total",
        "total_diff",
        "classification",
        "notes",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow({
                "po_number": r.po_number,
                "po_date": r.po_date,
                "po_source": r.po_source,
                "vendor_name": r.vendor_name,
                "po_zoho_id": r.po_zoho_id,
                "db_po_total": f"{r.db_po_total:.2f}",
                "zoho_po_total": f"{r.zoho_po_total:.2f}",
                "shipping_amount": f"{r.shipping_amount:.2f}",
                "tax_amount": f"{r.tax_amount:.2f}",
                "handling_amount": f"{r.handling_amount:.2f}",
                "total_charges": f"{r.total_charges:.2f}",
                "bill_count": r.bill_count,
                "bill_id": r.bill_id,
                "bill_number": r.bill_number,
                "bill_status": r.bill_status,
                "bill_subtotal": f"{r.bill_subtotal:.2f}",
                "bill_adjustment": f"{r.bill_adjustment:.2f}",
                "bill_adjustment_desc": r.bill_adjustment_desc,
                "bill_total": f"{r.bill_total:.2f}",
                "total_diff": f"{r.total_diff:.2f}",
                "classification": r.classification,
                "notes": r.notes,
            })


def print_summary(records: list[AuditRecord], mismatches: list[AuditRecord]) -> None:
    double_counted = [r for r in records if r.classification == "DOUBLE_COUNT_CONFIRMED"]
    matches = [r for r in records if r.classification in {"MATCH", "MATCH_WITH_ADJ"}]
    unbilled = [r for r in records if r.classification == "UNBILLED"]
    other_mismatches = [
        r for r in records
        if r.classification not in {"MATCH", "MATCH_WITH_ADJ", "UNBILLED", "DOUBLE_COUNT_CONFIRMED"}
    ]

    total_overbilled_amt = sum((r.total_diff for r in double_counted), Decimal("0.00"))

    print("\n" + "=" * 80)
    print("                 PURCHASE ORDER & BILL AUDIT SUMMARY")
    print("=" * 80)
    print(f"Total PO Records Audited   : {len(records)}")
    print(f"Exact Matches (No Diff)    : {len(matches)}")
    print(f"Unbilled POs               : {len(unbilled)}")
    print(f"Double-Counted Confirmed   : {len(double_counted)} (Total Overbilled: ${total_overbilled_amt:,.2f})")
    print(f"Other Discrepancies        : {len(other_mismatches)}")
    print("=" * 80)

    if double_counted:
        print("\n[!] CONFIRMED DOUBLE-COUNTED PURCHASE ORDERS:")
        print(f"{'PO Number':<16} {'Date':<11} {'Source':<16} {'PO Total':>10} {'Bill Total':>10} {'Diff (Over)':>12} {'Bill Adj':>10} {'Adj Description'}")
        print("-" * 105)
        for r in double_counted[:25]:
            print(
                f"{r.po_number:<16} {r.po_date:<11} {r.po_source[:15]:<16} "
                f"${r.zoho_po_total:>9.2f} ${r.bill_total:>9.2f} "
                f"+${r.total_diff:>10.2f} ${r.bill_adjustment:>9.2f} {r.bill_adjustment_desc}"
            )
        if len(double_counted) > 25:
            print(f"... and {len(double_counted) - 25} more double-counted records (see CSV report).")

    if other_mismatches:
        print("\n[*] OTHER DISCREPANCIES (Edge cases / Partial / Custom adjustments):")
        print(f"{'PO Number':<16} {'Date':<11} {'Classification':<24} {'PO Total':>10} {'Bill Total':>10} {'Diff':>10} {'Notes'}")
        print("-" * 110)
        for r in other_mismatches[:15]:
            print(
                f"{r.po_number:<16} {r.po_date:<11} {r.classification:<24} "
                f"${r.zoho_po_total:>9.2f} ${r.bill_total:>9.2f} "
                f"${r.total_diff:>9.2f} {r.notes}"
            )
        if len(other_mismatches) > 15:
            print(f"... and {len(other_mismatches) - 15} more records (see CSV report).")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Purchase Orders and Zoho Bills for Double Counting.")
    parser.add_argument("--start-date", default="2026-05-01", help="Start date (YYYY-MM-DD), default: 2026-05-01")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="End date (YYYY-MM-DD), default: today")
    parser.add_argument("--all", action="store_true", help="Include all records in output (default exports mismatches only)")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent API request limit (default: 5)")
    parser.add_argument("--csv", help="Custom CSV output path")
    args = parser.parse_args()

    try:
        start_d = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    except ValueError as exc:
        print(f"Invalid date format: {exc}. Please use YYYY-MM-DD.")
        sys.exit(1)

    print(f"Starting PO & Bill audit from {start_d} to {end_d}...")
    records = await fetch_po_bill_audit(start_d, end_d, concurrency=args.concurrency)

    if not records:
        print("No purchase orders found in the specified range.")
        return

    mismatches = [r for r in records if r.classification != "MATCH"]
    print_summary(records, mismatches)

    # Determine export target
    records_to_export = records if args.all else mismatches
    csv_file = Path(args.csv) if args.csv else PROJECT_ROOT / "misc" / f"po_bill_audit_{start_d}_{end_d}.csv"
    export_csv(records_to_export, csv_file)
    print(f"\n[+] Exported {len(records_to_export)} records to: {csv_file}\n")


if __name__ == "__main__":
    asyncio.run(main())
