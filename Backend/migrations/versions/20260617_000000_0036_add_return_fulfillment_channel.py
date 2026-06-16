"""add return fulfillment channel

Revision ID: 0036
Revises: 469482e42773
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: Union[str, None] = "469482e42773"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    fulfillment_enum = postgresql.ENUM(
        "SELF_FULFILLED",
        "AMAZON_FBA",
        name="return_order_fulfillment_channel_enum",
        create_type=False,
    )
    fulfillment_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "return_record",
        sa.Column(
            "fulfillment_channel",
            fulfillment_enum,
            nullable=False,
            server_default="SELF_FULFILLED",
        ),
    )
    op.create_index("ix_return_record_fulfillment_channel", "return_record", ["fulfillment_channel"])


def downgrade() -> None:
    op.drop_index("ix_return_record_fulfillment_channel", table_name="return_record")
    op.drop_column("return_record", "fulfillment_channel")
    postgresql.ENUM(name="return_order_fulfillment_channel_enum").drop(op.get_bind(), checkfirst=True)
