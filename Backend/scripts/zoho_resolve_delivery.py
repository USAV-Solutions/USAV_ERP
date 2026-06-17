#!/usr/bin/env python
"""
Resolve Zoho delivery:
1. Fetch POs from Jan 1 to May 1 2026.
2. Filter for to_be_received and to_be_billed.
3. Extract received dates from notes and terms.
4. Output CSV and sync to Zoho (Create bill -> create receive).
"""

import asyncio
import csv
import json
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from dateutil import parser
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT.parent / ".env")

from app.integrations.zoho.client import ZohoClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATE_PATTERN = re.compile(
    r'\b(?:'
    r'\d{4}-\d{1,2}-\d{1,2}|'
    r'\d{1,2}/\d{1,2}(?:/\d{2,4})?|'
    r'\d{1,2}[,\s]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[,\s]+\d{4}|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[,\s]+\d{1,2}[,\s]+\d{2,4}|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[,\s]+\d{1,2}'
    r')\b',
    re.IGNORECASE
)

def extract_dates_from_text(text: str, order_date: date) -> list[date]:
    if not text:
        return []
    matches = DATE_PATTERN.findall(text)
    extracted = []
    for m in matches:
        try:
            d = parser.parse(m, default=datetime(order_date.year, order_date.month, order_date.day))
            extracted.append(d.date())
        except Exception:
            pass
    return extracted

def _enrich_bill_payload_with_po_lines(remote_po: dict[str, Any], bill_payload: dict[str, Any]) -> dict[str, Any]:
    purchaseorder_id = bill_payload.get("purchaseorder_id")
    po_lines = remote_po.get("line_items") or []
    line_items: list[dict[str, Any]] = []
    for line in po_lines:
        if not isinstance(line, dict):
            continue
        po_item_id = line.get("purchaseorder_item_id") or line.get("line_item_id")
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
            if line.get(key) is not None:
                payload_line[key] = line.get(key)
        line_items.append(payload_line)

    enriched = dict(bill_payload)
    enriched["line_items"] = line_items
    if remote_po.get("branch_id"):
        enriched["branch_id"] = remote_po.get("branch_id")
    if remote_po.get("location_id"):
        enriched["location_id"] = remote_po.get("location_id")
    return enriched

async def create_bill_for_po(client: ZohoClient, full_po: dict[str, Any], po_number: str, bill_date: str) -> dict[str, Any]:
    po_id = full_po.get("purchaseorder_id")
    vendor_id = full_po.get("vendor_id")
    
    payload = {
        "purchaseorder_id": po_id,
        "vendor_id": vendor_id,
        "bill_number": po_number,
        "reference_number": po_number,
        "date": bill_date,
        "due_date": bill_date,
        "payment_terms": 1, # Due on receipt
        "currency_code": full_po.get("currency_code", "USD"),
    }
    payload = _enrich_bill_payload_with_po_lines(full_po, payload)
    
    request_body = {"JSONString": json.dumps(payload)}
    result = await client._request("POST", "/bills", api="inventory", data=request_body)
    return result.get("bill", {})

async def create_receive_for_po(client: ZohoClient, full_po: dict[str, Any], receive_number: str, receive_date: str, notes: str, bill_line_mapping: dict[str, str]) -> dict[str, Any]:
    po_id = full_po.get("purchaseorder_id")
    line_items = []
    
    for line in full_po.get("line_items", []):
        item_id = line.get("item_id")
        line_item_id = line.get("line_item_id") or line.get("purchaseorder_item_id")
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
            if line_item_id in bill_line_mapping:
                payload_line["bill_line_item_id"] = bill_line_mapping[line_item_id]
        line_items.append(payload_line)

    payload = {
        "purchaseorder_id": po_id,
        "receive_number": receive_number,
        "date": receive_date,
        "notes": notes,
        "line_items": line_items,
    }
    
    request_body = {"JSONString": json.dumps(payload)}
    result = await client._request("POST", "/purchasereceives", api="inventory", params={"purchaseorder_id": po_id}, data=request_body)
    rec = result.get("purchasereceive") or result.get("purchase_receive") or {}
    return rec

