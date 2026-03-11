"""
Pydantic request / response schemas for Order endpoints.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.entities import ZohoSyncStatus
from app.modules.orders.models import OrderItemStatus, OrderPlatform, OrderStatus, ShippingStatus


# ============================================================================
# CUSTOMER BRIEF (for order list serialisation)
# ============================================================================

class CustomerBrief(BaseModel):
    """Minimal customer info embedded in order responses."""
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# ORDER ITEM SCHEMAS
# ============================================================================

class OrderItemBrief(BaseModel):
    """Compact order-item representation for list views."""
    id: int
    external_item_id: Optional[str] = None
    external_sku: Optional[str] = None
    external_asin: Optional[str] = None
    item_name: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    status: OrderItemStatus
    variant_id: Optional[int] = None
    variant_sku: Optional[str] = None
    matching_notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="wrap")
    @classmethod
    def _resolve_variant_sku(cls, values: Any, handler: Any) -> Any:
        """Auto-populate variant_sku from the ORM variant relationship."""
        obj = handler(values)
        if obj.variant_sku is None and hasattr(values, "variant") and values.variant is not None:
            obj.variant_sku = values.variant.full_sku
        return obj


class OrderItemDetail(OrderItemBrief):
    """Full order-item details including metadata."""
    allocated_inventory_id: Optional[int] = None
    item_metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class OrderItemMatchRequest(BaseModel):
    """
    Payload for POST /orders/items/{item_id}/match.

    Links the item to an internal product variant **and** optionally
    teaches the auto-match engine by creating a PLATFORM_LISTING row.
    """
    variant_id: int = Field(..., description="Internal ProductVariant.id to link.")
    learn: bool = Field(
        True,
        description=(
            "If True, also create / update a PLATFORM_LISTING row so future "
            "orders with the same external ref are auto-matched."
        ),
    )
    notes: Optional[str] = Field(None, max_length=500, description="Optional matching notes.")


class OrderItemConfirmRequest(BaseModel):
    """Payload for POST /orders/items/{item_id}/confirm (auto-match verification)."""
    notes: Optional[str] = Field(default=None, max_length=500)


# ============================================================================
# ORDER HEADER SCHEMAS
# ============================================================================

class OrderBrief(BaseModel):
    """Compact order representation for the dashboard list."""
    id: int
    platform: OrderPlatform
    external_order_id: str
    external_order_number: Optional[str] = None
    status: OrderStatus
    shipping_status: ShippingStatus
    zoho_sync_status: ZohoSyncStatus
    customer_name: Optional[str] = None
    customer: Optional[CustomerBrief] = None
    total_amount: Decimal
    currency: str
    ordered_at: Optional[datetime] = None
    created_at: datetime
    item_count: int = Field(0, description="Number of line items.")
    unmatched_count: int = Field(0, description="Line items needing SKU resolution.")

    model_config = ConfigDict(from_attributes=True)


class OrderDetail(BaseModel):
    """Full order view including all line items."""
    id: int
    platform: OrderPlatform
    external_order_id: str
    external_order_number: Optional[str] = None
    status: OrderStatus
    shipping_status: ShippingStatus
    zoho_sync_status: ZohoSyncStatus

    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer: Optional[CustomerBrief] = None

    shipping_address_line1: Optional[str] = None
    shipping_address_line2: Optional[str] = None
    shipping_city: Optional[str] = None
    shipping_state: Optional[str] = None
    shipping_postal_code: Optional[str] = None
    shipping_country: Optional[str] = None

    subtotal_amount: Decimal
    tax_amount: Decimal
    shipping_amount: Decimal
    total_amount: Decimal
    currency: str

    ordered_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None

    processing_notes: Optional[str] = None
    error_message: Optional[str] = None

    items: list[OrderItemDetail] = []

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("items", mode="before")
    @classmethod
    def force_list_structure(cls, v: Any) -> list[Any]:
        """
        If 'items' comes in as a single object (due to ingestion bugs),
        wrap it in a list so the Pydantic validation doesn't crash.
        """
        if v is None:
            return []
        if isinstance(v, list):
            return v
        # If it's a single SQLAlchemy object, wrap it
        return [v]


class OrderCreate(BaseModel):
    """Manual order creation (MANUAL platform)."""
    external_order_id: str = Field(..., max_length=100)
    customer_name: Optional[str] = Field(None, max_length=200)
    customer_email: Optional[str] = Field(None, max_length=200)
    total_amount: Decimal = Field(..., ge=0)
    currency: str = Field("USD", max_length=3)
    notes: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    """Update the processing status of an order."""
    status: OrderStatus
    notes: Optional[str] = None


class ShippingStatusUpdate(BaseModel):
    """Update the shipping / fulfilment status of an order."""
    shipping_status: ShippingStatus
    tracking_number: Optional[str] = Field(None, max_length=100)
    carrier: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class OrderListResponse(BaseModel):
    """Paginated order list response."""
    total: int
    skip: int
    limit: int
    items: list[OrderBrief]
