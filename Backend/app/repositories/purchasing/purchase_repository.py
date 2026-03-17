"""Repositories for purchasing domain."""
from datetime import date
from typing import Optional, Sequence

from sqlalchemy import desc, select
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

    async def get_multi_with_date_filters(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        order_date_from: date | None = None,
        order_date_to: date | None = None,
        sort_date: str = "desc",
    ) -> Sequence[PurchaseOrder]:
        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.vendor),
                selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.variant),
            )
        )

        if order_date_from is not None:
            stmt = stmt.where(PurchaseOrder.order_date >= order_date_from)
        if order_date_to is not None:
            stmt = stmt.where(PurchaseOrder.order_date <= order_date_to)

        if str(sort_date).lower() == "asc":
            stmt = stmt.order_by(PurchaseOrder.order_date.asc(), PurchaseOrder.id.asc())
        else:
            stmt = stmt.order_by(desc(PurchaseOrder.order_date), desc(PurchaseOrder.id))

        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()


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
