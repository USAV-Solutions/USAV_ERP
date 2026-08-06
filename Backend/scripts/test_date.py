import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.integrations.zoho.client import ZohoClient

async def main():
    client = ZohoClient()
    pos = await client.list_purchase_orders(page=5, per_page=50)
    for po in pos:
        print(f"PO: {po.get('purchaseorder_number')} | Date: {po.get('date')} | Status: {po.get('status')} | RStatus: {po.get('received_status')}")

if __name__ == "__main__":
    asyncio.run(main())
