"""
Base repository with common CRUD operations.
Implements the Repository pattern for database access.
"""
from typing import Any, Generic, Optional, Sequence, Type, TypeVar

from sqlalchemy import select, func, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic repository providing common CRUD operations.
    
    Subclass this to create entity-specific repositories.
    """
    
    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session
    
    async def get(self, id: Any) -> Optional[ModelType]:
        """Get a single record by primary key."""
        return await self.session.get(self.model, id)
    
    async def get_by_field(self, field_name: str, value: Any) -> Optional[ModelType]:
        """Get a single record by a specific field."""
        stmt = select(self.model).where(
            getattr(self.model, field_name) == value
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_multi(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        order_by: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> Sequence[ModelType]:
        """Get multiple records with pagination and optional filters."""
        stmt = select(self.model)
        
        # Apply filters
        if filters:
            for field_name, value in filters.items():
                if hasattr(self.model, field_name) and value is not None:
                    stmt = stmt.where(getattr(self.model, field_name) == value)
        
        # Apply ordering. Prefix with '-' for descending (e.g. '-created_at').
        if order_by:
            descending = order_by.startswith("-")
            field_name = order_by[1:] if descending else order_by
            if hasattr(self.model, field_name):
                column = getattr(self.model, field_name)
                stmt = stmt.order_by(desc(column) if descending else column)
        
        # Apply pagination
        stmt = stmt.offset(skip).limit(limit)
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        """Count records matching optional filters."""
        stmt = select(func.count()).select_from(self.model)
        
        if filters:
            for field_name, value in filters.items():
                if hasattr(self.model, field_name) and value is not None:
                    stmt = stmt.where(getattr(self.model, field_name) == value)
        
        result = await self.session.execute(stmt)
        return result.scalar_one()
    
    async def create(self, obj_in: dict[str, Any]) -> ModelType:
        """Create a new record."""
        db_obj = self.model(**obj_in)
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj
    
    async def update(self, db_obj: ModelType, obj_in: dict[str, Any]) -> ModelType:
        """Update an existing record."""
        for field, value in obj_in.items():
            if value is not None and hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj
    
    async def delete(self, id: Any) -> bool:
        """Delete a record by primary key."""
        obj = await self.get(id)
        if obj:
            await self.session.delete(obj)
            await self.session.flush()
            return True
        return False
    
    async def delete_multi(self, ids: list[Any]) -> int:
        """Delete multiple records by primary keys."""
        pk_column = list(self.model.__table__.primary_key.columns)[0]
        stmt = delete(self.model).where(pk_column.in_(ids))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount
    
    async def exists(self, id: Any) -> bool:
        """Check if a record exists."""
        obj = await self.get(id)
        return obj is not None
