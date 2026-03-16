"""Add Goodwill CSV import fields to purchasing tables

Revision ID: 0015
Revises: 0014
Create Date: 2026-03-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_order", sa.Column("tracking_number", sa.String(length=100), nullable=True))
    op.add_column(
        "purchase_order",
        sa.Column("tax_amount", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
    )
    op.add_column(
        "purchase_order",
        sa.Column("shipping_amount", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
    )
    op.add_column(
        "purchase_order",
        sa.Column("handling_amount", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
    )
    op.add_column(
        "purchase_order",
        sa.Column("source", sa.String(length=50), nullable=False, server_default="MANUAL"),
    )

    op.add_column("purchase_order_item", sa.Column("external_item_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_order_item", "external_item_id")

    op.drop_column("purchase_order", "source")
    op.drop_column("purchase_order", "handling_amount")
    op.drop_column("purchase_order", "shipping_amount")
    op.drop_column("purchase_order", "tax_amount")
    op.drop_column("purchase_order", "tracking_number")
