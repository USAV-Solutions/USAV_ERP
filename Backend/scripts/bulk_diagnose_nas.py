"""
Bulk Synology NAS Packing Photo Diagnostic Script using Gemini 3.5 Flash.

Scans Synology NAS directory:
'/volume1/USAV Media/Packing Shipping/Packing Photos/Packing Station 2/2026/Q2 26'
or a local folder directory.

For every image:
1. Identifies the physical item visually (even if paperwork is missing).
2. Checks for packing slip / shipping label.
3. If paperwork exists: extracts Order ID, Tracking Number, SKU, and verifies against local ERP database.
4. If paperwork is missing: marks as IGNORED_NO_PAPERWORK, but records physical item classification.
"""

import os
import sys
import glob
import json
import asyncio
import argparse
import logging
from typing import List, Dict, Any

# Ensure Backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # Pre-import to resolve circular dependencies in app.models.__init__
from app.core.database import async_session_factory
from app.modules.orders.diagnose import diagnose_packaging_photo_bytes, AIDiagnosticResponse
from app.core.synology import list_synology_files, download_synology_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bulk_diagnose")

DEFAULT_NAS_FOLDER = "/USAV Media/Packing Shipping/Packing Photos/Packing Station 2/2026/Q2 26"


async def process_image_file(
    file_path: str,
    image_bytes: bytes,
    db_session=None,
) -> Dict[str, Any]:
    filename = os.path.basename(file_path)
    res: AIDiagnosticResponse = await diagnose_packaging_photo_bytes(
        image_bytes=image_bytes,
        filename=filename,
        mime_type="image/jpeg",
        db=db_session,
    )

    # Classification logic
    if not res.is_valid_packing_photo:
        status_label = "IGNORED_NO_PAPERWORK"
        action_summary = f"No slip/label found. Physical Item Identified: '{res.detected_physical_item}'"
    else:
        status_label = res.status
        action_summary = f"Order: {res.order_id} | Tracking: {res.tracking_number} | Item: '{res.detected_physical_item}'"

    logger.info(f"[{status_label}] {filename} ({res.latency_ms}ms) -> {action_summary}")

    return {
        "file_path": file_path,
        "filename": filename,
        "latency_ms": res.latency_ms,
        "is_valid_packing_photo": res.is_valid_packing_photo,
        "platform": res.platform,
        "order_id": res.order_id,
        "tracking_number": res.tracking_number,
        "sku_on_slip": res.sku_on_slip,
        "detected_physical_item": res.detected_physical_item,
        "expected_erp_item": res.expected_erp_item,
        "status": status_label,
        "message": res.message,
    }


async def main():
    parser = argparse.ArgumentParser(description="Bulk NAS AI Diagnostic Engine")
    parser.add_argument("--folder", type=str, default=DEFAULT_NAS_FOLDER, help="NAS or local folder path")
    parser.add_argument("--local", action="store_true", help="Treat folder as local filesystem path")
    parser.add_argument("--limit", type=int, default=50, help="Max files to process")
    args = parser.parse_args()

    print("=" * 80)
    print("  USAV ERP - SYNOLOGY NAS BULK AI PACKAGING DIAGNOSTIC TOOL")
    print(f"  Target Folder: {args.folder}")
    print(f"  Max Files Limit: {args.limit}")
    print("=" * 80)

    image_tasks = []

    if args.local or os.path.isdir(args.folder):
        print(f"[Mode: Local Filesystem] Scanning directory {args.folder}...")
        exts = ["*.jpg", "*.jpeg", "*.JPG", "*.JPEG", "*.png", "*.PNG"]
        local_files = []
        for ext in exts:
            local_files.extend(glob.glob(os.path.join(args.folder, ext)))
        local_files = sorted(local_files)[:args.limit]

        for path in local_files:
            try:
                with open(path, "rb") as f:
                    b = f.read()
                image_tasks.append((path, b))
            except Exception as e:
                logger.error(f"Failed to read local file {path}: {e}")
    else:
        print(f"[Mode: Synology FileStation WebAPI] Connecting to NAS...")
        try:
            nas_files = list_synology_files(args.folder)
            nas_files = [f for f in nas_files if f.lower().endswith((".jpg", ".jpeg", ".png"))][:args.limit]
            print(f"Found {len(nas_files)} image files on Synology NAS.")
            for path in nas_files:
                try:
                    b = download_synology_file(path)
                    image_tasks.append((path, b))
                except Exception as e:
                    logger.error(f"Failed to download {path} from Synology NAS: {e}")
        except Exception as e:
            print(f"Synology NAS connection note: {e}")
            print("To run against NAS via WebAPI, ensure SYNOLOGY_NAS_IP, SYNOLOGY_NAS_USER, SYNOLOGY_NAS_PASSWORD are set in .env.")
            print("Alternatively, mount NAS share to a drive letter or pass --folder <local_path> --local.")
            return

    if not image_tasks:
        print("No image files found to process.")
        return

    print(f"\nProcessing {len(image_tasks)} packaging photos with Gemini 3.5 Flash...\n")

    results = []
    async with async_session_factory() as db:
        for file_path, img_bytes in image_tasks:
            res = await process_image_file(file_path, img_bytes, db_session=db)
            results.append(res)

    # Summary report
    valid_count = sum(1 for r in results if r["is_valid_packing_photo"])
    ignored_count = len(results) - valid_count

    output_report = "nas_bulk_diagnostic_report.json"
    with open(output_report, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 80)
    print("                      DIAGNOSTIC PROCESSING SUMMARY")
    print("=" * 80)
    print(f"Total Photos Processed : {len(results)}")
    print(f"Valid Packing Photos   : {valid_count} (Slip & Label Detected)")
    print(f"Ignored Photos         : {ignored_count} (Parts-only, no paperwork)")
    print(f"Detailed Report Saved  : {output_report}")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
