"""add zoho_marked_as_fulfilled to orders

Revision ID: a1b2c3d4e5f6
Revises: ef489e27f5ff
Create Date: 2026-07-13 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ef489e27f5ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('zoho_marked_as_fulfilled', sa.Boolean(), server_default='false', nullable=False, comment='Whether this order was successfully marked as fulfilled in Zoho.'))


def downgrade() -> None:
    op.drop_column('orders', 'zoho_marked_as_fulfilled')
