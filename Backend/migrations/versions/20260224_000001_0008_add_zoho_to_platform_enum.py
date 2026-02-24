"""Add ZOHO to platform_enum.

Revision ID: 0008
Revises: 0007
Create Date: 2026-02-24 00:00:01.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'ZOHO'")


def downgrade() -> None:
    # PostgreSQL enum value removals are non-trivial and unsafe in-place.
    # Intentionally left as no-op.
    pass
