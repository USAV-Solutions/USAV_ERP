"""
Authentication API endpoints.
Handles login, token generation, and user management.
"""
import secrets
from datetime import datetime
from typing import Annotated, Optional
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models import User, UserRole
from app.repositories.user import UserRepository
from app.modules.auth.schemas import (
    PaginatedResponse,
    PasswordChange,
    SeaTalkAppTokenResponse,
    SeaTalkCallbackRequest,
    SeaTalkCodeResponse,
    Token,
    UserCreate,
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

# Cache for SeaTalk app access token
_seatalk_token_cache: dict[str, any] = {
    "token": None,
    "expires_at": None,
}


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth2 compatible token login.
    
    Authenticate with username and password, receive JWT access token.
    """
    repo = UserRepository(db)
    user = await repo.get_by_username(form_data.username)
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    # Update last login timestamp
    user.last_login = datetime.now()
    await db.flush()
    
    # Create access token
    access_token = create_access_token(
        subject=user.id,
        role=user.role.value,
        extra_data={"username": user.username},
    )
    
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser,
):
    """Get current authenticated user's information."""
    return UserResponse.model_validate(current_user)


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(
    password_data: PasswordChange,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Change current user's password."""
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    
    current_user.hashed_password = get_password_hash(password_data.new_password)
    await db.flush()


# ============================================================================
# SEATALK OAUTH ENDPOINTS
# ============================================================================

async def _get_seatalk_app_token() -> str:
    """
    Get SeaTalk app access token, using cached version if valid.
    Tokens are valid for 2 hours (7200 seconds).
    """
    global _seatalk_token_cache
    
    # Check if we have a valid cached token
    if (_seatalk_token_cache["token"] and 
        _seatalk_token_cache["expires_at"] and 
        datetime.now().timestamp() < _seatalk_token_cache["expires_at"]):
        logger.info("Using cached SeaTalk app access token")
        return _seatalk_token_cache["token"]
    
    # Request new token
    logger.info("Requesting new SeaTalk app access token")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.seatalk_api_base_url}/auth/app_access_token",
            json={
                "app_id": settings.seatalk_app_id,
                "app_secret": settings.seatalk_app_secret,
            },
        )
        
        logger.info(f"SeaTalk app token response status: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Failed to obtain SeaTalk app access token: {response.text}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to obtain SeaTalk app access token",
            )
        
        data = SeaTalkAppTokenResponse(**response.json())
        logger.info(f"SeaTalk app token response code: {data.code}")
        
        if data.code != 0 or not data.app_access_token:
            logger.error(f"SeaTalk API error: code {data.code}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"SeaTalk API error: code {data.code}",
            )
        
        # Cache the token (expire 5 minutes early for safety)
        _seatalk_token_cache["token"] = data.app_access_token
        _seatalk_token_cache["expires_at"] = (
            datetime.now().timestamp() + (data.expire or 7200) - 300
        )
        
        logger.info("SeaTalk app access token obtained and cached")
        return data.app_access_token


async def _get_seatalk_employee(code: str) -> SeaTalkCodeResponse:
    """
    Exchange authorization code for employee information.
    """
    logger.info(f"Getting SeaTalk employee with code: {code[:10]}...")
    app_token = await _get_seatalk_app_token()
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.seatalk_api_base_url}/open_login/code2employee",
            params={"code": code},
            headers={"Authorization": f"Bearer {app_token}"},
        )
        
        logger.info(f"SeaTalk code2employee response status: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Failed to verify SeaTalk authorization code: {response.text}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to verify SeaTalk authorization code",
            )
        
        data = SeaTalkCodeResponse(**response.json())
        logger.info(f"SeaTalk code2employee response code: {data.code}")
        
        if data.code != 0 or not data.employee:
            logger.error(f"SeaTalk authentication failed: code {data.code}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"SeaTalk authentication failed: code {data.code}",
            )
        
        return data


@router.get("/seatalk/login")
async def seatalk_login():
    """
    Initiate SeaTalk OAuth login flow.
    Redirects user to SeaTalk authorization endpoint.
    """
    state = secrets.token_urlsafe(16)
    
    auth_url = (
        f"{settings.seatalk_api_base_url}/oauth2/authorize?"
        f"app_id={settings.seatalk_app_id}&"
        f"redirect_uri={settings.seatalk_redirect_uri}&"
        f"scope=openid&"
        f"state={state}"
    )
    
    logger.info(f"Initiating SeaTalk login with state: {state}")
    return RedirectResponse(url=auth_url)


