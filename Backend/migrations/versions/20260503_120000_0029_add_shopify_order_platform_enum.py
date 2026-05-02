"""add SHOPIFY to order platform enum

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-03 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE order_platform_enum ADD VALUE IF NOT EXISTS 'SHOPIFY'")


def downgrade() -> None:
    # PostgreSQL enum value removal is non-trivial and intentionally omitted.
    pass
