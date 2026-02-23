"""
SQLAlchemy models for the Orders domain.

Tables:
  - IntegrationState: Sync heartbeat per platform.
  - Order:            Top-level customer order imported from a platform.
  - OrderItem:        Individual line items with SKU-matching status.

These models match the migration in 0005_add_orders (Order, OrderItem) and
0006_add_integration_state (IntegrationState).
"""
import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
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
from app.models.entities import TimestampMixin

if TYPE_CHECKING:
    from typing import List
    from app.models.entities import ProductVariant, InventoryItem


# ============================================================================
# ENUMS
# ============================================================================

class OrderPlatform(str, enum.Enum):
    """Supported order source platforms."""
    AMAZON = "AMAZON"
    EBAY_MEKONG = "EBAY_MEKONG"
    EBAY_USAV = "EBAY_USAV"
    EBAY_DRAGON = "EBAY_DRAGON"
    ECWID = "ECWID"
    ZOHO = "ZOHO"
    MANUAL = "MANUAL"


class OrderStatus(str, enum.Enum):
    """Order-level processing status."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    ON_HOLD = "ON_HOLD"
    ERROR = "ERROR"


class OrderItemStatus(str, enum.Enum):
    """
    Line-item matching status.

    UNMATCHED     – No internal variant linked yet (action needed).
    MATCHED       – Variant linked (auto or manual).
    ALLOCATED     – Physical inventory item reserved.
    SHIPPED       – Item shipped.
    CANCELLED     – Item cancelled.
    """
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class IntegrationSyncStatus(str, enum.Enum):
    """Current sync-engine state for a platform."""
    IDLE = "IDLE"
    SYNCING = "SYNCING"
    ERROR = "ERROR"


# ============================================================================
# INTEGRATION STATE  (The "Sync Memory")
# ============================================================================

class IntegrationState(Base, TimestampMixin):
    """
    Tracks the heartbeat of each platform integration.

    One row per platform.  The ``last_successful_sync`` column is the anchor
    for the next fetch window; ``current_status`` prevents concurrent syncs.
    """
    __tablename__ = "integration_state"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    platform_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        comment="Logical platform key, e.g. 'AMAZON', 'EBAY_USAV'.",
    )
    last_successful_sync: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Anchor timestamp for the next fetch window.",
    )
    current_status: Mapped[IntegrationSyncStatus] = mapped_column(
        Enum(IntegrationSyncStatus, name="integration_sync_status_enum"),
        nullable=False,
        default=IntegrationSyncStatus.IDLE,
        server_default="IDLE",
        comment="IDLE | SYNCING | ERROR.",
    )
    last_error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Debugging info if last sync failed.",
    )

    def __repr__(self) -> str:
        return (
            f"<IntegrationState(platform='{self.platform_name}', "
            f"status={self.current_status.value})>"
        )


# ============================================================================
# ORDER HEADER
# ============================================================================

class Order(Base, TimestampMixin):
    """
    Top-level customer order imported from an external sales platform.

    The ``UNIQUE(platform, external_order_id)`` constraint guarantees
    idempotent ingestion – overlapping sync windows are safe.
    """
    __tablename__ = "order"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    platform: Mapped[OrderPlatform] = mapped_column(
        Enum(OrderPlatform, name="order_platform_enum", create_constraint=False),
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
        Enum(OrderStatus, name="order_status_enum", create_constraint=False),
        nullable=False,
        default=OrderStatus.PENDING,
        comment="Current order processing status.",
    )

    # ---- Customer ----
    customer_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, comment="Customer full name.",
    )
    customer_email: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, comment="Customer email address.",
    )

    # ---- Shipping Address ----
    shipping_address_line1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shipping_address_line2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shipping_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_country: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, server_default="US",
    )

    # ---- Financial ----
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0",
        comment="Order subtotal before tax/shipping.",
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0",
        comment="Total tax amount.",
    )
    shipping_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0",
        comment="Shipping cost.",
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Total order amount.",
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD",
        comment="Currency code (ISO 4217).",
    )

    # ---- Timestamps ----
    ordered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When the order was placed on the platform.",
    )
    shipped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When the order was shipped.",
    )

    # ---- Tracking ----
    tracking_number: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="Shipment tracking number.",
    )
    carrier: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="Shipping carrier (UPS, FedEx, USPS).",
    )

    # ---- Metadata ----
    platform_data: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="Raw platform-specific order data.",
    )
    processing_notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Internal notes about order processing.",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Error message if processing failed.",
    )

    # ---- Relationships ----
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("platform", "external_order_id", name="uq_order_platform_external_id"),
        CheckConstraint("total_amount >= 0", name="ck_order_positive_total"),
        Index("ix_order_platform", "platform"),
        Index("ix_order_status", "status"),
        Index("ix_order_ordered_at", "ordered_at"),
        Index("ix_order_external_id", "external_order_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Order(id={self.id}, platform={self.platform.value}, "
            f"ext_id='{self.external_order_id}')>"
        )


# ============================================================================
# ORDER ITEM  (Line items – SKU matching workspace)
# ============================================================================

class OrderItem(Base, TimestampMixin):
    """
    Individual line item within an order.

    This is the workspace for SKU-matching: the ``variant_id`` column starts
    NULL (UNMATCHED) and is populated either automatically via
    ``PLATFORM_LISTING`` lookup or manually by the Order Specialist.
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

    # ---- External Identification ----
    external_item_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Item ID on the external platform.",
    )
    external_sku: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="SKU as listed on the platform.",
    )
    external_asin: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="Amazon ASIN (if Amazon order).",
    )

    # ---- Internal Matching ----
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
        Enum(OrderItemStatus, name="order_item_status_enum", create_constraint=False),
        nullable=False,
        default=OrderItemStatus.UNMATCHED,
        comment="Item processing status.",
    )

    # ---- Item Details ----
    item_name: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="Item name/title from the platform.",
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1",
        comment="Quantity ordered.",
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Price per unit.",
    )
    total_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Total price (quantity × unit_price).",
    )

    # ---- Metadata ----
    item_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="Platform-specific item data.",
    )
    matching_notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Notes about SKU matching process.",
    )

    # ---- Relationships ----
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="items",
    )
    variant: Mapped[Optional["ProductVariant"]] = relationship(
        "ProductVariant",
        lazy="selectin",
    )
    allocated_inventory: Mapped[Optional["InventoryItem"]] = relationship(
        "InventoryItem",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_item_positive_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_order_item_non_negative_price"),
        Index("ix_order_item_order_id", "order_id"),
        Index("ix_order_item_variant_id", "variant_id"),
        Index("ix_order_item_status", "status"),
        Index("ix_order_item_external_sku", "external_sku"),
        Index("ix_order_item_external_asin", "external_asin"),
    )

    def __repr__(self) -> str:
        return (
            f"<OrderItem(id={self.id}, order={self.order_id}, "
            f"status={self.status.value})>"
        )
