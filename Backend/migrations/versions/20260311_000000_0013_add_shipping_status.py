"""Add shipping_status column to orders table

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type
    shipping_status_enum = postgresql.ENUM(
        "PENDING",
        "ON_HOLD",
        "CANCELLED",
        "PACKED",
        "SHIPPING",
        "DELIVERED",
        name="shipping_status_enum",
        create_type=False,
    )
    shipping_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "orders",
        sa.Column(
            "shipping_status",
            sa.Enum(
                "PENDING", "ON_HOLD", "CANCELLED", "PACKED", "SHIPPING", "DELIVERED",
                name="shipping_status_enum",
                create_constraint=False,
            ),
            nullable=False,
            server_default="PENDING",
            comment="Shipping / fulfilment status (PENDING → PACKED → SHIPPING → DELIVERED).",
        ),
    )
    op.create_index("ix_orders_shipping_status", "orders", ["shipping_status"])


def downgrade() -> None:
    op.drop_index("ix_orders_shipping_status", table_name="orders")
    op.drop_column("orders", "shipping_status")

    shipping_status_enum = postgresql.ENUM(
        "PENDING", "ON_HOLD", "CANCELLED", "PACKED", "SHIPPING", "DELIVERED",
        name="shipping_status_enum",
    )
    shipping_status_enum.drop(op.get_bind(), checkfirst=True)
