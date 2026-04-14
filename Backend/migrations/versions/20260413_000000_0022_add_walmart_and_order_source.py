"""Add Walmart platform support and orders.source column.

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            ALTER TYPE order_platform_enum ADD VALUE IF NOT EXISTS 'WALMART';
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'WALMART';
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.add_column(
        "orders",
        sa.Column("source", sa.String(length=50), nullable=False, server_default="MANUAL"),
    )
    op.create_index("ix_order_source", "orders", ["source"])

    op.execute(
        """
        UPDATE orders
        SET source = CASE
            WHEN platform = 'ECWID' THEN 'ECWID_API'
            WHEN platform = 'EBAY_MEKONG' THEN 'EBAY_MEKONG_API'
            WHEN platform = 'EBAY_USAV' THEN 'EBAY_USAV_API'
            WHEN platform = 'EBAY_DRAGON' THEN 'EBAY_DRAGON_API'
            WHEN platform = 'AMAZON' THEN 'AMAZON_API'
            WHEN platform = 'WALMART' THEN 'WALMART_API'
            WHEN platform = 'ZOHO' THEN 'ZOHO_IMPORT'
            ELSE 'MANUAL'
        END
        WHERE source = 'MANUAL' OR source IS NULL;
        """
    )

    op.execute(
        """
        INSERT INTO integration_state (platform_name, current_status, last_successful_sync)
        VALUES ('WALMART', 'IDLE', '2026-01-01T00:00:00+00:00')
        ON CONFLICT (platform_name) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM integration_state WHERE platform_name = 'WALMART'")
    op.drop_index("ix_order_source", table_name="orders")
    op.drop_column("orders", "source")
