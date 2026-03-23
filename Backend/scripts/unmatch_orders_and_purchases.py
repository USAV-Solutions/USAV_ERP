#!/usr/bin/env python
# pyright: reportMissingImports=false
"""Bulk-unmatch orders and purchasing line items.

Purpose:
- Clear variant links before catalog reset/import so transactional rows do not keep stale matches.

What is updated:
- order_item.variant_id -> NULL
- order_item.allocated_inventory_id -> NULL
- order_item.status -> UNMATCHED
- purchase_order_item.variant_id -> NULL
- purchase_order_item.status -> UNMATCHED

Safety:
- Supports --dry-run for preview without commit.
- Supports --since-date to limit scope.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy import and_, or_, select, update

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.models import PurchaseOrder, PurchaseOrderItem, PurchaseOrderItemStatus
from app.modules.orders.models import Order, OrderItem, OrderItemStatus


def _parse_since_date(raw: str | None) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw)


async def _collect_order_item_ids(
    since_date: date | None,
    include_terminal_statuses: bool,
) -> list[int]:
    async with async_session_factory() as db:
        filters = [OrderItem.variant_id.is_not(None)]

        if not include_terminal_statuses:
            filters.append(
                OrderItem.status.in_([OrderItemStatus.MATCHED, OrderItemStatus.ALLOCATED])
            )

        if since_date is not None:
            since_dt = datetime.combine(since_date, time.min)
            filters.append(
                or_(
                    Order.ordered_at >= since_dt,
                    Order.created_at >= since_dt,
                )
            )

        stmt = (
            select(OrderItem.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(and_(*filters))
        )
        return [int(x) for x in (await db.execute(stmt)).scalars().all()]


async def _collect_purchase_item_ids(
    since_date: date | None,
    include_received_items: bool,
) -> list[int]:
    async with async_session_factory() as db:
        filters = [PurchaseOrderItem.variant_id.is_not(None)]

        if not include_received_items:
            filters.append(PurchaseOrderItem.status == PurchaseOrderItemStatus.MATCHED)

        if since_date is not None:
            filters.append(PurchaseOrder.order_date >= since_date)

        stmt = (
            select(PurchaseOrderItem.id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .where(and_(*filters))
        )
        return [int(x) for x in (await db.execute(stmt)).scalars().all()]


async def _apply_updates(
    order_item_ids: list[int],
    purchase_item_ids: list[int],
    dry_run: bool,
) -> None:
    async with async_session_factory() as db:
        if order_item_ids:
            await db.execute(
                update(OrderItem)
                .where(OrderItem.id.in_(order_item_ids))
                .values(
                    variant_id=None,
                    allocated_inventory_id=None,
                    status=OrderItemStatus.UNMATCHED,
                    matching_notes="Bulk reset: unmatched before catalog/database reset",
                )
            )

        if purchase_item_ids:
            await db.execute(
                update(PurchaseOrderItem)
                .where(PurchaseOrderItem.id.in_(purchase_item_ids))
                .values(
                    variant_id=None,
                    status=PurchaseOrderItemStatus.UNMATCHED,
                )
            )

        if dry_run:
            await db.rollback()
            print("Dry run complete. No changes committed.")
        else:
            await db.commit()
            print("Changes committed.")


def _print_preview(order_item_ids: list[int], purchase_item_ids: list[int]) -> None:
    print(f"Order items to unmatch: {len(order_item_ids)}")
    if order_item_ids:
        print(f"Order item sample ids: {order_item_ids[:20]}")

    print(f"Purchase order items to unmatch: {len(purchase_item_ids)}")
    if purchase_item_ids:
        print(f"Purchase item sample ids: {purchase_item_ids[:20]}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk unmatch order and purchase line items")
    parser.add_argument(
        "--since-date",
        default=None,
        help="Optional ISO date filter (YYYY-MM-DD). Applies to orders and purchase orders.",
    )
    parser.add_argument(
        "--include-terminal-order-statuses",
        action="store_true",
        help="Also unmatch SHIPPED/CANCELLED order items when variant_id is set.",
    )
    parser.add_argument(
        "--include-received-purchase-items",
        action="store_true",
        help="Also unmatch RECEIVED purchase items when variant_id is set.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    since_date = _parse_since_date(args.since_date)

    order_item_ids = await _collect_order_item_ids(
        since_date=since_date,
        include_terminal_statuses=args.include_terminal_order_statuses,
    )
    purchase_item_ids = await _collect_purchase_item_ids(
        since_date=since_date,
        include_received_items=args.include_received_purchase_items,
    )

    _print_preview(order_item_ids, purchase_item_ids)

    await _apply_updates(
        order_item_ids=order_item_ids,
        purchase_item_ids=purchase_item_ids,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())