async def main():
    client = ZohoClient()
    start_date = date(2026, 1, 1)
    end_date = date(2026, 5, 1)
    
    logger.info("Fetching POs...")
    page = 1
    target_pos = []
    
    while True:
        logger.info(f"Fetching page {page}")
        pos = await client.list_purchase_orders(page=page, per_page=200)
        if not pos:
            break
            
        for po in pos:
            po_date_str = po.get("date")
            if not po_date_str:
                continue
            try:
                po_date = date.fromisoformat(po_date_str)
            except Exception:
                continue
                
            if po_date < start_date:
                # Assuming descending order, we can break completely? Wait, just to be safe, continue to check all in page
                pass
            
            if start_date <= po_date <= end_date:
                if po.get("received_status") == "to_be_received" and po.get("billed_status") == "to_be_billed":
                    target_pos.append(po)
        
        last_po_date_str = pos[-1].get("date")
        if last_po_date_str:
            try:
                last_po_date = date.fromisoformat(last_po_date_str)
                if last_po_date < start_date:
                    break
            except Exception:
                pass
        
        page += 1

    logger.info(f"Found {len(target_pos)} POs matching criteria.")
    
    report_rows = []
    
    for po in target_pos:
        po_id = po.get("purchaseorder_id")
        po_number = po.get("purchaseorder_number")
        order_date_str = po.get("date")
        order_date = date.fromisoformat(order_date_str)
        
        full_po = await client.get_purchase_order(po_id)
        notes = full_po.get("notes", "")
        terms = full_po.get("terms", "")
        
        combined_text = f"{notes} {terms}"
        possible_dates = extract_dates_from_text(combined_text, order_date)
        
        if len(possible_dates) == 1:
            received_date = possible_dates[0]
            extracted_date_str = received_date.isoformat()
        elif len(possible_dates) > 1:
            valid_dates = [d for d in possible_dates if d >= order_date]
            if valid_dates:
                received_date = min(valid_dates, key=lambda d: d - order_date)
            else:
                received_date = max(possible_dates)
            extracted_date_str = received_date.isoformat()
        else:
            extracted_date_str = ""
            
        report_rows.append({
            "po_id": po_id,
            "po_number": po_number,
            "order_date": order_date_str,
            "received_status": po.get("received_status"),
            "billed_status": po.get("billed_status"),
            "extracted_received_date": extracted_date_str,
            "notes": notes,
            "terms": terms,
            "full_po": full_po, # for later sync
        })
        
    csv_path = PROJECT_ROOT / "scripts" / "zoho_delivery_report.csv"
    csv_path.parent.mkdir(exist_ok=True, parents=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["po_id", "po_number", "order_date", "received_status", "billed_status", "extracted_received_date", "notes", "terms"])
        writer.writeheader()
        for row in report_rows:
            writer.writerow({k: v for k, v in row.items() if k != "full_po"})
            
    logger.info(f"Report saved to {csv_path}")
    
    # Sync Step
    for row in report_rows:
        if not row["extracted_received_date"]:
            logger.info(f"Skipping PO {row['po_number']} - no received date extracted.")
            continue
            
        po_number = row["po_number"]
        order_date_str = row["order_date"]
        received_date_str = row["extracted_received_date"]
        full_po = row["full_po"]
        
        logger.info(f"Syncing PO {po_number}...")
        
        try:
            bill = await create_bill_for_po(client, full_po, po_number, order_date_str)
            logger.info(f"Created bill for PO {po_number}")
            
            # Map PO lines to Bill lines
            bill_line_mapping = {}
            for line in bill.get("line_items", []):
                po_item_id = line.get("purchaseorder_item_id")
                bill_line_id = line.get("line_item_id")
                if po_item_id and bill_line_id:
                    bill_line_mapping[po_item_id] = bill_line_id
                    
            receive_number = f"REC-{po_number}"
            await create_receive_for_po(client, full_po, receive_number, received_date_str, "Extracted from PO notes/terms", bill_line_mapping)
            logger.info(f"Created receive {receive_number} for PO {po_number}")
        except Exception as e:
            logger.error(f"Failed to sync PO {po_number}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
