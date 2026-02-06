"""
Bundle Component schemas.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import BundleRole


class BundleComponentBase(BaseModel):
    """Base bundle component schema."""
    quantity_required: int = Field(default=1, ge=1, description="Quantity of this component required")
    role: BundleRole = Field(default=BundleRole.PRIMARY, description="Component role: Primary, Accessory, Satellite")


class BundleComponentCreate(BundleComponentBase):
    """Schema for creating a bundle component."""
    parent_identity_id: int = Field(..., description="Bundle/Kit identity")
    child_identity_id: int = Field(..., description="Component identity")


class BundleComponentUpdate(BaseModel):
    """Schema for updating a bundle component."""
    quantity_required: Optional[int] = Field(None, ge=1)
    role: Optional[BundleRole] = Field(None)


class BundleComponentResponse(BundleComponentBase):
    """Schema for bundle component response."""
    id: int
    parent_identity_id: int
    child_identity_id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class BundleComponentWithDetails(BundleComponentResponse):
    """Bundle component with parent and child details."""
    parent_upis_h: Optional[str] = Field(None, description="Parent UPIS-H")
    child_upis_h: Optional[str] = Field(None, description="Child UPIS-H")
