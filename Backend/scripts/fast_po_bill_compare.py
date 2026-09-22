import asyncio
from decimal import Decimal
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
env_path = PROJECT_ROOT.parent / ".env"
if not env_path.exists():
    env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=env_path)

from app.integrations.zoho.client import ZohoClient


async def fast_audit():
    zoho = ZohoClient()
    start_date = "2026-05-01"
    end_date = "2026-08-18"

    print(f"Fetching PO list from {start_date} to {end_date}...")
    po_dict = {}
    page = 1
    while True:
        try:
            pos = await zoho.list_purchase_orders(date_start=start_date, date_end=end_date, page=page, per_page=200)
            if not pos:
                break
            for p in pos:
                p_num = str(p.get("purchaseorder_number") or "").strip()
                if p_num:
                    po_dict[p_num] = {
                        "po_id": p.get("purchaseorder_id"),
                        "po_number": p_num,
                        "date": p.get("date"),
                        "total": Decimal(str(p.get("total", 0))),
                        "status": p.get("status"),
                        "billed_status": p.get("billed_status"),
                        "vendor_name": p.get("vendor_name"),
                    }
            if len(pos) < 200:
                break
            page += 1
            await asyncio.sleep(0.3)
        except Exception as exc:
            if "rate limit" in str(exc).lower() or "429" in str(exc):
                print("Rate limited on PO list. Waiting 60s...")
                await asyncio.sleep(60)
            else:
                raise

    print(f"Total Zoho POs fetched: {len(po_dict)}")

    print(f"Fetching Bills list from {start_date} to {end_date}...")
    bills_list = []
    page = 1
    while True:
        params = {
            "page": page,
            "per_page": 200,
            "filter_by": "Status.All",
            "date_start": start_date,
            "date_end": end_date,
        }
        try:
            res = await zoho._request("GET", "/bills", api="inventory", params=params)
            bills = res.get("bills", [])
            if not bills:
                break
            bills_list.extend(bills)
            if len(bills) < 200:
                break
            page += 1
            await asyncio.sleep(0.3)
        except Exception as exc:
            if "rate limit" in str(exc).lower() or "429" in str(exc):
                print(f"Rate limited on Bills page {page}. Waiting 60s...")
                await asyncio.sleep(60)
            else:
                raise

    print(f"Total Zoho Bills fetched: {len(bills_list)}")

    mismatches = []
    matches = []
    unmatched_bills = []

    for b in bills_list:
        b_num = str(b.get("bill_number") or "").strip()
        b_total = Decimal(str(b.get("total", 0)))
        b_status = str(b.get("status") or "").strip()

        if b_status.lower() in ("void",):
            continue

        po = po_dict.get(b_num)
        if not po:
            unmatched_bills.append(b)
            continue

        po_total = po["total"]
        diff = b_total - po_total

        if abs(diff) > Decimal("0.01"):
            mismatches.append({
                "po_number": b_num,
                "date": po["date"],
                "vendor": str(po["vendor_name"] or ""),
                "po_total": po_total,
                "bill_total": b_total,
                "diff": diff,
                "bill_status": b_status,
                "bill_id": b.get("bill_id"),
            })
        else:
            matches.append(b_num)

    print("\n" + "=" * 80)
    print(f"AUDIT SUMMARY ({start_date} to {end_date}):")
    print(f"Total POs in Zoho       : {len(po_dict)}")
    print(f"Total Active Bills      : {len(bills_list)}")
    print(f"Total Matching Bills    : {len(matches)}")
    print(f"Total Mismatched Bills  : {len(mismatches)}")
    print(f"Bills without matching PO in date range: {len(unmatched_bills)}")
    print("=" * 80)

    if mismatches:
        overbilled = [m for m in mismatches if m["diff"] > 0]
        underbilled = [m for m in mismatches if m["diff"] < 0]
        total_over = sum(m["diff"] for m in overbilled)

        print(f"\nOverbilled Count (Double-Counted Candidates): {len(overbilled)} | Total Excess: ${total_over:,.2f}")
        print(f"Underbilled Count (Partial / Credits)       : {len(underbilled)}")

        print("\n--- SAMPLE OVERBILLED (First 40) ---")
        print(f"{'PO Number':<20} {'Date':<11} {'PO Total':>10} {'Bill Total':>11} {'Diff (Over)':>12} {'Vendor'}")
        print("-" * 85)
        for m in overbilled[:40]:
            print(f"{m['po_number']:<20} {m['date']:<11} ${m['po_total']:>9.2f} ${m['bill_total']:>10.2f} +${m['diff']:>10.2f} {m['vendor'][:25]}")

        if underbilled:
            print("\n--- SAMPLE UNDERBILLED ---")
            for m in underbilled[:10]:
                print(f"{m['po_number']:<20} {m['date']:<11} ${m['po_total']:>9.2f} ${m['bill_total']:>10.2f} -${abs(m['diff']):>10.2f} {m['vendor'][:25]}")


if __name__ == "__main__":
    asyncio.run(fast_audit())
