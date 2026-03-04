"""Add zoho_sync_status to orders

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    zoho_sync_status_enum = postgresql.ENUM(
        "PENDING",
        "SYNCED",
        "ERROR",
        "DIRTY",
        name="zoho_sync_status_enum",
        create_type=False,
    )

    op.add_column(
        "orders",
        sa.Column(
            "zoho_sync_status",
            zoho_sync_status_enum,
            nullable=False,
            server_default="PENDING",
            comment="Outbound Zoho sync status.",
        ),
    )
    op.create_index("ix_orders_zoho_sync_status", "orders", ["zoho_sync_status"])


def downgrade() -> None:
    op.drop_index("ix_orders_zoho_sync_status", table_name="orders")
    op.drop_column("orders", "zoho_sync_status")
