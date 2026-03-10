"""Repositories for purchasing domain."""
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemStatus,
    Vendor,
)
from app.repositories.base import BaseRepository


class VendorRepository(BaseRepository[Vendor]):
    """Repository for Vendor operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(Vendor, session)


class PurchaseOrderRepository(BaseRepository[PurchaseOrder]):
    """Repository for purchase order header operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(PurchaseOrder, session)

    async def get_with_items_and_vendor(self, po_id: int) -> Optional[PurchaseOrder]:
        """Load a purchase order with vendor and line items."""
        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.vendor),
                selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.variant),
            )
            .where(PurchaseOrder.id == po_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class PurchaseOrderItemRepository(BaseRepository[PurchaseOrderItem]):
    """Repository for purchase order line-item operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(PurchaseOrderItem, session)

    async def get_unmatched(self, *, skip: int = 0, limit: int = 100) -> Sequence[PurchaseOrderItem]:
        """Return unmatched purchase order items."""
        stmt = (
            select(PurchaseOrderItem)
            .where(PurchaseOrderItem.status == PurchaseOrderItemStatus.UNMATCHED)
            .order_by(PurchaseOrderItem.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
