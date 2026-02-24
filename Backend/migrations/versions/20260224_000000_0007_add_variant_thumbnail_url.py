"""Add thumbnail_url to product_variant.

Revision ID: 0007
Revises: 0006
Create Date: 2026-02-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'product_variant',
        sa.Column(
            'thumbnail_url',
            sa.String(length=1024),
            nullable=True,
            comment='Precomputed public URL for this variant thumbnail (served directly by Nginx).',
        ),
    )


def downgrade() -> None:
    op.drop_column('product_variant', 'thumbnail_url')
