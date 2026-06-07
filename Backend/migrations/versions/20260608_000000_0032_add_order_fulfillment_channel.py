"""add order fulfillment channel

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    fulfillment_enum = sa.Enum(
        "SELF_FULFILLED",
        "AMAZON_FBA",
        name="order_fulfillment_channel_enum",
    )
    fulfillment_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "orders",
        sa.Column(
            "fulfillment_channel",
            fulfillment_enum,
            nullable=False,
            server_default="SELF_FULFILLED",
        ),
    )
    op.create_index("ix_order_fulfillment_channel", "orders", ["fulfillment_channel"])

    op.execute(
        """
        UPDATE orders
        SET fulfillment_channel = 'SELF_FULFILLED'
        WHERE fulfillment_channel IS NULL;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_order_fulfillment_channel", table_name="orders")
    op.drop_column("orders", "fulfillment_channel")
    sa.Enum(name="order_fulfillment_channel_enum").drop(op.get_bind(), checkfirst=True)
