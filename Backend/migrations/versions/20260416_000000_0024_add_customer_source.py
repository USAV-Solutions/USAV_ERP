"""Add customer source column.

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customer", sa.Column("source", sa.String(length=50), nullable=True))
    op.create_index("ix_customer_source", "customer", ["source"])


def downgrade() -> None:
    op.drop_index("ix_customer_source", table_name="customer")
    op.drop_column("customer", "source")
