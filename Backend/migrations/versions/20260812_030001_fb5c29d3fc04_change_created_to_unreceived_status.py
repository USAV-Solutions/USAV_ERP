"""change_created_to_unreceived_status

Revision ID: fb5c29d3fc04
Revises: c2d3e4f5g6h7
Create Date: 2026-08-12 03:00:01.113227+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb5c29d3fc04'
down_revision: Union[str, None] = 'c2d3e4f5g6h7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires enum value additions to be committed before use.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE purchase_deliver_status_enum ADD VALUE IF NOT EXISTS 'UNRECEIVED'")

    # Update existing rows from 'CREATED' to 'UNRECEIVED'
    op.execute("UPDATE purchase_order SET deliver_status = 'UNRECEIVED' WHERE deliver_status = 'CREATED'")

    # Change column default value to 'UNRECEIVED'
    op.alter_column('purchase_order', 'deliver_status', server_default='UNRECEIVED')


def downgrade() -> None:
    # Change column default value back to 'CREATED'
    op.alter_column('purchase_order', 'deliver_status', server_default='CREATED')

    # Update rows back from 'UNRECEIVED' to 'CREATED'
    op.execute("UPDATE purchase_order SET deliver_status = 'CREATED' WHERE deliver_status = 'UNRECEIVED'")
