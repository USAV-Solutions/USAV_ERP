"""
Dependency injection for the Orders module.

Provides FastAPI ``Depends()`` callables that wire up repositories and
the OrderSyncService with the current database session.
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.inventory import PlatformListingRepository
from app.repositories.orders.order_repository import OrderItemRepository, OrderRepository
from app.repositories.orders.sync_repository import SyncRepository
from app.modules.orders.service import OrderSyncService


async def get_sync_repo(db: AsyncSession = Depends(get_db)) -> SyncRepository:
    return SyncRepository(db)


async def get_order_repo(db: AsyncSession = Depends(get_db)) -> OrderRepository:
    return OrderRepository(db)


async def get_order_item_repo(db: AsyncSession = Depends(get_db)) -> OrderItemRepository:
    return OrderItemRepository(db)


async def get_listing_repo(db: AsyncSession = Depends(get_db)) -> PlatformListingRepository:
    return PlatformListingRepository(db)


async def get_order_sync_service(
    db: AsyncSession = Depends(get_db),
    sync_repo: SyncRepository = Depends(get_sync_repo),
    order_repo: OrderRepository = Depends(get_order_repo),
    order_item_repo: OrderItemRepository = Depends(get_order_item_repo),
    listing_repo: PlatformListingRepository = Depends(get_listing_repo),
) -> OrderSyncService:
    """Build the fully-wired service for a single request."""
    return OrderSyncService(
        session=db,
        sync_repo=sync_repo,
        order_repo=order_repo,
        order_item_repo=order_item_repo,
        listing_repo=listing_repo,
    )
