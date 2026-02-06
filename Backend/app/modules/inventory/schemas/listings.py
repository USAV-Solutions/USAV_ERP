"""
Platform Listing schemas.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import Platform, PlatformSyncStatus


class PlatformListingBase(BaseModel):
    """Base platform listing schema."""
    platform: Platform = Field(..., description="Platform: AMAZON, EBAY_MEKONG, EBAY_USAV, EBAY_DRAGON, ECWID")
    external_ref_id: Optional[str] = Field(None, max_length=100, description="ID on remote platform")
    listed_name: Optional[str] = Field(None, max_length=500, description="Product name on this platform")
    listed_description: Optional[str] = Field(None, description="Product description on this platform")
    listing_price: Optional[float] = Field(None, ge=0, description="Price on this platform")


class PlatformListingCreate(PlatformListingBase):
    """Schema for creating a platform listing."""
    variant_id: int = Field(..., description="Link to product variant")


class PlatformListingUpdate(BaseModel):
    """Schema for updating a platform listing."""
    external_ref_id: Optional[str] = Field(None, max_length=100)
    listed_name: Optional[str] = Field(None, max_length=500)
    listed_description: Optional[str] = Field(None)
    listing_price: Optional[float] = Field(None, ge=0)


class PlatformListingResponse(PlatformListingBase):
    """Schema for platform listing response."""
    id: int
    variant_id: int
    sync_status: PlatformSyncStatus = Field(default=PlatformSyncStatus.PENDING)
    last_synced_at: Optional[datetime] = None
    sync_error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
