"""
Nightly Zoho reconciliation task.

Catches dropped webhooks or failed background tasks by comparing
Zoho's ``last_modified_time`` against the local ``updated_at`` column.
Records that are newer on the Zoho side are re-enqueued for inbound sync;
records that are newer locally are re-enqueued for outbound sync.

Usage (standalone / cron)::

    python -m app.tasks.reconciliation

Or import ``run_reconciliation`` and schedule it via Celery Beat / APScheduler.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.database import async_session_factory
from app.integrations.zoho.client import ZohoClient
from app.integrations.zoho.security import generate_payload_hash
from app.integrations.zoho.sync_engine import (
    process_contact_inbound,
    process_item_inbound,
    process_order_inbound,
    sync_customer_outbound,
    sync_order_outbound,
    sync_variant_outbound,
)

logger = logging.getLogger(__name__)

# How far back to look when fetching recently-modified Zoho records.
LOOKBACK_HOURS = 25  # slightly more than 24h to handle clock-skew


async def _reconcile_items(zoho: ZohoClient, since: str) -> dict[str, int]:
    """Compare Zoho items modified since *since* with local ProductVariant."""
    from sqlalchemy import select
    from app.models.entities import ProductVariant

    stats = {"checked": 0, "enqueued_inbound": 0, "enqueued_outbound": 0}
    page = 1

    while True:
        items = await zoho.list_items(last_modified_time=since, page=page, per_page=200)
        if not items:
            break

        async with async_session_factory() as db:
            for item in items:
                stats["checked"] += 1
                zoho_item_id = str(item.get("item_id", ""))
                sku = item.get("sku", "")
                if not zoho_item_id:
                    continue

                stmt = select(ProductVariant).where(ProductVariant.zoho_item_id == zoho_item_id)
                variant = (await db.execute(stmt)).scalar_one_or_none()

                if variant is None:
                    # Item exists in Zoho but not locally — process inbound
                    await process_item_inbound({"item": item})
                    stats["enqueued_inbound"] += 1
                    continue

                remote_hash = generate_payload_hash(item)
                if remote_hash != variant.zoho_last_sync_hash:
                    # Hashes differ – decide direction by timestamp
                    zoho_modified = item.get("last_modified_time", "")
                    local_updated = variant.updated_at

                    if zoho_modified and local_updated:
                        try:
                            zoho_dt = datetime.fromisoformat(
                                zoho_modified.replace("Z", "+00:00")
                            )
                            local_dt = local_updated.replace(tzinfo=timezone.utc) if local_updated.tzinfo is None else local_updated
                            if zoho_dt > local_dt:
                                await process_item_inbound({"item": item})
                                stats["enqueued_inbound"] += 1
                            else:
                                await sync_variant_outbound(variant.id)
                                stats["enqueued_outbound"] += 1
                            continue
                        except (ValueError, TypeError):
                            pass

                    # Fallback: treat Zoho as source of truth
                    await process_item_inbound({"item": item})
                    stats["enqueued_inbound"] += 1

        if len(items) < 200:
            break
        page += 1

    return stats


async def _reconcile_contacts(zoho: ZohoClient, since: str) -> dict[str, int]:
    """Compare Zoho contacts modified since *since* with local Customer."""
    from sqlalchemy import select
    from app.models.entities import Customer

    stats = {"checked": 0, "enqueued_inbound": 0, "enqueued_outbound": 0}
    page = 1

    while True:
        contacts = await zoho.list_contacts(last_modified_time=since, page=page, per_page=200)
        if not contacts:
            break

        async with async_session_factory() as db:
            for contact in contacts:
                stats["checked"] += 1
                contact_id = str(contact.get("contact_id", ""))
                if not contact_id:
                    continue

                stmt = select(Customer).where(Customer.zoho_id == contact_id)
                customer = (await db.execute(stmt)).scalar_one_or_none()

                if customer is None:
                    await process_contact_inbound({"contact": contact})
                    stats["enqueued_inbound"] += 1
                    continue

                remote_hash = generate_payload_hash(contact)
                if remote_hash != customer.zoho_last_sync_hash:
                    zoho_modified = contact.get("last_modified_time", "")
                    local_updated = customer.updated_at
                    if zoho_modified and local_updated:
                        try:
                            zoho_dt = datetime.fromisoformat(
                                zoho_modified.replace("Z", "+00:00")
                            )
                            local_dt = local_updated.replace(tzinfo=timezone.utc) if local_updated.tzinfo is None else local_updated
                            if zoho_dt > local_dt:
                                await process_contact_inbound({"contact": contact})
                                stats["enqueued_inbound"] += 1
                            else:
                                await sync_customer_outbound(customer.id)
                                stats["enqueued_outbound"] += 1
                            continue
                        except (ValueError, TypeError):
                            pass
                    await process_contact_inbound({"contact": contact})
                    stats["enqueued_inbound"] += 1

        if len(contacts) < 200:
            break
        page += 1

    return stats


async def _reconcile_salesorders(zoho: ZohoClient, since: str) -> dict[str, int]:
    """Compare Zoho salesorders modified since *since* with local Order."""
    from sqlalchemy import select
    from app.modules.orders.models import Order

    stats = {"checked": 0, "enqueued_inbound": 0, "enqueued_outbound": 0}
    page = 1

    while True:
        orders = await zoho.list_salesorders(last_modified_time=since, page=page, per_page=200)
        if not orders:
            break

        async with async_session_factory() as db:
            for so in orders:
                stats["checked"] += 1
                so_id = str(so.get("salesorder_id", ""))
                if not so_id:
                    continue

                stmt = select(Order).where(Order.zoho_id == so_id)
                order = (await db.execute(stmt)).scalar_one_or_none()

                if order is None:
                    # Sales order exists in Zoho but not locally – inbound
                    await process_order_inbound({"salesorder": so})
                    stats["enqueued_inbound"] += 1
                    continue

                remote_hash = generate_payload_hash(so)
                if remote_hash != order.zoho_last_sync_hash:
                    zoho_modified = so.get("last_modified_time", "")
                    local_updated = order.updated_at
                    if zoho_modified and local_updated:
                        try:
                            zoho_dt = datetime.fromisoformat(
                                zoho_modified.replace("Z", "+00:00")
                            )
                            local_dt = local_updated.replace(tzinfo=timezone.utc) if local_updated.tzinfo is None else local_updated
                            if zoho_dt > local_dt:
                                await process_order_inbound({"salesorder": so})
                                stats["enqueued_inbound"] += 1
                            else:
                                await sync_order_outbound(order.id)
                                stats["enqueued_outbound"] += 1
                            continue
                        except (ValueError, TypeError):
                            pass
                    await process_order_inbound({"salesorder": so})
                    stats["enqueued_inbound"] += 1

        if len(orders) < 200:
            break
        page += 1

    return stats


# =========================================================================
# PUBLIC ENTRY POINT
# =========================================================================

async def run_reconciliation() -> dict[str, dict[str, int]]:
    """
    Run a full reconciliation sweep across items, contacts, and salesorders.

    Returns a summary dict like::

        {
            "items": {"checked": 42, "enqueued_inbound": 3, "enqueued_outbound": 1},
            "contacts": {...},
            "salesorders": {...},
        }
    """
    since_dt = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    since = since_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    logger.info("Zoho reconciliation started | since=%s", since)
    zoho = ZohoClient()

    item_stats = await _reconcile_items(zoho, since)
    contact_stats = await _reconcile_contacts(zoho, since)
    so_stats = await _reconcile_salesorders(zoho, since)

    summary = {
        "items": item_stats,
        "contacts": contact_stats,
        "salesorders": so_stats,
    }
    logger.info("Zoho reconciliation complete | summary=%s", summary)
    return summary


# Allow standalone execution: python -m app.tasks.reconciliation
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_reconciliation())
