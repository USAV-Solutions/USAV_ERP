import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.engine.result import ScalarResult

import app.models
from app.models.user import User, UserRole
from app.api.deps import require_packer, require_admin_or_warehouse

@pytest.mark.asyncio
async def test_require_packer_allowed():
    """Verify require_packer allows PACKER role user."""
    mock_user = MagicMock(spec=User)
    mock_user.is_superuser = False
    mock_user.role = UserRole.PACKER

    res = await require_packer(current_user=mock_user)
    assert res.role == UserRole.PACKER

@pytest.mark.asyncio
async def test_require_packer_admin_allowed():
    """Verify require_packer allows ADMIN role user."""
    mock_user = MagicMock(spec=User)
    mock_user.is_superuser = False
    mock_user.role = UserRole.ADMIN

    res = await require_packer(current_user=mock_user)
    assert res.role == UserRole.ADMIN

@pytest.mark.asyncio
async def test_require_admin_or_warehouse_packer_allowed():
    """Verify require_admin_or_warehouse permits PACKER role."""
    mock_user = MagicMock(spec=User)
    mock_user.is_superuser = False
    mock_user.role = UserRole.PACKER

    res = await require_admin_or_warehouse(current_user=mock_user)
    assert res.role == UserRole.PACKER
