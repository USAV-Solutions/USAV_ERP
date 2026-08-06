import asyncio
import csv
import re
import sys
from pathlib import Path

# Load env
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.integrations.zoho.client import ZohoClient

# Matches dates like 1/15, 03/17, 12/31
DATE_REGEX = re.compile(r'\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])\b')

async def main():
    client = ZohoClient()
    date_start = "2026-04-01"
    date_end = "2026-06-16"
    
    report_rows = []
    page = 1
    per_page = 200
    
    print(f"Fetching POs via API from {date_start} to {date_end}...")
    while True:
        try:
            pos = await client.list_purchase_orders(page=page, per_page=per_page)
        except Exception as e:
            print(f"Error listing POs: {e}")
            break
            
        if not pos:
            break
            
        print(f"Scanning page {page} ({len(pos)} POs)...")
        for po_summary in pos:
            po_date = po_summary.get('date', '')
            if po_date > date_end or po_date < date_start:
                continue
                
            po_id = po_summary.get('purchaseorder_id')
            if not po_id:
                continue
                
            try:
                full_po = await client.get_purchase_order(po_id)
            except Exception as e:
                print(f"Error fetching PO {po_id}: {e}")
                continue
                
            status = full_po.get('status', '').lower()
            received_status = full_po.get('received_status', '').lower()
            
            # Keep only PO with receive status unreceived
            if received_status not in ['', 'unreceived', 'to_be_received']:
                continue
            if status in ['received', 'partially_received']:
                continue
                
            # Verify again with full PO receives
            if full_po.get('receives', []) or full_po.get('purchasereceives', []):
                continue
                
            # Skip if not billed yet
            bills = full_po.get('bills', [])
            if not bills:
                continue
                
            po_number = full_po.get('purchaseorder_number', '')
            notes = full_po.get('notes', '')
            terms = full_po.get('terms', '') or full_po.get('terms_and_conditions', '')
            
            # Extract date (first match)
            date_match = DATE_REGEX.search(notes)
            if not date_match:
                date_match = DATE_REGEX.search(terms)
                
            if date_match:
                month, day = date_match.groups()
                extracted_date = f"2026-{int(month):02d}-{int(day):02d}"
                flagged = False
            else:
                extracted_date = ""
                flagged = True
                print(f"Flagged PO {po_number}: No date found in notes or terms.")
                
            for bill in bills:
                bill_id = bill.get('bill_id', '')
                bill_number = bill.get('bill_number', '')
                report_rows.append({
                    "PO ID": po_id,
                    "PO Number": po_number,
                    "Bill ID": bill_id,
                    "Bill Number": bill_number,
                    "Extracted Date": extracted_date,
                    "Notes": notes,
                    "Terms": terms,
                    "Flagged": "Yes" if flagged else "No"
                })
        
        if len(pos) < per_page:
            break
        page += 1

    # Write to CSV
    csv_path = PROJECT_ROOT / "misc" / "po_receive_report.csv"
    csv_path.parent.mkdir(exist_ok=True)
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=["PO ID", "PO Number", "Bill ID", "Bill Number", "Extracted Date", "Notes", "Terms", "Flagged"])
        writer.writeheader()
        writer.writerows(report_rows)
    print(f"Report written to {csv_path} with {len(report_rows)} rows.")

if __name__ == "__main__":
    asyncio.run(main())
