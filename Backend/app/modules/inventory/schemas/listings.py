"""
Platform Listing schemas.
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import Platform, PlatformSyncStatus


class PlatformListingBase(BaseModel):
    """Base platform listing schema."""
    platform: Platform = Field(..., description="Platform: AMAZON, EBAY_MEKONG, EBAY_USAV, EBAY_DRAGON, ECWID, WALMART")
    external_ref_id: Optional[str] = Field(None, max_length=100, description="ID on remote platform")
    merchant_sku: Optional[str] = Field(None, max_length=100, description="Merchant SKU used on marketplace listing")
    listed_name: Optional[str] = Field(None, max_length=500, description="Product name on this platform")
    listed_description: Optional[str] = Field(None, description="Product description on this platform")
    listing_price: Optional[float] = Field(None, ge=0, description="Price on this platform")
    listing_quantity: Optional[int] = Field(None, ge=0, description="Quantity/stock shown on this platform")
    listing_type: Optional[str] = Field(None, max_length=100, description="Platform listing type/classification")
    listing_condition: Optional[str] = Field(None, max_length=100, description="Condition label for this platform")
    upc: Optional[str] = Field(None, max_length=64, description="UPC/GTIN used on this platform listing")
    platform_metadata: Optional[dict[str, Any]] = Field(
        None,
        description=(
            "Flexible channel-specific listing fields. "
            "Use this for eBay/Ecwid publish data like category, condition, item specifics, "
            "policies, shipping package values, SEO, media, and promotion toggles."
        ),
    )


class PlatformListingCreate(PlatformListingBase):
    """Schema for creating a platform listing."""
    variant_id: int = Field(..., description="Link to product variant")


class PlatformListingUpdate(BaseModel):
    """Schema for updating a platform listing."""
    external_ref_id: Optional[str] = Field(None, max_length=100)
    merchant_sku: Optional[str] = Field(None, max_length=100)
    listed_name: Optional[str] = Field(None, max_length=500)
    listed_description: Optional[str] = Field(None)
    listing_price: Optional[float] = Field(None, ge=0)
    listing_quantity: Optional[int] = Field(None, ge=0)
    listing_type: Optional[str] = Field(None, max_length=100)
    listing_condition: Optional[str] = Field(None, max_length=100)
    upc: Optional[str] = Field(None, max_length=64)
    platform_metadata: Optional[dict[str, Any]] = None


class PlatformListingResponse(PlatformListingBase):
    """Schema for platform listing response."""
    id: int
    variant_id: Optional[int]
    sync_status: PlatformSyncStatus = Field(default=PlatformSyncStatus.PENDING)
    last_synced_at: Optional[datetime] = None
    sync_error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class EbayPolicyProfiles(BaseModel):
    payment_profile_id: str
    return_profile_id: str
    shipping_profile_id: str


class EbayCategorySuggestion(BaseModel):
    category_id: str
    category_name: str
    category_tree_node_level: int | None = None
    category_tree_tokens: list[str] = Field(default_factory=list)


class EbaySpecificInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    value: str = Field(..., min_length=1, max_length=255)


class EbayListingDraftRequest(BaseModel):
    platform: Platform
    variant_id: int


class EbayListingDraftResponse(BaseModel):
    platform: Platform
    variant_id: int
    title: str
    description: str
    sku: str
    quantity: int
    price: float
    condition_text: str | None = None
    condition_id: int | None = None
    upc: str | None = None
    brand: str | None = None
    color: str | None = None
    marketplace_id: str
    country: str
    currency: str
    location: str
    postal_code: str
    dispatch_time_max: int
    category_id: str | None = None
    picture_urls: list[str] = Field(default_factory=list)
    dimensions: dict[str, float | None]
    shipping_package_details: dict[str, str] | None = None
    seller_profiles: EbayPolicyProfiles


class EbayCategorySuggestionsRequest(BaseModel):
    platform: Platform
    variant_id: int
    query_override: str | None = None
    title: str | None = None
    brand: str | None = None
    color: str | None = None
    condition_text: str | None = None


class EbayCategorySuggestionsResponse(BaseModel):
    marketplace_id: str
    category_tree_id: str
    query: str
    suggestions: list[EbayCategorySuggestion] = Field(default_factory=list)


class EbayPublishRequest(BaseModel):
    platform: Platform
    variant_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    category_id: str = Field(..., min_length=1, max_length=64)
    price: float = Field(..., gt=0)
    quantity: int = Field(..., ge=1)
    picture_urls: list[str] = Field(..., min_length=1)
    condition_text: str = Field(..., min_length=1, max_length=100)
    upc: str | None = Field(None, max_length=64)
    brand: str | None = Field(None, max_length=255)
    mpn: str | None = Field(None, max_length=255)
    color: str | None = Field(None, max_length=100)
    dimensions: dict[str, float | None] = Field(default_factory=dict)
    extra_specifics: list[EbaySpecificInput] = Field(default_factory=list)


class EbayPublishResponse(BaseModel):
    listing_id: int
    platform: Platform
    variant_id: int
    item_id: str
    sync_status: PlatformSyncStatus
