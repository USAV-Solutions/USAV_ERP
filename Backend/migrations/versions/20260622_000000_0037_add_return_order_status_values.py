"""add return order status values

Revision ID: 0037
Revises: 0036
Create Date: 2026-06-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE order_status_enum ADD VALUE IF NOT EXISTS 'PARTIALLY_REFUNDED'")
    op.execute("ALTER TYPE order_status_enum ADD VALUE IF NOT EXISTS 'RETURN'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be dropped safely without rebuilding the type.
    pass
