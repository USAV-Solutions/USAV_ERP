"""
Return sync repository – manages ReturnSyncState rows.
"""
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import IntegrationSyncStatus
from app.modules.returns.models import ReturnSyncState
from app.repositories.base import BaseRepository


class ReturnSyncStateRepository(BaseRepository[ReturnSyncState]):
    def __init__(self, session: AsyncSession):
        super().__init__(ReturnSyncState, session)

    async def get_by_platform(self, platform_name: str) -> Optional[ReturnSyncState]:
        result = await self.session.execute(
            select(ReturnSyncState).where(ReturnSyncState.platform_name == platform_name)
        )
        return result.scalar_one_or_none()

    async def get_all_states(self) -> Sequence[ReturnSyncState]:
        result = await self.session.execute(
            select(ReturnSyncState).order_by(ReturnSyncState.platform_name)
        )
        return result.scalars().all()

    async def acquire_sync_lock(self, platform_name: str) -> bool:
        stmt = (
            update(ReturnSyncState)
            .where(ReturnSyncState.platform_name == platform_name)
            .where(ReturnSyncState.current_status == IntegrationSyncStatus.IDLE)
            .values(current_status=IntegrationSyncStatus.SYNCING, updated_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def release_sync_success(self, platform_name: str, sync_timestamp: Optional[datetime] = None) -> None:
        now = sync_timestamp or datetime.now(timezone.utc)
        await self.session.execute(
            update(ReturnSyncState)
            .where(ReturnSyncState.platform_name == platform_name)
            .values(
                current_status=IntegrationSyncStatus.IDLE,
                last_successful_sync=now,
                last_error_message=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.flush()

    async def release_sync_error(self, platform_name: str, error_message: str) -> None:
        await self.session.execute(
            update(ReturnSyncState)
            .where(ReturnSyncState.platform_name == platform_name)
            .values(
                current_status=IntegrationSyncStatus.ERROR,
                last_error_message=error_message,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.flush()

    async def reset_to_idle(self, platform_name: str) -> None:
        await self.session.execute(
            update(ReturnSyncState)
            .where(ReturnSyncState.platform_name == platform_name)
            .values(
                current_status=IntegrationSyncStatus.IDLE,
                last_error_message=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.flush()
