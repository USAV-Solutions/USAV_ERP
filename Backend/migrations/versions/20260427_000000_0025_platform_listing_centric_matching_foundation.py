"""Platform listing-centric matching foundation.

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) platform_listing: variant nullable + merchant_sku
    op.add_column(
        "platform_listing",
        sa.Column("merchant_sku", sa.String(length=100), nullable=True),
    )
    op.alter_column(
        "platform_listing",
        "variant_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )

    # 2) order_item: add platform_listing_id
    op.add_column(
        "order_item",
        sa.Column("platform_listing_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_order_item_platform_listing_id_platform_listing",
        "order_item",
        "platform_listing",
        ["platform_listing_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_order_item_platform_listing_id",
        "order_item",
        ["platform_listing_id"],
        unique=False,
    )

    # 3) replace listing constraints/indexes
    op.drop_constraint("uq_listing_variant_platform", "platform_listing", type_="unique")
    op.drop_index("ix_listing_external_ref", table_name="platform_listing")

    # Normalize blank external refs and dedupe existing rows before
    # enforcing unique (platform, external_ref_id).
    op.execute(
        """
        UPDATE platform_listing
        SET external_ref_id = NULL
        WHERE external_ref_id IS NOT NULL
          AND btrim(external_ref_id) = ''
        """
    )
    op.execute(
        """
        DELETE FROM platform_listing pl
        USING platform_listing dup
        WHERE pl.platform = dup.platform
          AND pl.external_ref_id = dup.external_ref_id
          AND pl.external_ref_id IS NOT NULL
          AND pl.id > dup.id
        """
    )

    op.create_index(
        "ix_listing_external_ref",
        "platform_listing",
        ["platform", "external_ref_id"],
        unique=True,
        postgresql_where=sa.text("external_ref_id IS NOT NULL"),
    )
    op.create_index(
        "ix_listing_platform_merchant_sku",
        "platform_listing",
        ["platform", "merchant_sku"],
        unique=False,
    )

    # 4) data backfill:
    # backfill order_item.platform_listing_id from existing variant_id + order.platform
    # using enum text compare because order/platform enums are different SQL enum types.
    op.execute(
        """
        UPDATE order_item AS oi
        SET platform_listing_id = pl.id
        FROM orders AS o, platform_listing AS pl
        WHERE oi.order_id = o.id
          AND oi.variant_id IS NOT NULL
          AND oi.platform_listing_id IS NULL
          AND pl.variant_id = oi.variant_id
          AND pl.platform::text = o.platform::text
        """
    )


def downgrade() -> None:
    # Drop new indexes first
    op.drop_index("ix_listing_platform_merchant_sku", table_name="platform_listing")
    op.drop_index("ix_listing_external_ref", table_name="platform_listing")

    # Restore pre-existing non-unique external ref index
    op.create_index(
        "ix_listing_external_ref",
        "platform_listing",
        ["platform", "external_ref_id"],
        unique=False,
    )

    # Restore unique constraint (best effort)
    op.create_unique_constraint(
        "uq_listing_variant_platform",
        "platform_listing",
        ["variant_id", "platform"],
    )

    # Remove order_item.platform_listing_id
    op.drop_index("ix_order_item_platform_listing_id", table_name="order_item")
    op.drop_constraint(
        "fk_order_item_platform_listing_id_platform_listing",
        "order_item",
        type_="foreignkey",
    )
    op.drop_column("order_item", "platform_listing_id")

    # Remove merchant_sku and enforce legacy NOT NULL on variant_id
    op.drop_column("platform_listing", "merchant_sku")
    op.alter_column(
        "platform_listing",
        "variant_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
