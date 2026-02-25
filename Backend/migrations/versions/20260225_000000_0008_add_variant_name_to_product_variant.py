"""Add variant_name to product_variant.

Revision ID: 0008
Revises: 0007
Create Date: 2026-02-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_variant",
        sa.Column(
            "variant_name",
            sa.String(length=255),
            nullable=True,
            comment="Canonical display name for this variant (derived from platform listings).",
        ),
    )


def downgrade() -> None:
    op.drop_column("product_variant", "variant_name")
