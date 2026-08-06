"""add ebay purchasing enum

Revision ID: b1c2d3e4f5g6
Revises: a1b2c3d4e5f6
Create Date: 2026-07-17 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5g6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'EBAY_PURCHASING'")
        op.execute("ALTER TYPE order_platform_enum ADD VALUE IF NOT EXISTS 'EBAY_PURCHASING'")


def downgrade() -> None:
    pass
