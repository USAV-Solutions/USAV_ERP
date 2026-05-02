"""add platform listing quantity/type/condition/upc fields

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-01 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("platform_listing", sa.Column("listing_quantity", sa.Integer(), nullable=True))
    op.add_column("platform_listing", sa.Column("listing_type", sa.String(length=100), nullable=True))
    op.add_column("platform_listing", sa.Column("listing_condition", sa.String(length=100), nullable=True))
    op.add_column("platform_listing", sa.Column("upc", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("platform_listing", "upc")
    op.drop_column("platform_listing", "listing_condition")
    op.drop_column("platform_listing", "listing_type")
    op.drop_column("platform_listing", "listing_quantity")
