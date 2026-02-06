"""
Inventory Item schemas.
"""
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field

from app.models import InventoryStatus


class InventoryItemBase(BaseModel):
    """Base inventory item schema."""
    serial_number: Optional[str] = Field(None, max_length=100, description="Manufacturer serial number")
    status: InventoryStatus = Field(default=InventoryStatus.AVAILABLE, description="Item status")
    location_code: Optional[str] = Field(None, max_length=50, description="Warehouse location")
    cost_basis: Optional[float] = Field(None, ge=0, description="Acquisition cost")
    notes: Optional[str] = Field(None, description="Additional notes")


class InventoryItemCreate(InventoryItemBase):
    """Schema for creating an inventory item."""
    variant_id: int = Field(..., description="Link to product variant")


class InventoryItemUpdate(BaseModel):
    """Schema for updating an inventory item."""
    serial_number: Optional[str] = Field(None, max_length=100)
    status: Optional[InventoryStatus] = Field(None)
    location_code: Optional[str] = Field(None, max_length=50)
    cost_basis: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = Field(None)


class InventoryItemResponse(InventoryItemBase):
    """Schema for inventory item response."""
    id: int
    variant_id: int
    received_at: Optional[datetime] = None
    sold_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class InventoryItemWithVariant(InventoryItemResponse):
    """Inventory item with variant SKU info."""
    full_sku: Optional[str] = Field(None, description="SKU of the variant")


class InventorySummary(BaseModel):
    """Summary of inventory counts by status."""
    variant_id: int
    full_sku: str
    total: int = Field(default=0)
    available: int = Field(default=0)
    sold: int = Field(default=0)
    reserved: int = Field(default=0)
    rma: int = Field(default=0)
    damaged: int = Field(default=0)


# ============================================================================
# WAREHOUSE OPERATIONS SCHEMAS
# ============================================================================

class InventoryReceiveRequest(BaseModel):
    """Schema for receiving inventory via barcode scan."""
    serial_number: str = Field(..., min_length=1, max_length=100, description="Scanned serial number/barcode")
    variant_sku: Optional[str] = Field(None, description="Optional SKU if known")
    location_code: Optional[str] = Field(None, max_length=50, description="Optional initial location")
    cost_basis: Optional[float] = Field(None, ge=0, description="Optional acquisition cost")


class InventoryReceiveResponse(BaseModel):
    """Response after receiving an inventory item."""
    id: int
    serial_number: str
    sku: str = Field(..., description="Full SKU of the variant")
    location_code: Optional[str] = None
    status: str
    received_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class InventoryMoveRequest(BaseModel):
    """Schema for moving inventory to a new location."""
    serial_number: str = Field(..., min_length=1, max_length=100, description="Serial number to move")
    new_location: str = Field(..., min_length=1, max_length=50, description="Target location code")


class InventoryMoveResponse(BaseModel):
    """Response after moving an inventory item."""
    serial_number: str
    previous_location: Optional[str] = None
    new_location: str
    moved_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class InventoryAuditItem(BaseModel):
    """Single item in audit response."""
    id: int
    serial_number: Optional[str] = None
    location_code: Optional[str] = None
    status: str
    received_at: Optional[datetime] = None
    variant_id: int
    full_sku: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class InventoryAuditResponse(BaseModel):
    """Response for inventory audit/lookup."""
    items: List[InventoryAuditItem] = Field(default_factory=list)
    total_count: int = Field(default=0)
