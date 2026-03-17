"""Add zoho_sync_status to purchase_order

Revision ID: 0017
Revises: 0016
Create Date: 2026-03-17 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_order",
        sa.Column(
            "zoho_sync_status",
            sa.Enum("PENDING", "SYNCED", "ERROR", "DIRTY", name="zoho_sync_status_enum", create_constraint=False),
            nullable=False,
            server_default="DIRTY",
        ),
    )
    op.create_index("ix_purchase_order_zoho_sync_status", "purchase_order", ["zoho_sync_status"])

    # Backfill historical rows imported from Zoho as synced, everything else dirty.
    op.execute(
        """
        UPDATE purchase_order
        SET zoho_sync_status = CASE
            WHEN zoho_id IS NOT NULL THEN 'SYNCED'::zoho_sync_status_enum
            ELSE 'DIRTY'::zoho_sync_status_enum
        END
        """
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_order_zoho_sync_status", table_name="purchase_order")
    op.drop_column("purchase_order", "zoho_sync_status")
