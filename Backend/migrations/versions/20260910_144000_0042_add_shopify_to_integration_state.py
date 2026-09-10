"""add SHOPIFY to integration_state

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-10 14:40:00.000000+00:00
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO integration_state (platform_name, current_status, last_successful_sync)
        VALUES ('SHOPIFY', 'IDLE', '2026-01-01T00:00:00+00:00')
        ON CONFLICT (platform_name) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM integration_state WHERE platform_name = 'SHOPIFY'")
