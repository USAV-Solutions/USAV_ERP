import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, func, Date
from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient
from app.models.purchasing import PurchaseOrder, PurchaseDeliverStatus


async def main():
    parser = argparse.ArgumentParser(description="Compare POs between DB and Zoho.")
    parser.add_argument("startdate", help="Start date (YYYY-MM-DD)")
    parser.add_argument("enddate", help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    try:
        start_date = datetime.strptime(args.startdate, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.enddate, "%Y-%m-%d").date()
    except ValueError:
        print("Dates must be in YYYY-MM-DD format.")
        sys.exit(1)

    print(f"Fetching DB POs between {start_date} and {end_date} (GMT-8)...")
    db_pos = {}
    async with async_session_factory() as session:
        # Use created_at converted to GMT-8
        stmt = select(PurchaseOrder).where(
            func.cast(func.timezone('-08:00', PurchaseOrder.created_at), Date) >= start_date,
            func.cast(func.timezone('-08:00', PurchaseOrder.created_at), Date) <= end_date
        )
        result = await session.execute(stmt)
        for po in result.scalars():
            db_pos[po.po_number] = po

    print(f"Found {len(db_pos)} POs in DB.")

    print(f"Fetching Zoho POs between {args.startdate} and {args.enddate}...")
    client = ZohoClient()
    zoho_pos = {}
    page = 1
    per_page = 200
    while True:
        try:
            pos = await client.list_purchase_orders(
                date_start=args.startdate,
                date_end=args.enddate,
                page=page,
                per_page=per_page
            )
        except Exception as e:
            print(f"Error fetching Zoho POs: {e}")
            break

        if not pos:
            break

        for po in pos:
            po_num = po.get('purchaseorder_number')
            if po_num:
                zoho_pos[po_num] = po

        if len(pos) < per_page:
            break
        page += 1

    print(f"Found {len(zoho_pos)} POs in Zoho.")

    missing_in_db = []
    missing_in_zoho = []
    status_mismatch = []

    all_po_nums = set(db_pos.keys()).union(set(zoho_pos.keys()))

    for po_num in all_po_nums:
        in_db = po_num in db_pos
        in_zoho = po_num in zoho_pos

        if in_db and not in_zoho:
            missing_in_zoho.append(po_num)
        elif in_zoho and not in_db:
            missing_in_db.append(po_num)

        if in_db and in_zoho:
            db_po = db_pos[po_num]
            zoho_po = zoho_pos[po_num]

            zoho_status = zoho_po.get('status', '').lower()
            zoho_received_status = zoho_po.get('received_status', '').lower()

            zoho_is_received = False
            if zoho_status in ['received', 'partially_received']:
                zoho_is_received = True
            elif zoho_received_status in ['received', 'partially_received']:
                zoho_is_received = True
            elif 'receive' in zoho_status or 'receive' in zoho_received_status:
                zoho_is_received = True

            db_is_delivered = (db_po.deliver_status == PurchaseDeliverStatus.DELIVERED)

            if zoho_is_received and not db_is_delivered:
                status_mismatch.append({
                    "po_number": po_num,
                    "zoho_status": zoho_status,
                    "zoho_received_status": zoho_received_status,
                    "db_deliver_status": db_po.deliver_status.value
                })

    report_path = PROJECT_ROOT / "misc" / f"po_comparison_report_{args.startdate}_to_{args.enddate}.txt"
    report_path.parent.mkdir(exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"PO Comparison Report ({args.startdate} to {args.enddate})\n")
        f.write("=" * 50 + "\n\n")

        f.write(f"Total in DB: {len(db_pos)}\n")
        f.write(f"Total in Zoho: {len(zoho_pos)}\n\n")

        f.write("--- Missing in DB (Present in Zoho) ---\n")
        if missing_in_db:
            for p in sorted(missing_in_db):
                f.write(f"{p}\n")
        else:
            f.write("None\n")
        f.write("\n")

        f.write("--- Missing in Zoho (Present in DB) ---\n")
        if missing_in_zoho:
            for p in sorted(missing_in_zoho):
                f.write(f"{p}\n")
        else:
            f.write("None\n")
        f.write("\n")

        f.write("--- Status Mismatch (Received in Zoho, Not Delivered in DB) ---\n")
        if status_mismatch:
            for item in sorted(status_mismatch, key=lambda x: x['po_number']):
                f.write(
                    f"{item['po_number']} | Zoho: {item['zoho_status']}/{item['zoho_received_status']} | DB: {item['db_deliver_status']}\n")
        else:
            f.write("None\n")

    print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
