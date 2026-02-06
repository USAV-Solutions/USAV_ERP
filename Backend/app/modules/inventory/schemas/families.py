"""
Product Family schemas.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.inventory.schemas.lookups import BrandResponse


class ProductFamilyBase(BaseModel):
    """Base product family schema."""
    base_name: str = Field(..., min_length=1, max_length=255, description="Product family name")
    description: Optional[str] = Field(None, max_length=2000, description="Product family description")
    brand_id: Optional[int] = Field(None, description="Link to brand")
    dimension_length: Optional[Decimal] = Field(None, ge=0, description="Length in inches")
    dimension_width: Optional[Decimal] = Field(None, ge=0, description="Width in inches")
    dimension_height: Optional[Decimal] = Field(None, ge=0, description="Height in inches")
    weight: Optional[Decimal] = Field(None, ge=0, description="Weight in pounds")
    kit_included_products: Optional[str] = Field(None, max_length=2000, description="Comma-separated list of included products for Kit type")


class ProductFamilyCreate(ProductFamilyBase):
    """Schema for creating a new product family."""
    product_id: Optional[int] = Field(None, ge=0, le=99999, description="ECWID product ID (0-99999). If not provided, auto-generated.")


class ProductFamilyUpdate(BaseModel):
    """Schema for updating a product family."""
    base_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    brand_id: Optional[int] = Field(None)
    dimension_length: Optional[Decimal] = Field(None, ge=0)
    dimension_width: Optional[Decimal] = Field(None, ge=0)
    dimension_height: Optional[Decimal] = Field(None, ge=0)
    weight: Optional[Decimal] = Field(None, ge=0)
    kit_included_products: Optional[str] = Field(None, max_length=2000)


class ProductFamilyResponse(ProductFamilyBase):
    """Schema for product family response."""
    product_id: int
    brand: Optional[BrandResponse] = Field(None, description="Brand details")
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ProductFamilyWithIdentities(ProductFamilyResponse):
    """Product family with associated identities."""
    identities_count: int = Field(default=0, description="Number of product identities")
