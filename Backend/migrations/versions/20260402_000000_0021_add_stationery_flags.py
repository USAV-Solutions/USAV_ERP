"""add stationery flags for identity and purchase order

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_identity",
        sa.Column("is_stationery", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_check_constraint(
        "ck_identity_stationery_product_only",
        "product_identity",
        "(is_stationery = false) OR (type = 'Product')",
    )
    op.create_index("ix_identity_is_stationery", "product_identity", ["is_stationery"], unique=False)

    op.add_column(
        "purchase_order",
        sa.Column("is_stationery", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("purchase_order", "is_stationery")

    op.drop_index("ix_identity_is_stationery", table_name="product_identity")
    op.drop_constraint("ck_identity_stationery_product_only", "product_identity", type_="check")
    op.drop_column("product_identity", "is_stationery")
