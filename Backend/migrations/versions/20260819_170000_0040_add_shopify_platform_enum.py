"""add SHOPIFY to platform enum

Revision ID: 0040
Revises: fb5c29d3fc04
Create Date: 2026-08-19 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0040'
down_revision: Union[str, None] = 'fb5c29d3fc04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add SHOPIFY to the platform_enum type
    # This is used by the platform_listing table
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'SHOPIFY'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values
    pass
