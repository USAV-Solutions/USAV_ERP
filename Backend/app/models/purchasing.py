"""
SQLAlchemy models for purchasing domain.

Tables:
  - Vendor
  - PurchaseOrder
  - PurchaseOrderItem
"""
import enum
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.entities import TimestampMixin, ZohoSyncMixin

if TYPE_CHECKING:
    from app.models.entities import ProductVariant


class PurchaseDeliverStatus(str, enum.Enum):
    """Purchase order delivery lifecycle."""

    CREATED = "CREATED"
    BILLED = "BILLED"
    DELIVERED = "DELIVERED"


class PurchaseOrderItemStatus(str, enum.Enum):
    """Item-level matching and receiving status."""

    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    RECEIVED = "RECEIVED"


class Vendor(Base, ZohoSyncMixin, TimestampMixin):
    """Suppliers from which purchase orders are created."""

    __tablename__ = "vendor"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        unique=True,
        comment="Vendor legal/trading name.",
    )
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
        "PurchaseOrder",
        back_populates="vendor",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_vendor_name", "name"),
        Index("ix_vendor_zoho_id", "zoho_id"),
    )


class PurchaseOrder(Base, ZohoSyncMixin, TimestampMixin):
    """Purchase order header."""

    __tablename__ = "purchase_order"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    po_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        comment="Human-readable purchase order reference.",
    )
    vendor_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("vendor.id", ondelete="RESTRICT"),
        nullable=False,
    )
    deliver_status: Mapped[PurchaseDeliverStatus] = mapped_column(
        Enum(PurchaseDeliverStatus, name="purchase_deliver_status_enum", create_constraint=False),
        nullable=False,
        default=PurchaseDeliverStatus.CREATED,
        server_default=PurchaseDeliverStatus.CREATED.value,
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    vendor: Mapped["Vendor"] = relationship(
        "Vendor",
        back_populates="purchase_orders",
        lazy="selectin",
    )
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("po_number", name="uq_purchase_order_po_number"),
        Index("ix_purchase_order_vendor_id", "vendor_id"),
        Index("ix_purchase_order_status", "deliver_status"),
        Index("ix_purchase_order_zoho_id", "zoho_id"),
    )


class PurchaseOrderItem(Base, TimestampMixin):
    """Individual line item in a purchase order."""

    __tablename__ = "purchase_order_item"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    purchase_order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_order.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("product_variant.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    status: Mapped[PurchaseOrderItemStatus] = mapped_column(
        Enum(PurchaseOrderItemStatus, name="purchase_order_item_status_enum", create_constraint=False),
        nullable=False,
        default=PurchaseOrderItemStatus.UNMATCHED,
        server_default=PurchaseOrderItemStatus.UNMATCHED.value,
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship(
        "PurchaseOrder",
        back_populates="items",
        lazy="selectin",
    )
    variant: Mapped[Optional["ProductVariant"]] = relationship(
        "ProductVariant",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_purchase_order_item_po_id", "purchase_order_id"),
        Index("ix_purchase_order_item_variant_id", "variant_id"),
        Index("ix_purchase_order_item_status", "status"),
    )
