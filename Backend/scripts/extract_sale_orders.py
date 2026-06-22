import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
import csv

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.database import async_session_factory
from app.models import Order
from sqlalchemy import select

async def main():
    parser = argparse.ArgumentParser(description="Extract sale orders in a given date range")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD or ISO 8601)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD or ISO 8601)")
    parser.add_argument("--output", default="sale_orders.csv", help="Output CSV file path")
    
    args = parser.parse_args()
    
    try:
        # Pad with time if only date provided
        start_str = args.start_date
        if len(start_str) == 10:
            start_str += "T00:00:00"
        start_date = datetime.fromisoformat(start_str)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
    except ValueError:
        print("Invalid start date format. Use YYYY-MM-DD or ISO 8601.")
        sys.exit(1)
        
    try:
        end_str = args.end_date
        if len(end_str) == 10:
            end_str += "T23:59:59"
        end_date = datetime.fromisoformat(end_str)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
    except ValueError:
        print("Invalid end date format. Use YYYY-MM-DD or ISO 8601.")
        sys.exit(1)

    async with async_session_factory() as session:
        stmt = select(Order).where(
            Order.ordered_at >= start_date,
            Order.ordered_at <= end_date
        ).order_by(Order.ordered_at)
        
        result = await session.execute(stmt)
        orders = result.scalars().all()
        
        if not orders:
            print(f"No orders found between {start_date} and {end_date}.")
            return
            
        print(f"Found {len(orders)} orders. Writing to {args.output}...")
        
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Order ID", "Platform", "External Order ID", 
                "Status", "Total Amount", "Currency", "Ordered At"
            ])
            for order in orders:
                writer.writerow([
                    order.id,
                    getattr(order.platform, 'value', order.platform),
                    order.external_order_id,
                    getattr(order.status, 'value', order.status),
                    order.total_amount,
                    order.currency,
                    order.ordered_at.isoformat() if order.ordered_at else ""
                ])
                
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
