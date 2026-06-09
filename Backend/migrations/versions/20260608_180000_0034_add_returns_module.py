"""add returns module tables

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-08 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    return_sync_status_enum = postgresql.ENUM(
        "IDLE",
        "SYNCING",
        "ERROR",
        name="return_integration_sync_status_enum",
        create_type=False,
    )
    return_sync_status_enum.create(op.get_bind(), checkfirst=True)

    return_platform_enum = postgresql.ENUM(
        "AMAZON",
        "EBAY_MEKONG",
        "EBAY_USAV",
        "EBAY_DRAGON",
        "ECWID",
        "SHOPIFY",
        "WALMART",
        "ZOHO",
        "MANUAL",
        name="return_order_platform_enum",
        create_type=False,
    )
    return_platform_enum.create(op.get_bind(), checkfirst=True)

    return_normalized_status_enum = postgresql.ENUM(
        "RETURNED",
        "PARTIALLY_RETURNED",
        "REFUNDED",
        "PARTIALLY_REFUNDED",
        "CANCELLED",
        "PARTIALLY_CANCELLED",
        "UNKNOWN",
        name="return_normalized_status_enum",
        create_type=False,
    )
    return_normalized_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "return_sync_state",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("platform_name", sa.String(length=50), nullable=False),
        sa.Column("last_successful_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "current_status",
            return_sync_status_enum,
            nullable=False,
            server_default="IDLE",
        ),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform_name"),
    )

    op.create_table(
        "return_record",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "platform",
            return_platform_enum,
            nullable=False,
        ),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="MANUAL"),
        sa.Column("external_record_key", sa.String(length=150), nullable=False),
        sa.Column("external_order_id", sa.String(length=100), nullable=False),
        sa.Column("external_return_id", sa.String(length=100), nullable=True),
        sa.Column("linked_order_id", sa.BigInteger(), nullable=True),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("customer_email", sa.String(length=200), nullable=True),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "normalized_status",
            return_normalized_status_enum,
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column("source_status", sa.String(length=100), nullable=True),
        sa.Column("source_substatus", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("order_total_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("refunded_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("order_total_amount >= 0", name="ck_return_record_non_negative_total"),
        sa.CheckConstraint("refunded_amount >= 0", name="ck_return_record_non_negative_refunded"),
        sa.ForeignKeyConstraint(["linked_order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_record_key", name="uq_return_record_platform_external_key"),
    )
    op.create_index("ix_return_record_platform", "return_record", ["platform"])
    op.create_index("ix_return_record_normalized_status", "return_record", ["normalized_status"])
    op.create_index("ix_return_record_external_order_id", "return_record", ["external_order_id"])
    op.create_index("ix_return_record_event_at", "return_record", ["event_at"])
    op.create_index("ix_return_record_ordered_at", "return_record", ["ordered_at"])
    op.create_index("ix_return_record_linked_order_id", "return_record", ["linked_order_id"])

    op.create_table(
        "return_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("return_record_id", sa.BigInteger(), nullable=False),
        sa.Column("linked_order_item_id", sa.BigInteger(), nullable=True),
        sa.Column("external_item_id", sa.String(length=100), nullable=True),
        sa.Column("external_sku", sa.String(length=100), nullable=True),
        sa.Column("item_name", sa.String(length=500), nullable=False),
        sa.Column("ordered_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("returned_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancelled_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refunded_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("item_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ordered_qty >= 0", name="ck_return_item_non_negative_ordered_qty"),
        sa.CheckConstraint("returned_qty >= 0", name="ck_return_item_non_negative_returned_qty"),
        sa.CheckConstraint("cancelled_qty >= 0", name="ck_return_item_non_negative_cancelled_qty"),
        sa.CheckConstraint("refunded_amount >= 0", name="ck_return_item_non_negative_refunded"),
        sa.ForeignKeyConstraint(["linked_order_item_id"], ["order_item.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["return_record_id"], ["return_record.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_return_item_record_id", "return_item", ["return_record_id"])
    op.create_index("ix_return_item_linked_order_item_id", "return_item", ["linked_order_item_id"])
    op.create_index("ix_return_item_external_item_id", "return_item", ["external_item_id"])
    op.create_index("ix_return_item_external_sku", "return_item", ["external_sku"])

    op.execute(
        """
        INSERT INTO return_sync_state (platform_name, current_status, last_successful_sync)
        VALUES
            ('EBAY_MEKONG', 'IDLE', '2026-01-01T00:00:00+00:00'),
            ('EBAY_USAV', 'IDLE', '2026-01-01T00:00:00+00:00'),
            ('EBAY_DRAGON', 'IDLE', '2026-01-01T00:00:00+00:00'),
            ('ECWID', 'IDLE', '2026-01-01T00:00:00+00:00'),
            ('WALMART', 'IDLE', '2026-01-01T00:00:00+00:00')
        ON CONFLICT (platform_name) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_return_item_external_sku", table_name="return_item")
    op.drop_index("ix_return_item_external_item_id", table_name="return_item")
    op.drop_index("ix_return_item_linked_order_item_id", table_name="return_item")
    op.drop_index("ix_return_item_record_id", table_name="return_item")
    op.drop_table("return_item")

    op.drop_index("ix_return_record_linked_order_id", table_name="return_record")
    op.drop_index("ix_return_record_ordered_at", table_name="return_record")
    op.drop_index("ix_return_record_event_at", table_name="return_record")
    op.drop_index("ix_return_record_external_order_id", table_name="return_record")
    op.drop_index("ix_return_record_normalized_status", table_name="return_record")
    op.drop_index("ix_return_record_platform", table_name="return_record")
    op.drop_table("return_record")

    op.drop_table("return_sync_state")

    postgresql.ENUM(name="return_normalized_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="return_order_platform_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="return_integration_sync_status_enum").drop(op.get_bind(), checkfirst=True)
