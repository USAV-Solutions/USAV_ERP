"""Dependency providers for purchasing module."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.purchasing.service import PurchasingService
from app.repositories.inventory import InventoryItemRepository
from app.repositories.purchasing import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
    VendorRepository,
)


async def get_vendor_repo(db: AsyncSession = Depends(get_db)) -> VendorRepository:
    return VendorRepository(db)


async def get_purchase_order_repo(db: AsyncSession = Depends(get_db)) -> PurchaseOrderRepository:
    return PurchaseOrderRepository(db)


async def get_purchase_order_item_repo(
    db: AsyncSession = Depends(get_db),
) -> PurchaseOrderItemRepository:
    return PurchaseOrderItemRepository(db)


async def get_inventory_item_repo(db: AsyncSession = Depends(get_db)) -> InventoryItemRepository:
    return InventoryItemRepository(db)


async def get_purchasing_service(
    db: AsyncSession = Depends(get_db),
    po_repo: PurchaseOrderRepository = Depends(get_purchase_order_repo),
    po_item_repo: PurchaseOrderItemRepository = Depends(get_purchase_order_item_repo),
    inventory_repo: InventoryItemRepository = Depends(get_inventory_item_repo),
) -> PurchasingService:
    return PurchasingService(
        session=db,
        po_repo=po_repo,
        po_item_repo=po_item_repo,
        inventory_repo=inventory_repo,
    )
