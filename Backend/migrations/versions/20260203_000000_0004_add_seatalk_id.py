"""Add seatalk_id column to users table

Revision ID: 0004
Revises: 0003
Create Date: 2026-02-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add seatalk_id column to users table for SeaTalk OAuth integration."""
    op.add_column(
        'users',
        sa.Column(
            'seatalk_id',
            sa.String(100),
            nullable=True,
            unique=True,
            comment='SeaTalk employee code for OAuth login.'
        )
    )
    op.create_index('ix_users_seatalk_id', 'users', ['seatalk_id'], unique=True)


def downgrade() -> None:
    """Remove seatalk_id column from users table."""
    op.drop_index('ix_users_seatalk_id', table_name='users')
    op.drop_column('users', 'seatalk_id')
