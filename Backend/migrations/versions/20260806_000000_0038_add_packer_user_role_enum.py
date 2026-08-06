"""add PACKER to user role enum

Revision ID: 0038
Revises: c2d3e4f5g6h7
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0038"
down_revision: Union[str, None] = "c2d3e4f5g6h7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'PACKER'")


def downgrade() -> None:
    # PostgreSQL enum value removal is non-trivial and intentionally omitted.
    pass
