"""
Remediation script for misclassified eBay Dragon orders.

Identifies orders previously misclassified as EBAY_USAV from ShipStation CSV imports
that actually belong to eBay Dragon, using the eBay Dragon Fulfillment API.

Usage:
    # Dry run (safe, read-only preview):
    python scripts/remediate_ebay_dragon_orders.py --dry-run

    # Execute changes:
    python scripts/remediate_ebay_dragon_orders.py --execute

    # Optional flags:
    --limit 50           # limit number of orders to check
    --db-host 100.87.193.67  # specify DB host
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Backend"))
from app.core.config import settings
from app.integrations.ebay.client import EbayClient
from app.integrations.zoho.client import ZohoClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediate_dragon")


async def build_db_pool(db_host: str, db_port: int, db_user: str, db_pass: str, db_name: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_pass,
        database=db_name,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )


async def main():
    parser = argparse.ArgumentParser(description="Remediate misclassified eBay Dragon orders.")
    parser.add_argument("--execute", action="store_true", help="Execute changes in DB and Zoho (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview changes without modifying DB")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of orders to process")
    parser.add_argument("--db-host", type=str, default="100.87.193.67", help="Database host (default: 100.87.193.67)")
    parser.add_argument("--db-port", type=int, default=5432, help="Database port")
    parser.add_argument("--db-user", type=str, default="postgres", help="Database user")
    parser.add_argument("--db-pass", type=str, default="devpassword123", help="Database password")
    parser.add_argument("--db-name", type=str, default="inventory_system", help="Database name")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of concurrent eBay API queries")

    args = parser.parse_args()
    is_dry_run = not args.execute

    mode_label = "DRY RUN (Preview Only)" if is_dry_run else "EXECUTE (Modifying Database & Zoho)"
    logger.info("=" * 60)
    logger.info(f"Starting eBay Dragon Order Remediation - Mode: {mode_label}")
    logger.info(f"Connecting to DB: {args.db_host}:{args.db_port}/{args.db_name}")
    logger.info("=" * 60)

    # Initialize eBay Dragon client
    dragon_client = EbayClient(
        store_name="DRAGON",
        app_id=settings.ebay_app_id,
        cert_id=settings.ebay_cert_id,
        refresh_token=settings.ebay_refresh_token_dragon,
        sandbox=settings.ebay_sandbox,
    )

    if not dragon_client.is_configured:
        logger.error("eBay Dragon credentials not fully configured in settings (.env). Aborting.")
        return

    zoho_client = ZohoClient()

    pool = await build_db_pool(args.db_host, args.db_port, args.db_user, args.db_pass, args.db_name)

    try:
        async with pool.acquire() as conn:
            # Fetch orders candidate for remediation
            query = """
                SELECT id, external_order_id, external_order_number, platform, source, zoho_id
                FROM orders
                WHERE platform = 'EBAY_USAV' AND source = 'SHIPSTATION_CSV'
                ORDER BY id ASC
            """
            if args.limit:
                query += f" LIMIT {args.limit}"

            orders = await conn.fetch(query)
            logger.info(f"Found {len(orders)} EBAY_USAV SHIPSTATION_CSV orders to verify.")

            # Cache existing Dragon orders to identify duplicate pairs quickly
            existing_dragon_rows = await conn.fetch("""
                SELECT id, external_order_id, external_order_number, zoho_id
                FROM orders
                WHERE platform = 'EBAY_DRAGON'
            """)
            existing_dragon_map = {
                r["external_order_number"] or r["external_order_id"]: r
                for r in existing_dragon_rows
            }
            logger.info(f"Found {len(existing_dragon_map)} existing EBAY_DRAGON orders in database for duplicate detection.")

        # Concurrency semaphore for eBay API requests
        semaphore = asyncio.Semaphore(args.concurrency)

        async def verify_order(order_row):
            order_num = order_row["external_order_number"] or order_row["external_order_id"]
            if not order_num:
                return order_row, False

            # If it already exists in existing_dragon_map, we know it's Dragon!
            if order_num in existing_dragon_map:
                return order_row, True

            async with semaphore:
                try:
                    res = await dragon_client.get_order(order_num)
                    return order_row, (res is not None)
                except Exception as exc:
                    logger.warning(f"Error querying eBay for {order_num}: {exc}")
                    return order_row, False

        logger.info(f"Verifying {len(orders)} orders against eBay Dragon API (concurrency={args.concurrency})...")
        tasks = [verify_order(o) for o in orders]
        results = await asyncio.gather(*tasks)

        dragon_orders = []
        usav_orders = []
        for order_row, is_dragon in results:
            if is_dragon:
                dragon_orders.append(order_row)
            else:
                usav_orders.append(order_row)

        logger.info("-" * 60)
        logger.info(f"Verification Results:")
        logger.info(f"  Confirmed eBay Dragon: {len(dragon_orders)}")
        logger.info(f"  Confirmed USAV / Other: {len(usav_orders)}")
        logger.info("-" * 60)

        # Plan / Execute Actions
        direct_updates = []
        duplicate_merges = []
        zoho_updates = []

        for o in dragon_orders:
            order_num = o["external_order_number"] or o["external_order_id"]
            existing_dragon = existing_dragon_map.get(order_num)
            if existing_dragon:
                duplicate_merges.append((o, existing_dragon))
            else:
                direct_updates.append(o)

            if o["zoho_id"]:
                zoho_updates.append(o)

        logger.info(f"Remediation Plan:")
        logger.info(f"  Direct Updates (EBAY_USAV -> EBAY_DRAGON): {len(direct_updates)}")
        logger.info(f"  Duplicate Merges (Keep API Dragon, Delete redundant CSV USAV): {len(duplicate_merges)}")
        logger.info(f"  Zoho SalesOrder Source Updates: {len(zoho_updates)}")

        if is_dry_run:
            logger.info("DRY RUN completed. No changes were written. Run with --execute to apply changes.")
            return

        # EXECUTE MODE
        logger.info("Applying database changes...")
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Direct Updates
                for o in direct_updates:
                    await conn.execute("""
                        UPDATE orders
                        SET platform = 'EBAY_DRAGON',
                            zoho_sync_status = 'DIRTY',
                            updated_at = NOW()
                        WHERE id = $1
                    """, o["id"])
                logger.info(f"Updated {len(direct_updates)} orders to EBAY_DRAGON.")

                # 2. Duplicate Merges
                for usav_order, dragon_order in duplicate_merges:
                    # If USAV record had zoho_id and dragon did not, transfer zoho_id
                    if usav_order["zoho_id"] and not dragon_order["zoho_id"]:
                        await conn.execute("""
                            UPDATE orders
                            SET zoho_id = $1,
                                zoho_sync_status = 'DIRTY',
                                updated_at = NOW()
                            WHERE id = $2
                        """, usav_order["zoho_id"], dragon_order["id"])

                    # Delete items of redundant USAV order
                    await conn.execute("DELETE FROM order_item WHERE order_id = $1", usav_order["id"])
                    # Delete redundant USAV order
                    await conn.execute("DELETE FROM orders WHERE id = $1", usav_order["id"])

                logger.info(f"Merged and cleaned up {len(duplicate_merges)} duplicate order records.")

        # 3. Update Zoho Sales Orders if needed
        logger.info(f"Updating {len(zoho_updates)} Sales Orders in Zoho to cf_source = 'Ebay_Dragon'...")
        for o in zoho_updates:
            try:
                await zoho_client.update_salesorder(
                    o["zoho_id"],
                    {
                        "custom_fields": [
                            {
                                "api_name": "cf_source",
                                "value": "Ebay_Dragon",
                            }
                        ]
                    }
                )
                logger.info(f"  ✓ Zoho SO {o['zoho_id']} updated to cf_source='Ebay_Dragon'")
            except Exception as exc:
                logger.error(f"  ✗ Failed to update Zoho SO {o['zoho_id']}: {exc}")

        logger.info("=" * 60)
        logger.info("Remediation execution successfully completed!")
        logger.info("=" * 60)

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
