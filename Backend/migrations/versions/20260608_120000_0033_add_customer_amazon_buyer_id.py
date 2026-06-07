"""add customer amazon buyer id

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-08 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer",
        sa.Column(
            "amazon_buyer_id",
            sa.String(length=120),
            nullable=True,
            comment="Stable Amazon FBA buyer identifier used for customer matching and Zoho contact naming.",
        ),
    )
    op.create_index("ix_customer_amazon_buyer_id", "customer", ["amazon_buyer_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_amazon_buyer_id", table_name="customer")
    op.drop_column("customer", "amazon_buyer_id")