@router.get("/seatalk/callback")
async def seatalk_callback(
    code: str = Query(..., description="Authorization code from SeaTalk"),
    state: str = Query(..., description="State parameter from SeaTalk"),
    db: AsyncSession = Depends(get_db),
):
    """
    SeaTalk OAuth callback handler.
    Exchanges authorization code for user token.
    """
    logger.info(f"SeaTalk callback received with state: {state}")
    
    # Step 1: Get employee info from SeaTalk
    code_response = await _get_seatalk_employee(code)
    employee = code_response.employee
    
    logger.info(f"SeaTalk employee retrieved: {employee.employee_code}")
    
    # Step 2: Get or create user from database
    repo = UserRepository(db)
    user = await repo.get_by_seatalk_id(employee.employee_code)
    
    if user:
        # Step 3: Update user if needed
        logger.info(f"Existing user found for SeaTalk ID: {employee.employee_code}")
        if user.email != employee.email:
            user.email = employee.email
            logger.info(f"Updated email for user {user.id}")
        if user.full_name != employee.name:
            user.full_name = employee.name
            logger.info(f"Updated name for user {user.id}")
            await db.flush()
    
    if not user:
        # Step 4: Create new user
        logger.info(f"Creating new user for SeaTalk employee: {employee.employee_code}")
        # Generate a random placeholder password (user authenticates via SeaTalk)
        random_password = secrets.token_urlsafe(32)
        
        # Create username from email or employee code
        username = (
            employee.email.split("@")[0] if employee.email 
            else f"seatalk_{employee.employee_code}"
        )
        
        # Ensure username is unique
        base_username = username
        counter = 1
        while await repo.username_exists(username):
            username = f"{base_username}_{counter}"
            counter += 1
        
        logger.info(f"Creating user with username: {username}")
        user = User(
            username=username,
            email=employee.email,
            seatalk_id=employee.employee_code,
            full_name=employee.name,
            hashed_password=get_password_hash(random_password),
            role=UserRole.SALES_REP,  # Default role for new SeaTalk users
            is_active=True,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        logger.info(f"New user created with ID: {user.id}")
    
    # Check if user is active
    if not user.is_active:
        logger.warning(f"User account is disabled: {user.username}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    # Update last login timestamp
    user.last_login = datetime.now()
    await db.flush()
    
    logger.info(f"Generating access token for user: {user.username} (ID: {user.id})")
    # Create access token
    access_token = create_access_token(
        subject=user.id,
        role=user.role.value,
        extra_data={"username": user.username},
    )
    
    logger.info("SeaTalk login successful")
    return Token(access_token=access_token, token_type="bearer")


# ============================================================================
# USER MANAGEMENT ENDPOINTS (Admin only)
# ============================================================================

@router.get("/users", response_model=PaginatedResponse)
async def list_users(
    current_user: AdminUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    role: Annotated[UserRole | None, Query(description="Filter by role")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by active status")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all users (Admin only)."""
    repo = UserRepository(db)
    
    filters = {}
    if role is not None:
        filters["role"] = role
    if is_active is not None:
        filters["is_active"] = is_active
    
    items = await repo.get_multi(skip=skip, limit=limit, filters=filters, order_by="id")
    total = await repo.count(filters=filters)
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[UserResponse.model_validate(u) for u in items]
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (Admin only). Roles are assigned by admins."""
    repo = UserRepository(db)
    
    # Check for existing username
    if await repo.username_exists(user_data.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{user_data.username}' is already taken",
        )
    
    # Create user with hashed password
    user_dict = user_data.model_dump(exclude={"password"})
    user_dict["hashed_password"] = get_password_hash(user_data.password)
    
    user = await repo.create(user_dict)
    return UserResponse.model_validate(user)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific user by ID (Admin only)."""
    repo = UserRepository(db)
    user = await repo.get(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Update a user (Admin only, supports both PUT and PATCH)."""
    repo = UserRepository(db)
    user = await repo.get(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    
    update_dict = user_data.model_dump(exclude_unset=True, exclude={"password"})
    
    # Handle password update separately
    if user_data.password:
        update_dict["hashed_password"] = get_password_hash(user_data.password)
    
    if update_dict:
        user = await repo.update(user, update_dict)
    
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Delete a user (Admin only)."""
    repo = UserRepository(db)
    
    # Prevent self-deletion
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    
    deleted = await repo.delete(user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )


@router.post("/users/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user account (Admin only)."""
    repo = UserRepository(db)
    user = await repo.get(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    
    # Prevent self-deactivation
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )
    
    user = await repo.update(user, {"is_active": False})
    return UserResponse.model_validate(user)


@router.post("/users/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Activate a user account (Admin only)."""
    repo = UserRepository(db)
    user = await repo.get(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )
    
    user = await repo.update(user, {"is_active": True})
    return UserResponse.model_validate(user)
