"""Add full-text indexes for variant search

Revision ID: 0014
Revises: 0013
Create Date: 2026-03-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_product_family_base_name_fts
        ON product_family
        USING gin (to_tsvector('simple', coalesce(base_name, '')))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_product_variant_full_sku_fts
        ON product_variant
        USING gin (to_tsvector('simple', coalesce(full_sku, '')))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_product_variant_variant_name_fts
        ON product_variant
        USING gin (to_tsvector('simple', coalesce(variant_name, '')))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_product_variant_variant_name_fts")
    op.execute("DROP INDEX IF EXISTS ix_product_variant_full_sku_fts")
    op.execute("DROP INDEX IF EXISTS ix_product_family_base_name_fts")
