"""Repositories for purchasing domain."""
from datetime import date
from typing import Optional, Sequence

from sqlalchemy import and_, desc, exists, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    PurchaseOrder,
    PurchaseDeliverStatus,
    PurchaseOrderItem,
    PurchaseOrderItemStatus,
    ZohoSyncStatus,
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
        deliver_status: PurchaseDeliverStatus | None = None,
        item_match_status: str | None = None,
        zoho_sync_status: ZohoSyncStatus | None = None,
        sort_by: str = "order_date",
        sort_dir: str = "desc",
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
        if deliver_status is not None:
            stmt = stmt.where(PurchaseOrder.deliver_status == deliver_status)
        if zoho_sync_status is not None:
            stmt = stmt.where(PurchaseOrder.zoho_sync_status == zoho_sync_status)

        unmatched_exists = exists(
            select(1).where(
                and_(
                    PurchaseOrderItem.purchase_order_id == PurchaseOrder.id,
                    PurchaseOrderItem.status == PurchaseOrderItemStatus.UNMATCHED,
                )
            )
        )
        if item_match_status == "unmatched":
            stmt = stmt.where(unmatched_exists)
        elif item_match_status == "matched":
            any_item_exists = exists(
                select(1).where(PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
            )
            stmt = stmt.where(any_item_exists).where(not_(unmatched_exists))

        sort_columns = {
            "order_date": PurchaseOrder.order_date,
            "po_number": PurchaseOrder.po_number,
            "total_amount": PurchaseOrder.total_amount,
            "created_at": PurchaseOrder.created_at,
        }
        sort_column = sort_columns.get(str(sort_by).lower(), PurchaseOrder.order_date)
        if str(sort_dir).lower() == "asc":
            stmt = stmt.order_by(sort_column.asc(), PurchaseOrder.id.asc())
        else:
            stmt = stmt.order_by(desc(sort_column), desc(PurchaseOrder.id))

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
