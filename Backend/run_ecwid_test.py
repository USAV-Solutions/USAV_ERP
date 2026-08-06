import asyncio
from datetime import datetime, timezone
import sys

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.integrations.ecwid.client import EcwidClient
from app.modules.returns.service import ReturnSyncService
from app.repositories.returns.record_repository import ReturnRecordRepository
from app.repositories.returns.sync_repository import ReturnSyncStateRepository
from app.repositories.orders.order_repository import OrderRepository

async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with async_session() as session:
        sync_repo = ReturnSyncStateRepository(session)
        record_repo = ReturnRecordRepository(session)
        order_repo = OrderRepository(session)
        service = ReturnSyncService(session, sync_repo, record_repo, order_repo)
        
        client = EcwidClient()
        
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        print("Starting sync...")
        try:
            res = await service.sync_platform("ECWID", client, source="ECWID_API")
            print(res)
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
