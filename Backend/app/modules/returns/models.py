"""
SQLAlchemy models for the Returns domain.

Tables:
  - ReturnSyncState: sync heartbeat per platform for returns/cancellations.
  - ReturnRecord:    normalized return/refund/cancellation dashboard rows.
  - ReturnItem:      line-item detail for each return record.
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.entities import TimestampMixin
from app.modules.orders.models import IntegrationSyncStatus, OrderPlatform, OrderFulfillmentChannel

if TYPE_CHECKING:
    from app.modules.orders.models import Order, OrderItem


class ReturnNormalizedStatus(str, enum.Enum):
    RETURNED = "RETURNED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    CANCELLED = "CANCELLED"
    PARTIALLY_CANCELLED = "PARTIALLY_CANCELLED"
    UNKNOWN = "UNKNOWN"


class ReturnZohoSyncStatus(str, enum.Enum):
    PENDING = "PENDING"
    READY_TO_SYNC = "READY_TO_SYNC"
    MISSING_LOCAL_ORDER = "MISSING_LOCAL_ORDER"
    MISSING_ZOHO_ORDER = "MISSING_ZOHO_ORDER"
    MISSING_LINE_ITEM_MAPPING = "MISSING_LINE_ITEM_MAPPING"
    QUANTITY_CONFLICT = "QUANTITY_CONFLICT"
    ALREADY_SYNCED = "ALREADY_SYNCED"
    SYNCED = "SYNCED"
    ERROR = "ERROR"


class ReturnSyncState(Base, TimestampMixin):
    __tablename__ = "return_sync_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    last_successful_sync: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_status: Mapped[IntegrationSyncStatus] = mapped_column(
        Enum(IntegrationSyncStatus, name="return_integration_sync_status_enum"),
        nullable=False,
        default=IntegrationSyncStatus.IDLE,
        server_default="IDLE",
    )
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ReturnRecord(Base, TimestampMixin):
    __tablename__ = "return_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[OrderPlatform] = mapped_column(
        Enum(OrderPlatform, name="return_order_platform_enum", create_constraint=False),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="MANUAL")
    external_record_key: Mapped[str] = mapped_column(String(150), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    external_return_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    linked_order_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )

    customer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    ordered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    event_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_source_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    normalized_status: Mapped[ReturnNormalizedStatus] = mapped_column(
        Enum(ReturnNormalizedStatus, name="return_normalized_status_enum", create_constraint=False),
        nullable=False,
        default=ReturnNormalizedStatus.UNKNOWN,
        server_default="UNKNOWN",
    )
    source_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_substatus: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fulfillment_channel: Mapped[OrderFulfillmentChannel] = mapped_column(
        Enum(OrderFulfillmentChannel, name="return_order_fulfillment_channel_enum", create_constraint=False),
        nullable=False,
        default=OrderFulfillmentChannel.SELF_FULFILLED,
        server_default="SELF_FULFILLED",
    )

    order_total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    zoho_salesreturn_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    zoho_salesreturn_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    zoho_sync_status: Mapped[ReturnZohoSyncStatus] = mapped_column(
        Enum(ReturnZohoSyncStatus, name="return_zoho_sync_status_enum", create_constraint=False),
        nullable=False,
        default=ReturnZohoSyncStatus.PENDING,
        server_default=ReturnZohoSyncStatus.PENDING.value,
    )
    zoho_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    zoho_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    linked_order: Mapped[Optional["Order"]] = relationship("Order", lazy="selectin")
    items: Mapped[list["ReturnItem"]] = relationship(
        "ReturnItem",
        back_populates="record",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("platform", "external_record_key", name="uq_return_record_platform_external_key"),
        CheckConstraint("order_total_amount >= 0", name="ck_return_record_non_negative_total"),
        CheckConstraint("refunded_amount >= 0", name="ck_return_record_non_negative_refunded"),
        Index("ix_return_record_platform", "platform"),
        Index("ix_return_record_normalized_status", "normalized_status"),
        Index("ix_return_record_external_order_id", "external_order_id"),
        Index("ix_return_record_event_at", "event_at"),
        Index("ix_return_record_ordered_at", "ordered_at"),
        Index("ix_return_record_linked_order_id", "linked_order_id"),
        Index("ix_return_record_zoho_salesreturn_id", "zoho_salesreturn_id"),
        Index("ix_return_record_zoho_sync_status", "zoho_sync_status"),
    )


class ReturnItem(Base, TimestampMixin):
    __tablename__ = "return_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    return_record_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("return_record.id", ondelete="CASCADE"),
        nullable=False,
    )
    linked_order_item_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("order_item.id", ondelete="SET NULL"),
        nullable=True,
    )

    external_item_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    external_sku: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    item_name: Mapped[str] = mapped_column(String(500), nullable=False)
    ordered_qty: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    returned_qty: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cancelled_qty: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    item_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    record: Mapped["ReturnRecord"] = relationship("ReturnRecord", back_populates="items")
    linked_order_item: Mapped[Optional["OrderItem"]] = relationship("OrderItem", lazy="selectin")

    __table_args__ = (
        CheckConstraint("ordered_qty >= 0", name="ck_return_item_non_negative_ordered_qty"),
        CheckConstraint("returned_qty >= 0", name="ck_return_item_non_negative_returned_qty"),
        CheckConstraint("cancelled_qty >= 0", name="ck_return_item_non_negative_cancelled_qty"),
        CheckConstraint("refunded_amount >= 0", name="ck_return_item_non_negative_refunded"),
        Index("ix_return_item_record_id", "return_record_id"),
        Index("ix_return_item_linked_order_item_id", "linked_order_item_id"),
        Index("ix_return_item_external_item_id", "external_item_id"),
        Index("ix_return_item_external_sku", "external_sku"),
    )
