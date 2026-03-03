"""Add Customer table, Zoho sync columns to Order & ProductVariant.

Phase 1 of the Zoho two-way sync implementation:
  - Creates the ``customer`` table with ZohoSyncMixin columns.
  - Adds ``zoho_last_sync_hash`` and ``zoho_sync_error`` to ``product_variant``.
  - Adds ``customer_id`` FK, ``zoho_id``, ``zoho_last_sync_hash``,
    ``zoho_last_synced_at``, and ``zoho_sync_error`` to ``order``.

Revision ID: 0009
Revises: 0008
Create Date: 2026-02-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create the ``customer`` table
    # ------------------------------------------------------------------
    op.create_table(
        "customer",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # --- ZohoSyncMixin columns ---
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
        # --- Core fields ---
        sa.Column(
            "name",
            sa.String(length=200),
            nullable=False,
            comment="Customer full name.",
        ),
        sa.Column(
            "email",
            sa.String(length=200),
            nullable=True,
            comment="Customer email address.",
        ),
        sa.Column(
            "phone",
            sa.String(length=50),
            nullable=True,
            comment="Customer phone number.",
        ),
        sa.Column(
            "company_name",
            sa.String(length=200),
            nullable=True,
            comment="Company / organisation name.",
        ),
        # --- Address ---
        sa.Column("address_line1", sa.String(length=255), nullable=True),
        sa.Column("address_line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column(
            "country",
            sa.String(length=100),
            nullable=True,
            server_default="US",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Soft-delete flag; maps to Zoho 'inactive' status.",
        ),
        # --- TimestampMixin ---
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Indexes on customer
    op.create_index("ix_customer_email", "customer", ["email"])
    op.create_index("ix_customer_name", "customer", ["name"])
    op.create_index("ix_customer_zoho_id", "customer", ["zoho_id"])

    # ------------------------------------------------------------------
    # 2. Add Zoho sync columns to ``product_variant``
    # ------------------------------------------------------------------
    op.add_column(
        "product_variant",
        sa.Column(
            "zoho_last_sync_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 hash of the last synced payload (echo-loop prevention).",
        ),
    )
    op.add_column(
        "product_variant",
        sa.Column(
            "zoho_sync_error",
            sa.Text(),
            nullable=True,
            comment="Error message from the last failed Zoho sync attempt.",
        ),
    )

    # ------------------------------------------------------------------
    # 3. Add Zoho sync + customer FK columns to ``order``
    # ------------------------------------------------------------------
    op.add_column(
        "order",
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("customer.id", ondelete="SET NULL"),
            nullable=True,
            comment="FK to the normalised Customer record.",
        ),
    )
    op.add_column(
        "order",
        sa.Column(
            "zoho_id",
            sa.String(length=50),
            nullable=True,
            comment="Zoho Inventory record ID.",
        ),
    )
    op.add_column(
        "order",
        sa.Column(
            "zoho_last_sync_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 hash of the last synced payload (echo-loop prevention).",
        ),
    )
    op.add_column(
        "order",
        sa.Column(
            "zoho_last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of the last successful Zoho sync.",
        ),
    )
    op.add_column(
        "order",
        sa.Column(
            "zoho_sync_error",
            sa.Text(),
            nullable=True,
            comment="Error message from the last failed Zoho sync attempt.",
        ),
    )
    op.create_index("ix_order_customer_id", "order", ["customer_id"])
    op.create_index("ix_order_zoho_id", "order", ["zoho_id"])


def downgrade() -> None:
    # Order columns
    op.drop_index("ix_order_zoho_id", table_name="order")
    op.drop_index("ix_order_customer_id", table_name="order")
    op.drop_column("order", "zoho_sync_error")
    op.drop_column("order", "zoho_last_synced_at")
    op.drop_column("order", "zoho_last_sync_hash")
    op.drop_column("order", "zoho_id")
    op.drop_column("order", "customer_id")

    # ProductVariant columns
    op.drop_column("product_variant", "zoho_sync_error")
    op.drop_column("product_variant", "zoho_last_sync_hash")

    # Customer table
    op.drop_index("ix_customer_zoho_id", table_name="customer")
    op.drop_index("ix_customer_name", table_name="customer")
    op.drop_index("ix_customer_email", table_name="customer")
    op.drop_table("customer")
