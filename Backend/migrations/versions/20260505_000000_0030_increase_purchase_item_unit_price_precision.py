"""increase purchase_order_item.unit_price precision

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "purchase_order_item",
        "unit_price",
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=sa.Numeric(precision=12, scale=6),
        existing_nullable=False,
        postgresql_using="unit_price::numeric(12,6)",
    )

    # Restore precise per-unit values where line totals and rounded unit prices diverged.
    op.execute(
        """
        UPDATE purchase_order_item
        SET unit_price = (total_price / quantity::numeric)
        WHERE quantity > 0
          AND total_price IS NOT NULL
          AND unit_price IS NOT NULL
          AND (unit_price * quantity) <> total_price
        """
    )


def downgrade() -> None:
    op.alter_column(
        "purchase_order_item",
        "unit_price",
        existing_type=sa.Numeric(precision=12, scale=6),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=False,
        postgresql_using="round(unit_price, 2)",
    )
