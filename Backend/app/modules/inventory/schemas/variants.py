"""
Product Variant schemas.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import ConditionCode, ZohoSyncStatus


class ProductVariantBase(BaseModel):
    """Base product variant schema."""
    color_code: Optional[str] = Field(None, max_length=2, description="Color code (e.g., BK, WY, SV)")
    condition_code: Optional[ConditionCode] = Field(None, description="Condition: N (New), R (Repair)")
    is_active: bool = Field(default=True, description="Whether variant is active")


class ProductVariantCreate(ProductVariantBase):
    """Schema for creating a product variant."""
    identity_id: int = Field(..., description="Link to product identity")


class ProductVariantUpdate(BaseModel):
    """Schema for updating a product variant."""
    color_code: Optional[str] = Field(None, max_length=2)
    condition_code: Optional[ConditionCode] = Field(None)
    is_active: Optional[bool] = Field(None)


class ProductVariantResponse(ProductVariantBase):
    """Schema for product variant response."""
    id: int
    identity_id: int
    full_sku: str = Field(..., description="Complete sellable SKU")
    zoho_item_id: Optional[str] = Field(None, description="Zoho item ID")
    zoho_sync_status: ZohoSyncStatus = Field(default=ZohoSyncStatus.PENDING)
    zoho_last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ProductVariantWithListings(ProductVariantResponse):
    """Product variant with listing count."""
    listings_count: int = Field(default=0, description="Number of platform listings")
