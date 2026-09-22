import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect(
        host="100.87.193.67",
        port=5432,
        user="postgres",
        password="devpassword123",
        database="inventory_system",
        timeout=10
    )
    try:
        dragon_items = await conn.fetch("""
            SELECT o.id, o.external_order_number, oi.external_item_id, oi.external_sku, oi.item_name, o.zoho_id
            FROM orders o
            JOIN order_item oi ON oi.order_id = o.id
            WHERE o.platform = 'EBAY_DRAGON'
            LIMIT 10
        """)
        print(f"=== Items from EBAY_DRAGON orders ({len(dragon_items)}) ===")
        for r in dragon_items:
            print(f"  Order={r['id']} | Num={r['external_order_number']} | ExtItemId={r['external_item_id']} | SKU={r['external_sku']} | Name={r['item_name'][:40]} | ZohoId={r['zoho_id']}")

        usav_ss_items = await conn.fetch("""
            SELECT o.id, o.external_order_number, oi.external_item_id, oi.external_sku, oi.item_name, o.zoho_id
            FROM orders o
            JOIN order_item oi ON oi.order_id = o.id
            WHERE o.platform = 'EBAY_USAV' AND o.source = 'SHIPSTATION_CSV'
            LIMIT 10
        """)
        print(f"\n=== Items from EBAY_USAV SHIPSTATION_CSV orders ({len(usav_ss_items)}) ===")
        for r in usav_ss_items:
            print(f"  Order={r['id']} | Num={r['external_order_number']} | ExtItemId={r['external_item_id']} | SKU={r['external_sku']} | Name={r['item_name'][:40]} | ZohoId={r['zoho_id']}")

        # How many EBAY_DRAGON orders have a zoho_id?
        dragon_zoho = await conn.fetchval("""
            SELECT COUNT(*) FROM orders WHERE platform = 'EBAY_DRAGON' AND zoho_id IS NOT NULL
        """)
        print(f"\nEBAY_DRAGON orders with zoho_id: {dragon_zoho} / 166")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
