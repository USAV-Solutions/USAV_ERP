from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.returns.service import ReturnSyncService
from app.repositories.orders.order_repository import OrderRepository
from app.repositories.returns.record_repository import ReturnRecordRepository
from app.repositories.returns.sync_repository import ReturnSyncStateRepository


async def get_return_sync_repo(db: AsyncSession = Depends(get_db)) -> ReturnSyncStateRepository:
    return ReturnSyncStateRepository(db)


async def get_return_record_repo(db: AsyncSession = Depends(get_db)) -> ReturnRecordRepository:
    return ReturnRecordRepository(db)


async def get_return_order_repo(db: AsyncSession = Depends(get_db)) -> OrderRepository:
    return OrderRepository(db)


async def get_return_service(
    db: AsyncSession = Depends(get_db),
    sync_repo: ReturnSyncStateRepository = Depends(get_return_sync_repo),
    record_repo: ReturnRecordRepository = Depends(get_return_record_repo),
    order_repo: OrderRepository = Depends(get_return_order_repo),
) -> ReturnSyncService:
    return ReturnSyncService(
        session=db,
        sync_repo=sync_repo,
        record_repo=record_repo,
        order_repo=order_repo,
    )
