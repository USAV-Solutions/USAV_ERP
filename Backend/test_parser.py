import sys
import asyncio
from sqlalchemy.orm import Session
from app.modules.orders.routes import _parse_order_csv

with open("/home/las/USAV/USAV_Inventory/misc/eBay-OrdersReport-Jul-17-2026-00_00_15-0700-13314833682.csv", "r", encoding="utf-8-sig") as f:
    text = f.read()

grouped, seen, skipped = _parse_order_csv(text)
print(f"seen: {seen}, skipped: {skipped}, grouped: {len(grouped)}")
for o in grouped:
    print(f"Order ID: {o['platform_order_id']} | Platform: {o['platform_name']}")
