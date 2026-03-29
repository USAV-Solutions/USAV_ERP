"""add condition_note to purchase_order_item

Revision ID: 0020
Revises: 0019
Create Date: 2026-03-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_order_item", sa.Column("condition_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_order_item", "condition_note")
