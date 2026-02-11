"""Add integration_state table for sync memory.

Revision ID: 0006
Revises: 0005
Create Date: 2026-02-10 00:00:00.000000
"""
from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add ECWID to order_platform_enum if not already present
    op.execute("""
        DO $$ BEGIN
            ALTER TYPE order_platform_enum ADD VALUE IF NOT EXISTS 'ECWID';
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create enum for integration sync status
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE integration_sync_status_enum AS ENUM (
                'IDLE', 'SYNCING', 'ERROR'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create integration_state table
    op.create_table(
        'integration_state',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            'platform_name', sa.String(length=50), nullable=False,
            comment='Logical platform key, e.g. AMAZON, EBAY_USAV.',
        ),
        sa.Column(
            'last_successful_sync', sa.DateTime(timezone=True), nullable=True,
            comment='Anchor timestamp for the next fetch window.',
        ),
        sa.Column(
            'current_status',
            postgresql.ENUM('IDLE', 'SYNCING', 'ERROR',
                            name='integration_sync_status_enum',
                            create_type=False),
            nullable=False,
            server_default='IDLE',
            comment='IDLE | SYNCING | ERROR.',
        ),
        sa.Column(
            'last_error_message', sa.Text(), nullable=True,
            comment='Debugging info if last sync failed.',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('platform_name', name='uq_integration_state_platform'),
    )

    # Seed initial rows for every supported platform
    op.execute("""
        INSERT INTO integration_state (platform_name, current_status, last_successful_sync)
        VALUES
            ('AMAZON',      'IDLE', '2026-01-01T00:00:00+00:00'),
            ('EBAY_MEKONG', 'IDLE', '2026-01-01T00:00:00+00:00'),
            ('EBAY_USAV',   'IDLE', '2026-01-01T00:00:00+00:00'),
            ('EBAY_DRAGON', 'IDLE', '2026-01-01T00:00:00+00:00'),
            ('ECWID',       'IDLE', '2026-01-01T00:00:00+00:00')
        ON CONFLICT (platform_name) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_table('integration_state')
    op.execute("DROP TYPE IF EXISTS integration_sync_status_enum")
