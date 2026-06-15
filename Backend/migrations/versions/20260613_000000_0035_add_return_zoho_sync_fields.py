"""add return zoho sync fields

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    return_zoho_sync_status_enum = postgresql.ENUM(
        "PENDING",
        "READY_TO_SYNC",
        "MISSING_LOCAL_ORDER",
        "MISSING_ZOHO_ORDER",
        "MISSING_LINE_ITEM_MAPPING",
        "QUANTITY_CONFLICT",
        "ALREADY_SYNCED",
        "SYNCED",
        "ERROR",
        name="return_zoho_sync_status_enum",
        create_type=False,
    )
    return_zoho_sync_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column("return_record", sa.Column("zoho_salesreturn_id", sa.String(length=50), nullable=True))
    op.add_column("return_record", sa.Column("zoho_salesreturn_number", sa.String(length=100), nullable=True))
    op.add_column(
        "return_record",
        sa.Column(
            "zoho_sync_status",
            return_zoho_sync_status_enum,
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column("return_record", sa.Column("zoho_sync_error", sa.Text(), nullable=True))
    op.add_column("return_record", sa.Column("zoho_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_return_record_zoho_salesreturn_id", "return_record", ["zoho_salesreturn_id"])
    op.create_index("ix_return_record_zoho_sync_status", "return_record", ["zoho_sync_status"])


def downgrade() -> None:
    op.drop_index("ix_return_record_zoho_sync_status", table_name="return_record")
    op.drop_index("ix_return_record_zoho_salesreturn_id", table_name="return_record")
    op.drop_column("return_record", "zoho_synced_at")
    op.drop_column("return_record", "zoho_sync_error")
    op.drop_column("return_record", "zoho_sync_status")
    op.drop_column("return_record", "zoho_salesreturn_number")
    op.drop_column("return_record", "zoho_salesreturn_id")
    postgresql.ENUM(name="return_zoho_sync_status_enum").drop(op.get_bind(), checkfirst=True)
