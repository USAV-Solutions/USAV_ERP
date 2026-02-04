"""
User model with Role-Based Access Control (RBAC).
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRole(str, enum.Enum):
    """
    User roles for RBAC.
    
    Hierarchy:
    - ADMIN: Full access. Can create Product Families/Identities (Layer 1). Can manage users.
    - WAREHOUSE_OP: Operational access. Can RECEIVE, MOVE, AUDIT inventory. Read-only for products.
    - SALES_REP: Commercial access. Can edit Variant prices/descriptions. Read-only stock levels.
    - SYSTEM_BOT: Restricted. Reserved for Zoho Sync Worker. Only sync-related updates.
    """
    ADMIN = "ADMIN"
    WAREHOUSE_OP = "WAREHOUSE_OP"
    SALES_REP = "SALES_REP"
    SYSTEM_BOT = "SYSTEM_BOT"


class User(Base):
    """
    User account for authentication and authorization.
    """
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique username for login.",
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="User email address (optional).",
    )
    seatalk_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
        index=True,
        comment="SeaTalk employee code for OAuth login.",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Bcrypt hashed password.",
    )
    full_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Display name.",
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.WAREHOUSE_OP,
        comment="User role for access control.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether user can login.",
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Bypass all permission checks.",
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last successful login timestamp.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    __table_args__ = (
        Index("ix_users_role", "role"),
        Index("ix_users_is_active", "is_active"),
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role={self.role.value})>"
