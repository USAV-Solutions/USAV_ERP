"""
Return repositories – CRUD helpers for ReturnRecord and ReturnItem data.
"""
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.orders.models import OrderPlatform
from app.modules.returns.models import ReturnItem, ReturnNormalizedStatus, ReturnRecord
from app.repositories.base import BaseRepository


class ReturnRecordRepository(BaseRepository[ReturnRecord]):
    def __init__(self, session: AsyncSession):
        super().__init__(ReturnRecord, session)

    def _apply_filters(
        self,
        stmt,
        *,
        platform: Optional[OrderPlatform] = None,
        normalized_status: Optional[ReturnNormalizedStatus] = None,
        source: Optional[str] = None,
        ordered_at_from: Optional[datetime] = None,
        ordered_at_to: Optional[datetime] = None,
        event_at_from: Optional[datetime] = None,
        event_at_to: Optional[datetime] = None,
        search: Optional[str] = None,
    ):
        if platform is not None:
            stmt = stmt.where(ReturnRecord.platform == platform)
        if normalized_status is not None:
            stmt = stmt.where(ReturnRecord.normalized_status == normalized_status)
        if source:
            stmt = stmt.where(ReturnRecord.source.ilike(f"%{source.strip()}%"))
        if ordered_at_from is not None:
            stmt = stmt.where(ReturnRecord.ordered_at >= ordered_at_from)
        if ordered_at_to is not None:
            stmt = stmt.where(ReturnRecord.ordered_at <= ordered_at_to)
        if event_at_from is not None:
            stmt = stmt.where(ReturnRecord.event_at >= event_at_from)
        if event_at_to is not None:
            stmt = stmt.where(ReturnRecord.event_at <= event_at_to)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                ReturnRecord.external_order_id.ilike(pattern)
                | ReturnRecord.external_return_id.ilike(pattern)
                | ReturnRecord.customer_name.ilike(pattern)
                | ReturnRecord.customer_email.ilike(pattern)
                | ReturnRecord.items.any(ReturnItem.external_sku.ilike(pattern))
                | ReturnRecord.items.any(ReturnItem.item_name.ilike(pattern))
            )
        return stmt

    async def get_by_external_key(
        self,
        platform: OrderPlatform,
        external_record_key: str,
    ) -> Optional[ReturnRecord]:
        stmt = (
            select(ReturnRecord)
            .options(selectinload(ReturnRecord.items))
            .where(
                ReturnRecord.platform == platform,
                ReturnRecord.external_record_key == external_record_key,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_items(self, record_id: int) -> Optional[ReturnRecord]:
        stmt = (
            select(ReturnRecord)
            .options(selectinload(ReturnRecord.items), selectinload(ReturnRecord.linked_order))
            .where(ReturnRecord.id == record_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_records(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        platform: Optional[OrderPlatform] = None,
        normalized_status: Optional[ReturnNormalizedStatus] = None,
        source: Optional[str] = None,
        ordered_at_from: Optional[datetime] = None,
        ordered_at_to: Optional[datetime] = None,
        event_at_from: Optional[datetime] = None,
        event_at_to: Optional[datetime] = None,
        sort_by: str = "event_at",
        sort_dir: str = "desc",
        search: Optional[str] = None,
    ) -> tuple[Sequence[ReturnRecord], int, dict[str, int]]:
        stmt = select(ReturnRecord).options(
            selectinload(ReturnRecord.items),
            selectinload(ReturnRecord.linked_order),
        )
        stmt = self._apply_filters(
            stmt,
            platform=platform,
            normalized_status=normalized_status,
            source=source,
            ordered_at_from=ordered_at_from,
            ordered_at_to=ordered_at_to,
            event_at_from=event_at_from,
            event_at_to=event_at_to,
            search=search,
        )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_columns = {
            "event_at": ReturnRecord.event_at,
            "ordered_at": ReturnRecord.ordered_at,
            "refunded_amount": ReturnRecord.refunded_amount,
            "external_order_id": ReturnRecord.external_order_id,
        }
        sort_column = sort_columns.get(sort_by.lower(), ReturnRecord.event_at)
        if sort_dir.lower() == "asc":
            stmt = stmt.order_by(sort_column.asc(), ReturnRecord.id.asc())
        else:
            stmt = stmt.order_by(desc(sort_column), desc(ReturnRecord.id))

        if limit > 0:
            stmt = stmt.offset(skip).limit(limit)
        rows = (await self.session.execute(stmt)).scalars().all()

        summary_stmt = select(ReturnRecord.normalized_status, func.count()).group_by(ReturnRecord.normalized_status)
        summary_stmt = self._apply_filters(
            summary_stmt,
            platform=platform,
            normalized_status=normalized_status,
            source=source,
            ordered_at_from=ordered_at_from,
            ordered_at_to=ordered_at_to,
            event_at_from=event_at_from,
            event_at_to=event_at_to,
            search=search,
        )
        summary_rows = (await self.session.execute(summary_stmt)).all()
        summary_counts = {
            status.value if hasattr(status, "value") else str(status): count
            for status, count in summary_rows
        }
        return rows, total, summary_counts

    async def count_by_status(self) -> dict[str, int]:
        stmt = select(ReturnRecord.normalized_status, func.count()).group_by(ReturnRecord.normalized_status)
        rows = (await self.session.execute(stmt)).all()
        return {status.value: count for status, count in rows}
