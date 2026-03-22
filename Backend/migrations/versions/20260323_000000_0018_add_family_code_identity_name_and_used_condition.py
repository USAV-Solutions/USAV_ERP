"""add family_code, identity_name, and explicit used condition code

Revision ID: 0018
Revises: 0017
Create Date: 2026-03-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add explicit Used condition code for product_variant.condition_code enum.
    op.execute("ALTER TYPE condition_code_enum ADD VALUE IF NOT EXISTS 'U'")

    # Product family now has a persisted, deterministic family_code.
    op.add_column(
        "product_family",
        sa.Column("family_code", sa.String(length=5), nullable=True),
    )
    op.execute(
        """
        UPDATE product_family
        SET family_code = LPAD(product_id::text, 5, '0')
        WHERE family_code IS NULL
        """
    )
    op.alter_column("product_family", "family_code", nullable=False)
    op.create_unique_constraint("uq_product_family_family_code", "product_family", ["family_code"])

    # Optional naming field used by the restart importer and bundle/part resolution.
    op.add_column(
        "product_identity",
        sa.Column("identity_name", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_identity_identity_name", "product_identity", ["identity_name"])
    op.execute(
        """
        UPDATE product_identity pi
        SET identity_name = pf.base_name
        FROM product_family pf
        WHERE pi.product_id = pf.product_id
          AND pi.type = 'Product'::identity_type_enum
          AND pi.identity_name IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_identity_identity_name", table_name="product_identity")
    op.drop_column("product_identity", "identity_name")

    op.drop_constraint("uq_product_family_family_code", "product_family", type_="unique")
    op.drop_column("product_family", "family_code")

    # Downgrade enum by recreating it without U. Existing U values are coerced to NULL.
    op.execute(
        """
        UPDATE product_variant
        SET condition_code = NULL
        WHERE condition_code::text = 'U'
        """
    )

    op.execute("ALTER TYPE condition_code_enum RENAME TO condition_code_enum_old")
    new_enum = postgresql.ENUM("N", "R", name="condition_code_enum")
    new_enum.create(op.get_bind(), checkfirst=True)
    op.execute(
        """
        ALTER TABLE product_variant
        ALTER COLUMN condition_code TYPE condition_code_enum
        USING condition_code::text::condition_code_enum
        """
    )
    op.execute("DROP TYPE condition_code_enum_old")
