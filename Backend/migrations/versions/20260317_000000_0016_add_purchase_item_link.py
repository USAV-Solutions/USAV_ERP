"""Add purchase_item_link to purchase_order_item

Revision ID: 0016
Revises: 0015
Create Date: 2026-03-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_order_item", sa.Column("purchase_item_link", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_order_item", "purchase_item_link")
