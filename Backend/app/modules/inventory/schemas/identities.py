"""
Product Identity schemas.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import IdentityType, PhysicalClass


class ProductIdentityBase(BaseModel):
    """Base product identity schema."""
    type: IdentityType = Field(..., description="Identity type: Base, B (Bundle), P (Part), K (Kit), S (Service)")
    lci: Optional[int] = Field(None, ge=1, le=99, description="Local Component Index (1-99, only for Parts)")
    physical_class: Optional[PhysicalClass] = Field(None, description="Physical classification: E, C, P, S, W, A")
    identity_name: Optional[str] = Field(None, max_length=255, description="Human-friendly identity name")


class ProductIdentityCreate(ProductIdentityBase):
    """Schema for creating a product identity."""
    product_id: int = Field(..., description="Link to product family")


class ProductIdentityUpdate(BaseModel):
    """Schema for updating a product identity."""
    identity_name: Optional[str] = Field(None, max_length=255)
    physical_class: Optional[PhysicalClass] = Field(None)


class ProductIdentityResponse(ProductIdentityBase):
    """Schema for product identity response."""
    id: int
    product_id: int
    generated_upis_h: str = Field(..., description="Computed identity string (e.g., '00845-P-1')")
    hex_signature: str = Field(..., description="32-bit HEX encoding")
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ProductIdentityWithVariants(ProductIdentityResponse):
    """Product identity with variant count."""
    variants_count: int = Field(default=0, description="Number of variants")
