"""Add purchase_order Zoho billing state columns.

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_order",
        sa.Column("zoho_bill_created", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "purchase_order",
        sa.Column("zoho_payment_created", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "purchase_order",
        sa.Column("zoho_billed_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "purchase_order",
        sa.Column("zoho_bill_id", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "purchase_order",
        sa.Column("zoho_payment_id", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "purchase_order",
        sa.Column("zoho_billing_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("purchase_order", "zoho_billing_error")
    op.drop_column("purchase_order", "zoho_payment_id")
    op.drop_column("purchase_order", "zoho_bill_id")
    op.drop_column("purchase_order", "zoho_billed_checked_at")
    op.drop_column("purchase_order", "zoho_payment_created")
    op.drop_column("purchase_order", "zoho_bill_created")
