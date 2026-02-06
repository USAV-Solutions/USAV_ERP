"""
Order Schemas.

Pydantic schemas for order API endpoints.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.models import OrderItemStatus, OrderPlatform, OrderStatus


# ============================================================================
# ORDER ITEM SCHEMAS
# ============================================================================

class OrderItemBase(BaseModel):
    """Base order item schema."""
    item_name: str = Field(..., max_length=500, description="Item name/title")
    quantity: int = Field(1, ge=1, description="Quantity ordered")
    unit_price: Decimal = Field(..., ge=0, description="Price per unit")
    external_item_id: Optional[str] = Field(None, max_length=100)
    external_sku: Optional[str] = Field(None, max_length=100)
    external_asin: Optional[str] = Field(None, max_length=20)
    item_metadata: Optional[dict[str, Any]] = None


class OrderItemCreate(OrderItemBase):
    """Schema for creating an order item."""
    pass


class OrderItemUpdate(BaseModel):
    """Schema for updating an order item."""
    variant_id: Optional[int] = Field(None, description="Link to internal SKU")
    allocated_inventory_id: Optional[int] = Field(None, description="Allocated inventory item")
    status: Optional[OrderItemStatus] = None
    matching_notes: Optional[str] = None


class OrderItemResponse(OrderItemBase):
    """Schema for order item response."""
    id: int
    order_id: int
    variant_id: Optional[int] = None
    allocated_inventory_id: Optional[int] = None
    status: OrderItemStatus
    total_price: Decimal
    matching_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class OrderItemWithVariant(OrderItemResponse):
    """Order item with variant details."""
    variant_sku: Optional[str] = Field(None, description="Matched variant full SKU")
    variant_name: Optional[str] = Field(None, description="Variant product name")


# ============================================================================
# ORDER SCHEMAS
# ============================================================================

class OrderBase(BaseModel):
    """Base order schema."""
    platform: OrderPlatform
    external_order_id: str = Field(..., max_length=100)
    external_order_number: Optional[str] = Field(None, max_length=100)
    
    # Customer info
    customer_name: Optional[str] = Field(None, max_length=200)
    customer_email: Optional[str] = Field(None, max_length=200)
    
    # Shipping address
    shipping_address_line1: Optional[str] = Field(None, max_length=255)
    shipping_address_line2: Optional[str] = Field(None, max_length=255)
    shipping_city: Optional[str] = Field(None, max_length=100)
    shipping_state: Optional[str] = Field(None, max_length=100)
    shipping_postal_code: Optional[str] = Field(None, max_length=20)
    shipping_country: Optional[str] = Field("US", max_length=100)
    
    # Financial
    subtotal_amount: Decimal = Field(0, ge=0)
    tax_amount: Decimal = Field(0, ge=0)
    shipping_amount: Decimal = Field(0, ge=0)
    total_amount: Decimal = Field(..., ge=0)
    currency: str = Field("USD", max_length=3)
    
    # Timestamps
    ordered_at: Optional[datetime] = None


class OrderCreate(OrderBase):
    """Schema for creating an order."""
    items: list[OrderItemCreate] = Field(default_factory=list)
    platform_data: Optional[dict[str, Any]] = None


class OrderUpdate(BaseModel):
    """Schema for updating an order."""
    status: Optional[OrderStatus] = None
    tracking_number: Optional[str] = Field(None, max_length=100)
    carrier: Optional[str] = Field(None, max_length=50)
    shipped_at: Optional[datetime] = None
    processing_notes: Optional[str] = None


class OrderResponse(OrderBase):
    """Schema for order response."""
    id: int
    status: OrderStatus
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    shipped_at: Optional[datetime] = None
    platform_data: Optional[dict[str, Any]] = None
    processing_notes: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class OrderWithItems(OrderResponse):
    """Order with all items."""
    items: list[OrderItemResponse] = Field(default_factory=list)


class OrderSummary(BaseModel):
    """Summary statistics for orders."""
    total_orders: int
    pending_orders: int
    processing_orders: int
    ready_to_ship_orders: int
    shipped_orders: int
    orders_with_errors: int
    total_revenue: Decimal
    unmatched_items: int


# ============================================================================
# ORDER MATCHING SCHEMAS
# ============================================================================

class SkuMatchRequest(BaseModel):
    """Request to manually match an SKU to an order item."""
    order_item_id: int
    variant_id: int
    notes: Optional[str] = None


class BulkSkuMatchRequest(BaseModel):
    """Request to match multiple items at once."""
    matches: list[SkuMatchRequest]


class InventoryAllocationRequest(BaseModel):
    """Request to allocate inventory to an order item."""
    order_item_id: int
    inventory_item_id: int


class BulkInventoryAllocationRequest(BaseModel):
    """Request to allocate inventory to multiple items."""
    allocations: list[InventoryAllocationRequest]


# ============================================================================
# EXTERNAL ORDER IMPORT SCHEMAS
# ============================================================================

class AmazonOrderImport(BaseModel):
    """Schema for importing Amazon order data."""
    amazon_order_id: str
    purchase_date: datetime
    order_status: str
    buyer_name: Optional[str] = None
    buyer_email: Optional[str] = None
    ship_city: Optional[str] = None
    ship_state: Optional[str] = None
    ship_postal_code: Optional[str] = None
    ship_country: Optional[str] = "US"
    order_total: Decimal
    currency: str = "USD"
    items: list[dict[str, Any]]
    raw_data: Optional[dict[str, Any]] = None


class EbayOrderImport(BaseModel):
    """Schema for importing eBay order data."""
    order_id: str
    creation_date: datetime
    buyer_username: Optional[str] = None
    shipping_address: Optional[dict[str, Any]] = None
    total: Decimal
    currency: str = "USD"
    line_items: list[dict[str, Any]]
    raw_data: Optional[dict[str, Any]] = None

