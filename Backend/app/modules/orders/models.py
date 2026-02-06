"""
Order Models.

Defines the database models for order management:
- Order: External platform order header
- OrderItem: Individual line items linked to SKUs
"""
import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.entities import ProductVariant, InventoryItem


# ============================================================================
# ORDER ENUMS
# ============================================================================

class OrderPlatform(str, enum.Enum):
    """Order source platforms."""
    AMAZON = "AMAZON"
    EBAY_MEKONG = "EBAY_MEKONG"
    EBAY_USAV = "EBAY_USAV"
    EBAY_DRAGON = "EBAY_DRAGON"
    ZOHO = "ZOHO"
    MANUAL = "MANUAL"  # Manually created orders


class OrderStatus(str, enum.Enum):
    """Order processing status."""
    PENDING = "PENDING"           # Received but not processed
    PROCESSING = "PROCESSING"     # Being matched/allocated
    READY_TO_SHIP = "READY_TO_SHIP"  # Items allocated, ready for fulfillment
    SHIPPED = "SHIPPED"           # Order shipped
    DELIVERED = "DELIVERED"       # Order delivered
    CANCELLED = "CANCELLED"       # Order cancelled
    REFUNDED = "REFUNDED"         # Order refunded
    ON_HOLD = "ON_HOLD"           # On hold (awaiting payment, etc.)
    ERROR = "ERROR"               # Processing error


class OrderItemStatus(str, enum.Enum):
    """Individual order item status."""
    UNMATCHED = "UNMATCHED"       # SKU not found/matched
    MATCHED = "MATCHED"           # SKU matched but not allocated
    ALLOCATED = "ALLOCATED"       # Inventory item reserved
    SHIPPED = "SHIPPED"           # Item shipped
    CANCELLED = "CANCELLED"       # Item cancelled


# ============================================================================
# MIXIN
# ============================================================================

class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ============================================================================
# ORDER TABLES
# ============================================================================

class Order(Base, TimestampMixin):
    """
    External platform order.
    
    Stores order header information from Amazon, eBay, Zoho, etc.
    Links to OrderItem for individual line items.
    """
    __tablename__ = "order"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    platform: Mapped[OrderPlatform] = mapped_column(
        Enum(OrderPlatform, name="order_platform_enum"),
        nullable=False,
        comment="Source platform (AMAZON, EBAY, etc.).",
    )
    external_order_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Order ID on the external platform.",
    )
    external_order_number: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Human-readable order number (if different from ID).",
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status_enum"),
        nullable=False,
        default=OrderStatus.PENDING,
        comment="Current order processing status.",
    )
    
    # Customer Information
    customer_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Customer full name.",
    )
    customer_email: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Customer email address.",
    )
    
    # Shipping Address
    shipping_address_line1: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    shipping_address_line2: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    shipping_city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    shipping_state: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    shipping_postal_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    shipping_country: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        default="US",
    )
    
    # Financial
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=0,
        comment="Order subtotal before tax/shipping.",
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=0,
        comment="Total tax amount.",
    )
    shipping_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=0,
        comment="Shipping cost.",
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        comment="Total order amount.",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        comment="Currency code (ISO 4217).",
    )
    
    # Timestamps from platform
    ordered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the order was placed on the platform.",
    )
    shipped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the order was shipped.",
    )
    
    # Tracking
    tracking_number: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Shipment tracking number.",
    )
    carrier: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Shipping carrier (UPS, FedEx, USPS).",
    )
    
    # Platform metadata
    platform_data: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Raw platform-specific order data.",
    )
    
    # Processing notes
    processing_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Internal notes about order processing.",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if processing failed.",
    )
    
    # Relationships
    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    
    __table_args__ = (
        # Unique order per platform
        UniqueConstraint(
            "platform", "external_order_id",
            name="uq_order_platform_external_id",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="ck_order_positive_total",
        ),
        Index("ix_order_platform", "platform"),
        Index("ix_order_status", "status"),
        Index("ix_order_ordered_at", "ordered_at"),
        Index("ix_order_external_id", "external_order_id"),
    )
    
    def __repr__(self) -> str:
        return f"<Order(id={self.id}, platform={self.platform.value}, external_id='{self.external_order_id}')>"


class OrderItem(Base, TimestampMixin):
    """
    Individual order line item.
    
    Links external order items to internal SKUs (ProductVariant).
    Supports allocation of specific inventory items.
    """
    __tablename__ = "order_item"
    
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("order.id", ondelete="CASCADE"),
        nullable=False,
        comment="Parent order.",
    )
    
    # External identification
    external_item_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Item ID on the external platform.",
    )
    external_sku: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="SKU as listed on the platform.",
    )
    external_asin: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Amazon ASIN (if Amazon order).",
    )
    
    # Internal matching
    variant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("product_variant.id", ondelete="SET NULL"),
        nullable=True,
        comment="Matched internal product variant.",
    )
    allocated_inventory_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("inventory_item.id", ondelete="SET NULL"),
        nullable=True,
        comment="Allocated physical inventory item.",
    )
    
    status: Mapped[OrderItemStatus] = mapped_column(
        Enum(OrderItemStatus, name="order_item_status_enum"),
        nullable=False,
        default=OrderItemStatus.UNMATCHED,
        comment="Item processing status.",
    )
    
    # Item details
    item_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Item name/title from the platform.",
    )
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Quantity ordered.",
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        comment="Price per unit.",
    )
    total_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        comment="Total price (quantity * unit_price).",
    )
    
    # Platform metadata
    item_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Platform-specific item data.",
    )
    
    # Matching notes
    matching_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Notes about SKU matching process.",
    )
    
    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="items",
    )
    variant: Mapped[Optional["ProductVariant"]] = relationship(
        "ProductVariant",
        foreign_keys=[variant_id],
        lazy="selectin",
    )
    allocated_inventory: Mapped[Optional["InventoryItem"]] = relationship(
        "InventoryItem",
        foreign_keys=[allocated_inventory_id],
        lazy="selectin",
    )
    
    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_order_item_positive_quantity",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="ck_order_item_non_negative_price",
        ),
        Index("ix_order_item_order_id", "order_id"),
        Index("ix_order_item_variant_id", "variant_id"),
        Index("ix_order_item_status", "status"),
        Index("ix_order_item_external_sku", "external_sku"),
        Index("ix_order_item_external_asin", "external_asin"),
    )
    
    def __repr__(self) -> str:
        return f"<OrderItem(id={self.id}, order_id={self.order_id}, name='{self.item_name[:30]}')>"

