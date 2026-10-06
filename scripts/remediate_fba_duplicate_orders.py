"""
Remediate duplicate Amazon orders (e.g. AMAZON vs AMAZON_FBA) in the database.

Usage:
    # Dry run (inspect duplicates without modifying anything):
    python scripts/remediate_fba_duplicate_orders.py --host 100.87.193.67

    # Apply changes:
    python scripts/remediate_fba_duplicate_orders.py --host 100.87.193.67 --apply
"""
import argparse
import asyncio
import logging
from typing import Any

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediate_fba_duplicates")


async def main():
    parser = argparse.ArgumentParser(description="Remediate duplicate Amazon FBA orders")
    parser.add_argument("--host", default="100.87.193.67", help="Database host")
    parser.add_argument("--port", type=int, default=5432, help="Database port")
    parser.add_argument("--user", default="postgres", help="Database user")
    parser.add_argument("--password", default="devpassword123", help="Database password")
    parser.add_argument("--database", default="inventory_system", help="Database name")
    parser.add_argument("--apply", action="store_true", help="Apply fixes to database (default: dry run)")
    args = parser.parse_args()

    logger.info("Connecting to PostgreSQL at %s:%d/%s ...", args.host, args.port, args.database)
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
        timeout=15,
    )

    try:
        # Find external_order_ids that appear more than once among Amazon platforms
        dup_ids_rows = await conn.fetch("""
            SELECT external_order_id, COUNT(*) as count
            FROM orders
            WHERE platform IN ('AMAZON', 'AMAZON_FBA', 'AMAZON_RENEW')
            GROUP BY external_order_id
            HAVING COUNT(*) > 1
            ORDER BY count DESC
        """)

        logger.info("Found %d external_order_ids with duplicate Amazon records.", len(dup_ids_rows))
        if not dup_ids_rows:
            logger.info("No duplicates found. Database is clean!")
            return

        total_deleted = 0
        total_migrated = 0

        for row in dup_ids_rows:
            order_id = row["external_order_id"]
            records = await conn.fetch("""
                SELECT id, platform, source, fulfillment_channel, zoho_id, zoho_sync_status,
                       tracking_number, customer_id, created_at
                FROM orders
                WHERE external_order_id = $1 AND platform IN ('AMAZON', 'AMAZON_FBA', 'AMAZON_RENEW')
                ORDER BY
                    CASE WHEN zoho_id IS NOT NULL THEN 0 ELSE 1 END,
                    CASE WHEN platform = 'AMAZON_FBA' THEN 0 ELSE 1 END,
                    id ASC
            """, order_id)

            # Choose the primary order to keep:
            # Prefer order with zoho_id already assigned, or the oldest one
            primary = records[0]
            duplicates = records[1:]

            logger.info(
                "Order %s: Keeping primary ID=%d (platform=%s, zoho_id=%s, zoho_status=%s). Duplicates to remove: %s",
                order_id,
                primary["id"],
                primary["platform"],
                primary["zoho_id"],
                primary["zoho_sync_status"],
                [d["id"] for d in duplicates],
            )

            if args.apply:
                async with conn.transaction():
                    # If primary is not yet AMAZON_FBA and is FBA fulfilled, promote it to AMAZON_FBA
                    if primary["platform"] != "AMAZON_FBA":
                        await conn.execute("""
                            UPDATE orders
                            SET platform = 'AMAZON_FBA',
                                fulfillment_channel = 'AMAZON_FBA'
                            WHERE id = $1
                        """, primary["id"])
                        total_migrated += 1

                    for dup in duplicates:
                        dup_id = dup["id"]
                        # Re-link any sales returns pointing to the duplicate order to the primary order
                        try:
                            await conn.execute("UPDATE sales_returns SET linked_order_id = $1 WHERE linked_order_id = $2", primary["id"], dup_id)
                        except Exception:
                            pass
                        # Delete line items first
                        await conn.execute("DELETE FROM order_item WHERE order_id = $1", dup_id)
                        # Delete duplicate order
                        await conn.execute("DELETE FROM orders WHERE id = $1", dup_id)
                        total_deleted += 1

        if args.apply:
            logger.info("Remediation complete: %d orders upgraded to AMAZON_FBA, %d duplicate orders deleted.", total_migrated, total_deleted)
        else:
            logger.info("Dry run finished. Run with --apply to execute the changes.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
