"""
Sync repository – manages the IntegrationState table.

Provides read/write access to the per-platform sync heartbeat that drives
the "Safe Sync" algorithm.
"""
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import IntegrationState, IntegrationSyncStatus
from app.repositories.base import BaseRepository


class SyncRepository(BaseRepository[IntegrationState]):
    """Repository for IntegrationState operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(IntegrationState, session)

    async def get_by_platform(self, platform_name: str) -> Optional[IntegrationState]:
        """Get integration state for a single platform."""
        stmt = select(IntegrationState).where(
            IntegrationState.platform_name == platform_name
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_states(self) -> Sequence[IntegrationState]:
        """Get integration states for all platforms."""
        stmt = select(IntegrationState).order_by(IntegrationState.platform_name)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def acquire_sync_lock(self, platform_name: str) -> bool:
        """
        Atomically set ``current_status`` to SYNCING if currently IDLE.

        Returns True if the lock was acquired, False if already syncing/error.
        """
        stmt = (
            update(IntegrationState)
            .where(IntegrationState.platform_name == platform_name)
            .where(IntegrationState.current_status == IntegrationSyncStatus.IDLE)
            .values(
                current_status=IntegrationSyncStatus.SYNCING,
                updated_at=datetime.now(timezone.utc),
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def release_sync_success(
        self,
        platform_name: str,
        sync_timestamp: Optional[datetime] = None,
    ) -> None:
        """Mark sync as complete and update the anchor timestamp."""
        now = sync_timestamp or datetime.now(timezone.utc)
        stmt = (
            update(IntegrationState)
            .where(IntegrationState.platform_name == platform_name)
            .values(
                current_status=IntegrationSyncStatus.IDLE,
                last_successful_sync=now,
                last_error_message=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def release_sync_error(
        self,
        platform_name: str,
        error_message: str,
    ) -> None:
        """Mark sync as failed and store the error message."""
        stmt = (
            update(IntegrationState)
            .where(IntegrationState.platform_name == platform_name)
            .values(
                current_status=IntegrationSyncStatus.ERROR,
                last_error_message=error_message,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def reset_to_idle(self, platform_name: str) -> None:
        """Force-reset a stuck platform back to IDLE (admin action)."""
        stmt = (
            update(IntegrationState)
            .where(IntegrationState.platform_name == platform_name)
            .values(
                current_status=IntegrationSyncStatus.IDLE,
                last_error_message=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
