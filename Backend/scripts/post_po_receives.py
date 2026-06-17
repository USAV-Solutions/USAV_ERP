import asyncio
import csv
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.integrations.zoho.client import ZohoClient

def _clean(val):
    return str(val or "").strip()

def _build_po_line_to_bill_line_map(bills: list[dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for bill in bills:
        for line in bill.get("line_items", []):
            po_line_id = _clean(line.get("purchaseorder_item_id"))
            bill_line_id = _clean(line.get("line_item_id"))
            if po_line_id and bill_line_id and po_line_id not in mapping:
                mapping[po_line_id] = bill_line_id
    return mapping

def _build_receive_payload(
    full_po: dict,
    receive_date: str,
    notes: str,
    bill_line_item_by_po_line_id: dict[str, str],
):
    po_id = _clean(full_po.get("purchaseorder_id"))
    line_items = []
    for line in full_po.get("line_items") or []:
        item_id = _clean(line.get("item_id"))
        line_item_id = _clean(line.get("line_item_id") or line.get("purchaseorder_item_id"))
        
        qty_raw = line.get("quantity") or line.get("quantity_received") or 0
        try:
            qty = float(qty_raw)
        except Exception:
            qty = 0.0
            
        if not item_id or qty <= 0:
            continue
            
        payload_line = {
            "item_id": item_id,
            "quantity": qty,
            "quantity_received": qty,
        }
        if line_item_id:
            payload_line["line_item_id"] = line_item_id
            bill_line_item_id = _clean(bill_line_item_by_po_line_id.get(line_item_id))
            if bill_line_item_id:
                payload_line["bill_line_item_id"] = bill_line_item_id
        line_items.append(payload_line)

    if not line_items:
        return None

    payload = {
        "purchaseorder_id": po_id,
        "line_items": line_items,
        "date": receive_date,
        "notes": notes
    }
    return payload

async def main():
    csv_path = PROJECT_ROOT / "misc" / "po_receive_report.csv"
    if not csv_path.exists():
        print(f"CSV not found at {csv_path}. Please run generate_po_receive_report.py first.")
        return
        
    client = ZohoClient()
    
    # Read CSV and group by PO ID
    po_data = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Flagged", "No").lower() == "yes":
                continue
                
            po_id = row["PO ID"]
            if po_id not in po_data:
                po_data[po_id] = {
                    "po_number": row["PO Number"],
                    "receive_date": row["Extracted Date"],
                    "bill_ids": set(),
                }
            po_data[po_id]["bill_ids"].add(row["Bill ID"])
            
    if not po_data:
        print("No unflagged POs found to process.")
        return
        
    for po_id, data in po_data.items():
        po_number = data["po_number"]
        print(f"Processing PO {po_number} (ID: {po_id})")
        
        try:
            full_po = await client.get_purchase_order(po_id)
        except Exception as e:
            print(f"Failed to fetch PO {po_id}: {e}")
            continue
            
        bills = []
        for bill_id in data["bill_ids"]:
            try:
                result = await client.get_bill(bill_id)
                if result:
                    bills.append(result)
            except Exception as e:
                print(f"Failed to fetch bill {bill_id}: {e}")
                
        if not bills:
            print(f"No bills found for PO {po_number}, skipping.")
            continue
            
        mapping = _build_po_line_to_bill_line_map(bills)
        notes = "Auto-received from billed quantities."
        
        payload = _build_receive_payload(
            full_po=full_po,
            receive_date=data["receive_date"],
            notes=notes,
            bill_line_item_by_po_line_id=mapping
        )
        
        if not payload:
            print(f"Could not build receive payload for PO {po_number}")
            continue
            
        try:
            print(f"Posting receive for PO {po_number}...")
            await client._request(
                "POST", 
                "/purchasereceives", 
                api="inventory", 
                params={"purchaseorder_id": po_id}, 
                data={"JSONString": json.dumps(payload)}
            )
            print(f"Successfully received PO {po_number}.")
        except Exception as e:
            print(f"Failed to post receive for PO {po_number}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
