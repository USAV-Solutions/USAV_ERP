"""add AMAZON_RENEW, AMAZON_FBA, WALK_IN to platform and order enums

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'AMAZON_RENEW'")
        op.execute("ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'AMAZON_FBA'")
        op.execute("ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'WALK_IN'")
        op.execute("ALTER TYPE order_platform_enum ADD VALUE IF NOT EXISTS 'AMAZON_RENEW'")
        op.execute("ALTER TYPE order_platform_enum ADD VALUE IF NOT EXISTS 'AMAZON_FBA'")
        op.execute("ALTER TYPE order_platform_enum ADD VALUE IF NOT EXISTS 'WALK_IN'")
        op.execute("ALTER TYPE return_order_platform_enum ADD VALUE IF NOT EXISTS 'AMAZON_RENEW'")
        op.execute("ALTER TYPE return_order_platform_enum ADD VALUE IF NOT EXISTS 'AMAZON_FBA'")
        op.execute("ALTER TYPE return_order_platform_enum ADD VALUE IF NOT EXISTS 'WALK_IN'")


def downgrade() -> None:
    pass
