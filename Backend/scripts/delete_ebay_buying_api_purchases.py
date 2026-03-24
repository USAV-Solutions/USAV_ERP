#!/usr/bin/env python
"""Delete purchases imported from eBay Buying API.

Workflow:
1) Scan all purchase orders where source == EBAY_BUYING_API
2) Scan related line items and vendors
3) Delete sequentially: line items -> vendors -> purchase orders

Notes:
- Vendor has RESTRICT FK from purchase_order, so vendor delete before purchase order
  will generally skip referenced vendors. The script runs a second vendor cleanup pass
  after purchase-order deletion so referenced vendors can be removed if unreferenced.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.models.purchasing import PurchaseOrder, PurchaseOrderItem, Vendor


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete purchase orders imported via source=EBAY_BUYING_API",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and print what would be deleted without deleting.",
    )
    return parser.parse_args()


async def _scan_targets() -> tuple[list[PurchaseOrder], dict[int, int], list[Vendor]]:
    async with async_session_factory() as session:
        po_rows = (
            await session.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.source == "EBAY_BUYING_API")
                .order_by(PurchaseOrder.id.asc())
            )
        ).scalars().all()

        po_ids = [int(po.id) for po in po_rows]
        vendor_ids = sorted({int(po.vendor_id) for po in po_rows})

        item_count_by_po: dict[int, int] = {}
        if po_ids:
            count_rows = await session.execute(
                select(PurchaseOrderItem.purchase_order_id, func.count(PurchaseOrderItem.id))
                .where(PurchaseOrderItem.purchase_order_id.in_(po_ids))
                .group_by(PurchaseOrderItem.purchase_order_id)
            )
            item_count_by_po = {int(po_id): int(count) for po_id, count in count_rows.all()}

        vendor_rows: list[Vendor] = []
        if vendor_ids:
            vendor_rows = (
                await session.execute(
                    select(Vendor).where(Vendor.id.in_(vendor_ids)).order_by(Vendor.id.asc())
                )
            ).scalars().all()

        return po_rows, item_count_by_po, vendor_rows


async def _delete_targets(po_ids: list[int], vendor_ids: list[int]) -> None:
    async with async_session_factory() as session:
        # Step 1: delete line items for targeted purchase orders.
        deleted_items = await session.execute(
            delete(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id.in_(po_ids))
        )
        await session.commit()

        # Step 2: vendor delete attempt before purchase-order delete (requested sequence).
        # This generally deletes only vendors already unreferenced by purchase_order.
        vendor_delete_stmt = delete(Vendor).where(
            Vendor.id.in_(vendor_ids),
            ~Vendor.purchase_orders.any(),
        )
        deleted_vendors_pre = await session.execute(vendor_delete_stmt)
        await session.commit()

        # Step 3: delete purchase orders.
        deleted_pos = await session.execute(delete(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids)))
        await session.commit()

        # Final vendor cleanup pass after purchase-order deletion.
        deleted_vendors_post = await session.execute(vendor_delete_stmt)
        await session.commit()

        print(f"Deleted line items: {deleted_items.rowcount or 0}")
        print(f"Deleted vendors (pre-PO pass): {deleted_vendors_pre.rowcount or 0}")
        print(f"Deleted purchase orders: {deleted_pos.rowcount or 0}")
        print(f"Deleted vendors (post-PO pass): {deleted_vendors_post.rowcount or 0}")


async def main() -> None:
    args = _parse_args()

    po_rows, item_count_by_po, vendor_rows = await _scan_targets()
    if not po_rows:
        print("No purchase orders found with source=EBAY_BUYING_API.")
        return

    po_ids = [int(po.id) for po in po_rows]
    vendor_ids = sorted({int(po.vendor_id) for po in po_rows})
    total_items = sum(item_count_by_po.values())

    print("Scan results:")
    print(f"- Purchase orders: {len(po_rows)}")
    print(f"- Line items: {total_items}")
    print(f"- Vendors: {len(vendor_rows)}")
    print("Sample purchase orders (first 20):")
    for po in po_rows[:20]:
        count = item_count_by_po.get(int(po.id), 0)
        print(
            f"  PO id={po.id} po_number={po.po_number} vendor_id={po.vendor_id} "
            f"order_date={po.order_date} items={count}"
        )

    if args.dry_run:
        print("Dry run enabled. No deletions were executed.")
        return

    await _delete_targets(po_ids, vendor_ids)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
