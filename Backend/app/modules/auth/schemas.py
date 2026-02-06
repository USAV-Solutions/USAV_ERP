"""
Authentication and User Pydantic schemas.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import UserRole


class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )


# ============================================================================
# TOKEN SCHEMAS
# ============================================================================

class Token(BaseModel):
    """OAuth2 token response."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Data extracted from JWT token."""
    user_id: Optional[int] = None
    username: Optional[str] = None
    role: Optional[str] = None


# ============================================================================
# USER SCHEMAS
# ============================================================================

class UserBase(BaseSchema):
    """Shared user fields."""
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.]+$")
    email: Optional[str] = Field(None, description="Email address (optional)")
    full_name: Optional[str] = Field(None, max_length=100)
    role: UserRole = Field(UserRole.WAREHOUSE_OP, description="User role for access control")
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for creating a new user."""
    password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserUpdate(BaseSchema):
    """Schema for updating a user."""
    email: Optional[str] = Field(None, description="Email address (optional)")
    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8, max_length=100)


class UserResponse(UserBase):
    """Schema for user response (excludes password)."""
    id: int
    is_superuser: bool = False
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserInDB(UserResponse):
    """User with hashed password (internal use only)."""
    hashed_password: str


# ============================================================================
# LOGIN SCHEMAS
# ============================================================================

class LoginRequest(BaseModel):
    """Login request body."""
    username: str
    password: str


class PasswordChange(BaseModel):
    """Schema for password change request."""
    current_password: str
    new_password: str = Field(..., min_length=8)
    new_password_confirm: str
    
    @field_validator("new_password_confirm")
    @classmethod
    def passwords_match(cls, v, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


# ============================================================================
# SEATALK OAUTH SCHEMAS
# ============================================================================

class SeaTalkEmployee(BaseModel):
    """SeaTalk employee information from OAuth."""
    employee_code: str
    name: str
    email: Optional[str] = None


class SeaTalkAppTokenResponse(BaseModel):
    """SeaTalk app access token response."""
    code: int
    msg: Optional[str] = None
    app_access_token: Optional[str] = None
    expire: Optional[int] = None


class SeaTalkCodeResponse(BaseModel):
    """SeaTalk code2employee response."""
    code: int
    msg: Optional[str] = None
    employee: Optional[SeaTalkEmployee] = None


class SeaTalkCallbackRequest(BaseModel):
    """SeaTalk OAuth callback request."""
    code: str
    state: Optional[str] = None


# ============================================================================
# PAGINATED RESPONSE
# ============================================================================

class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""
    total: int
    skip: int
    limit: int
    items: list
