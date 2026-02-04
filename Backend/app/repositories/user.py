"""
User repository for database operations.
"""
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)
    
    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        stmt = select(User).where(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_seatalk_id(self, seatalk_id: str) -> Optional[User]:
        """Get user by SeaTalk employee code."""
        stmt = select(User).where(User.seatalk_id == seatalk_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_active_users(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[User]:
        """Get all active users."""
        stmt = (
            select(User)
            .where(User.is_active == True)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_by_role(
        self,
        role: UserRole,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[User]:
        """Get users by role."""
        stmt = (
            select(User)
            .where(User.role == role)
            .where(User.is_active == True)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def username_exists(self, username: str) -> bool:
        """Check if username is already taken."""
        user = await self.get_by_username(username)
        return user is not None
    
    async def email_exists(self, email: str) -> bool:
        """Check if email is already registered."""
        if not email:
            return False
        user = await self.get_by_email(email)
        return user is not None
