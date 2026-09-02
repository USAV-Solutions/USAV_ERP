"""add orders.tracking_last_checked_at

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-01 00:00:00.000000+00:00

Supports the server-side tracking-status scraper (parcelsapp.com). The column
records when an order's tracking status was last checked so the scrape queue can
skip recently-checked orders and safely resume after an interruption.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "tracking_last_checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time the tracking status was checked against parcelsapp.",
        ),
    )
    op.create_index(
        "ix_orders_tracking_last_checked_at",
        "orders",
        ["tracking_last_checked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_tracking_last_checked_at", table_name="orders")
    op.drop_column("orders", "tracking_last_checked_at")
