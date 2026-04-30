"""Add shipping_address_line3 to orders.

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("shipping_address_line3", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "shipping_address_line3")
