"""Add queued and syncing Zoho statuses

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-07-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c2d3e4f5g6h7"
down_revision: Union[str, None] = "b1c2d3e4f5g6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE zoho_sync_status_enum ADD VALUE IF NOT EXISTS 'QUEUED'")
    op.execute("ALTER TYPE zoho_sync_status_enum ADD VALUE IF NOT EXISTS 'SYNCING'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in place.
    pass
