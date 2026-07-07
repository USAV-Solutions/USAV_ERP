"""
Authentication dependencies for FastAPI route protection.
Provides get_current_user and role-based access control.
"""
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User, UserRole

# OAuth2 scheme - expects token in Authorization header
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/token",
    auto_error=False,  # Don't auto-error, we handle it ourselves
)


async def get_current_user(
    token: Annotated[Optional[str], Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.
    
    Raises:
        HTTPException 401: If token is missing, invalid, or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not token:
        raise credentials_exception
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    
    # Get user from database
    stmt = select(User).where(User.id == int(user_id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    return user


async def get_current_user_optional(
    token: Annotated[Optional[str], Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Optional user dependency - returns None if not authenticated.
    Useful for endpoints that work differently for authenticated vs anonymous users.
    """
    if not token:
        return None
    
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


def require_roles(*allowed_roles: UserRole):
    """
    Factory for role-based access control dependency.
    
    Usage:
        @router.post("/admin-only")
        async def admin_endpoint(user: User = Depends(require_roles(UserRole.ADMIN))):
            ...
    """
    # FastAPI runs async dependencies directly on the event loop, avoiding threadpool scheduling overhead.
    # We keep it async def even without internal awaits to optimize performance for simple in-memory checks.
    async def role_checker(  # nosonar
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        # Superusers bypass role checks
        if current_user.is_superuser:
            return current_user
        
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {', '.join(r.value for r in allowed_roles)}",
            )
        
        return current_user
    
    return role_checker


# Pre-built role dependencies for common use cases
# FastAPI runs async dependencies directly on the event loop, avoiding threadpool scheduling overhead.
# We keep it async def even without internal awaits to optimize performance for simple in-memory checks.
async def require_admin(  # nosonar
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require ADMIN role."""
    if not current_user.is_superuser and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# FastAPI runs async dependencies directly on the event loop, avoiding threadpool scheduling overhead.
# We keep it async def even without internal awaits to optimize performance for simple in-memory checks.
async def require_admin_or_sales(  # nosonar
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require ADMIN or SALES_REP role."""
    if not current_user.is_superuser and current_user.role not in [UserRole.ADMIN, UserRole.SALES_REP]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Sales Rep access required",
        )
    return current_user


# FastAPI runs async dependencies directly on the event loop, avoiding threadpool scheduling overhead.
# We keep it async def even without internal awaits to optimize performance for simple in-memory checks.
async def require_admin_or_warehouse(  # nosonar
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require ADMIN or WAREHOUSE_OP role."""
    if not current_user.is_superuser and current_user.role not in [UserRole.ADMIN, UserRole.WAREHOUSE_OP]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Warehouse Operator access required",
        )
    return current_user


# Type aliases for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[Optional[User], Depends(get_current_user_optional)]
AdminUser = Annotated[User, Depends(require_admin)]
AdminOrSalesUser = Annotated[User, Depends(require_admin_or_sales)]
AdminOrWarehouseUser = Annotated[User, Depends(require_admin_or_warehouse)]
