import sys
import os
import csv
import urllib.request
import re

def import_tracking_from_url(sheet_url: str):
    """
    Import tracking numbers from a Google Sheets URL.
    Converts the standard view URL to a CSV export URL automatically.
    """
    # Convert standard Google Sheets URL to CSV export URL
    # Format: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/export?format=csv
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    if not match:
        print("❌ Invalid Google Sheets URL format.")
        return
    
    spreadsheet_id = match.group(1)
    
    # Check if a specific sheet (gid) is selected
    gid_match = re.search(r"[#&]gid=([0-9]+)", sheet_url)
    gid_param = f"&gid={gid_match.group(1)}" if gid_match else ""
    
    csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv{gid_param}"
    print(f"🔗 Converting link to CSV export URL: {csv_url}")
    
    try:
        req = urllib.request.Request(
            csv_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            csv_data = response.read().decode('utf-8').splitlines()
    except Exception as e:
        print(f"❌ Failed to fetch Google Sheet: {e}")
        return

    reader = csv.reader(csv_data)
    rows = list(reader)
    if not rows:
        print("⚠️ No data found in the spreadsheet.")
        return
        
    # Find header row
    header_idx = -1
    for i, row in enumerate(rows[:5]):  # Look in the first 5 rows
        row_lower = [cell.lower().strip() for cell in row]
        if "order number" in row_lower and "tracking" in row_lower:
            header_idx = i
            headers = row_lower
            break
            
    if header_idx == -1:
        print("❌ Could not find header row with 'Order Number' and 'Tracking' columns.")
        return
        
    order_idx = headers.index("order number")
    tracking_idx = headers.index("tracking")
    platform_idx = headers.index("platform") if "platform" in headers else -1
    
    scanned_count = 0
    skipped_fba = 0
    skipped_empty = 0
    
    print("\n📦 Processing rows...")
    is_fba_section = False
    
    for row_num, row in enumerate(rows[header_idx + 1:], header_idx + 2):
        # Skip empty rows
        if not any(cell.strip() for cell in row):
            continue
            
        row_str = " ".join(row).lower()
        
        # Detect the start of FBA section
        # Stop or flag once we hit FBA keywords in a separator/header row
        if "fba" in row_str and len([c for c in row if c.strip()]) <= 2:
            is_fba_section = True
            print(f"ℹ️ Line {row_num}: Detected FBA section divider. Skipping all rows below.")
            break
            
        if is_fba_section:
            skipped_fba += 1
            continue
            
        platform = row[platform_idx].strip() if platform_idx != -1 else ""
        order_num = row[order_idx].strip()
        tracking = row[tracking_idx].strip()
        
        # Double check if platform itself is labeled FBA
        if "fba" in platform.lower() or "fba" in order_num.lower():
            skipped_fba += 1
            continue
            
        if not tracking or tracking.strip() == "-" or tracking.strip() == "—":
            skipped_empty += 1
            continue
            
        # Clean tracking number (remove spaces)
        tracking_clean = re.sub(r"\s+", "", tracking)
        
        print(f"✅ Line {row_num}: Platform={platform} | Order={order_num} | Tracking={tracking_clean}")
        scanned_count += 1
        
    print("\n--- Summary ---")
    print(f"Total tracking numbers found & imported: {scanned_count}")
    print(f"Skipped FBA rows: {skipped_fba}")
    print(f"Skipped empty tracking rows: {skipped_empty}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_tracking_from_sheet.py <google_sheets_url>")
        sys.exit(1)
    import_tracking_from_url(sys.argv[1])
