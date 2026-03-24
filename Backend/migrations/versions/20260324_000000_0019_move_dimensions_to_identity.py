"""move dimensions and weight from family to identity

Revision ID: 0019
Revises: 0018
Create Date: 2026-03-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("product_identity", sa.Column("dimension_length", sa.Numeric(10, 2), nullable=True))
    op.add_column("product_identity", sa.Column("dimension_width", sa.Numeric(10, 2), nullable=True))
    op.add_column("product_identity", sa.Column("dimension_height", sa.Numeric(10, 2), nullable=True))
    op.add_column("product_identity", sa.Column("weight", sa.Numeric(10, 2), nullable=True))

    op.execute(
        """
        UPDATE product_identity pi
        SET
            dimension_length = pf.dimension_length,
            dimension_width = pf.dimension_width,
            dimension_height = pf.dimension_height,
            weight = pf.weight
        FROM product_family pf
        WHERE pi.product_id = pf.product_id
        """
    )

    op.drop_column("product_family", "dimension_length")
    op.drop_column("product_family", "dimension_width")
    op.drop_column("product_family", "dimension_height")
    op.drop_column("product_family", "weight")


def downgrade() -> None:
    op.add_column("product_family", sa.Column("dimension_length", sa.Numeric(10, 2), nullable=True))
    op.add_column("product_family", sa.Column("dimension_width", sa.Numeric(10, 2), nullable=True))
    op.add_column("product_family", sa.Column("dimension_height", sa.Numeric(10, 2), nullable=True))
    op.add_column("product_family", sa.Column("weight", sa.Numeric(10, 2), nullable=True))

    op.execute(
        """
        UPDATE product_family pf
        SET
            dimension_length = src.dimension_length,
            dimension_width = src.dimension_width,
            dimension_height = src.dimension_height,
            weight = src.weight
        FROM (
            SELECT
                product_id,
                MAX(dimension_length) AS dimension_length,
                MAX(dimension_width) AS dimension_width,
                MAX(dimension_height) AS dimension_height,
                MAX(weight) AS weight
            FROM product_identity
            GROUP BY product_id
        ) src
        WHERE pf.product_id = src.product_id
        """
    )

    op.drop_column("product_identity", "dimension_length")
    op.drop_column("product_identity", "dimension_width")
    op.drop_column("product_identity", "dimension_height")
    op.drop_column("product_identity", "weight")