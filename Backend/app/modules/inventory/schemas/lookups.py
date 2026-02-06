"""
Lookup table schemas for Brand, Color, Condition, and LCI Definition.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# BRAND SCHEMAS
# ============================================================================

class BrandBase(BaseModel):
    """Base brand schema."""
    name: str = Field(..., min_length=1, max_length=100, description="Brand name")


class BrandCreate(BrandBase):
    """Schema for creating a brand."""
    pass


class BrandUpdate(BaseModel):
    """Schema for updating a brand."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)


class BrandResponse(BrandBase):
    """Schema for brand response."""
    id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# COLOR SCHEMAS
# ============================================================================

class ColorBase(BaseModel):
    """Base color schema."""
    name: str = Field(..., min_length=1, max_length=50, description="Color name (e.g., 'Black')")
    code: str = Field(..., min_length=1, max_length=2, description="Color code (e.g., 'BK')")


class ColorCreate(ColorBase):
    """Schema for creating a color."""
    pass


class ColorUpdate(BaseModel):
    """Schema for updating a color."""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    code: Optional[str] = Field(None, min_length=1, max_length=2)


class ColorResponse(ColorBase):
    """Schema for color response."""
    id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# CONDITION SCHEMAS
# ============================================================================

class ConditionBase(BaseModel):
    """Base condition schema."""
    name: str = Field(..., min_length=1, max_length=50, description="Condition name (e.g., 'Used')")
    code: str = Field(..., min_length=1, max_length=1, description="Condition code (e.g., 'U')")


class ConditionCreate(ConditionBase):
    """Schema for creating a condition."""
    pass


class ConditionUpdate(BaseModel):
    """Schema for updating a condition."""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    code: Optional[str] = Field(None, min_length=1, max_length=1)


class ConditionResponse(ConditionBase):
    """Schema for condition response."""
    id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# LCI DEFINITION SCHEMAS
# ============================================================================

class LCIDefinitionBase(BaseModel):
    """Base LCI definition schema."""
    component_name: str = Field(..., min_length=1, max_length=100, description="Component name (e.g., 'Motherboard')")


class LCIDefinitionCreate(LCIDefinitionBase):
    """Schema for creating an LCI definition."""
    product_id: int = Field(..., ge=0, le=99999, description="Product family ID")
    lci_index: Optional[int] = Field(None, ge=1, le=99, description="LCI index (auto-generated if not provided)")


class LCIDefinitionUpdate(BaseModel):
    """Schema for updating an LCI definition."""
    component_name: Optional[str] = Field(None, min_length=1, max_length=100)


class LCIDefinitionResponse(LCIDefinitionBase):
    """Schema for LCI definition response."""
    id: int
    product_id: int
    lci_index: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
