"""Add purchasing module (vendor, purchase_order, purchase_order_item)

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum types ---
    purchase_deliver_status_enum = postgresql.ENUM(
        "CREATED",
        "BILLED",
        "DELIVERED",
        name="purchase_deliver_status_enum",
        create_type=False,
    )
    purchase_deliver_status_enum.create(op.get_bind(), checkfirst=True)

    purchase_order_item_status_enum = postgresql.ENUM(
        "UNMATCHED",
        "MATCHED",
        "RECEIVED",
        name="purchase_order_item_status_enum",
        create_type=False,
    )
    purchase_order_item_status_enum.create(op.get_bind(), checkfirst=True)

    # --- vendor table ---
    op.create_table(
        "vendor",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
            comment="Vendor legal/trading name.",
        ),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # ZohoSyncMixin columns
        sa.Column(
            "zoho_id",
            sa.String(length=50),
            nullable=True,
            comment="Zoho Inventory record ID.",
        ),
        sa.Column(
            "zoho_last_sync_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 hash of the last synced payload (echo-loop prevention).",
        ),
        sa.Column(
            "zoho_last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of the last successful Zoho sync.",
        ),
        sa.Column(
            "zoho_sync_error",
            sa.Text(),
            nullable=True,
            comment="Error message from the last failed Zoho sync attempt.",
        ),
        # TimestampMixin columns
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_vendor_name", "vendor", ["name"])
    op.create_index("ix_vendor_zoho_id", "vendor", ["zoho_id"])

    # --- purchase_order table ---
    op.create_table(
        "purchase_order",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "po_number",
            sa.String(length=100),
            nullable=False,
            comment="Human-readable purchase order reference.",
        ),
        sa.Column("vendor_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "deliver_status",
            purchase_deliver_status_enum,
            nullable=False,
            server_default="CREATED",
        ),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        # ZohoSyncMixin columns
        sa.Column(
            "zoho_id",
            sa.String(length=50),
            nullable=True,
            comment="Zoho Inventory record ID.",
        ),
        sa.Column(
            "zoho_last_sync_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 hash of the last synced payload (echo-loop prevention).",
        ),
        sa.Column(
            "zoho_last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of the last successful Zoho sync.",
        ),
        sa.Column(
            "zoho_sync_error",
            sa.Text(),
            nullable=True,
            comment="Error message from the last failed Zoho sync attempt.",
        ),
        # TimestampMixin columns
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("po_number", name="uq_purchase_order_po_number"),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendor.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_purchase_order_vendor_id", "purchase_order", ["vendor_id"])
    op.create_index("ix_purchase_order_status", "purchase_order", ["deliver_status"])
    op.create_index("ix_purchase_order_zoho_id", "purchase_order", ["zoho_id"])

    # --- purchase_order_item table ---
    op.create_table(
        "purchase_order_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("purchase_order_id", sa.BigInteger(), nullable=False),
        sa.Column("variant_id", sa.BigInteger(), nullable=True),
        sa.Column("external_item_name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "unit_price",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_price",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            purchase_order_item_status_enum,
            nullable=False,
            server_default="UNMATCHED",
        ),
        # TimestampMixin columns
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_order.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variant.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_purchase_order_item_po_id",
        "purchase_order_item",
        ["purchase_order_id"],
    )
    op.create_index(
        "ix_purchase_order_item_variant_id",
        "purchase_order_item",
        ["variant_id"],
    )
    op.create_index(
        "ix_purchase_order_item_status",
        "purchase_order_item",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("purchase_order_item")
    op.drop_table("purchase_order")
    op.drop_table("vendor")

    op.execute("DROP TYPE IF EXISTS purchase_order_item_status_enum")
    op.execute("DROP TYPE IF EXISTS purchase_deliver_status_enum")
