"""Rename order table to orders

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename table
    op.rename_table("order", "orders")

    # Rename primary key and indexes for clarity
    op.execute("ALTER INDEX IF EXISTS order_pkey RENAME TO orders_pkey")
    op.execute("ALTER INDEX IF EXISTS ix_order_platform RENAME TO ix_orders_platform")
    op.execute("ALTER INDEX IF EXISTS ix_order_status RENAME TO ix_orders_status")
    op.execute("ALTER INDEX IF EXISTS ix_order_ordered_at RENAME TO ix_orders_ordered_at")
    op.execute("ALTER INDEX IF EXISTS ix_order_external_id RENAME TO ix_orders_external_id")

    # Rename constraints
    op.execute(
        "ALTER TABLE orders RENAME CONSTRAINT uq_order_platform_external_id TO uq_orders_platform_external_id"
    )
    op.execute(
        "ALTER TABLE orders RENAME CONSTRAINT ck_order_positive_total TO ck_orders_positive_total"
    )


def downgrade() -> None:
    # Revert constraint names
    op.execute(
        "ALTER TABLE orders RENAME CONSTRAINT ck_orders_positive_total TO ck_order_positive_total"
    )
    op.execute(
        "ALTER TABLE orders RENAME CONSTRAINT uq_orders_platform_external_id TO uq_order_platform_external_id"
    )

    # Revert index names
    op.execute("ALTER INDEX IF EXISTS ix_orders_external_id RENAME TO ix_order_external_id")
    op.execute("ALTER INDEX IF EXISTS ix_orders_ordered_at RENAME TO ix_order_ordered_at")
    op.execute("ALTER INDEX IF EXISTS ix_orders_status RENAME TO ix_order_status")
    op.execute("ALTER INDEX IF EXISTS ix_orders_platform RENAME TO ix_order_platform")
    op.execute("ALTER INDEX IF EXISTS orders_pkey RENAME TO order_pkey")

    # Revert table name
    op.rename_table("orders", "order")
