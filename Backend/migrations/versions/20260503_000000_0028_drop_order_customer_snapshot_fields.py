"""drop duplicated customer and shipping snapshot fields from orders

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_customer_from_orders() -> None:
    # Copy latest known non-empty order snapshot values into customer rows
    # before dropping the duplicated order columns.
    op.execute(
        """
        UPDATE customer c
        SET name = src.customer_name
        FROM (
            SELECT DISTINCT ON (customer_id)
                customer_id, customer_name
            FROM orders
            WHERE customer_id IS NOT NULL
              AND customer_name IS NOT NULL
              AND btrim(customer_name) <> ''
            ORDER BY customer_id, id DESC
        ) src
        WHERE c.id = src.customer_id
          AND (c.name IS NULL OR btrim(c.name) = '' OR c.name = 'Unknown')
        """
    )
    op.execute(
        """
        UPDATE customer c
        SET email = src.customer_email
        FROM (
            SELECT DISTINCT ON (customer_id)
                customer_id, customer_email
            FROM orders
            WHERE customer_id IS NOT NULL
              AND customer_email IS NOT NULL
              AND btrim(customer_email) <> ''
            ORDER BY customer_id, id DESC
        ) src
        WHERE c.id = src.customer_id
          AND (c.email IS NULL OR btrim(c.email) = '')
        """
    )
    op.execute(
        """
        UPDATE customer c
        SET address_line1 = src.shipping_address_line1
        FROM (
            SELECT DISTINCT ON (customer_id)
                customer_id, shipping_address_line1
            FROM orders
            WHERE customer_id IS NOT NULL
              AND shipping_address_line1 IS NOT NULL
              AND btrim(shipping_address_line1) <> ''
            ORDER BY customer_id, id DESC
        ) src
        WHERE c.id = src.customer_id
          AND (c.address_line1 IS NULL OR btrim(c.address_line1) = '')
        """
    )
    op.execute(
        """
        UPDATE customer c
        SET address_line2 = src.shipping_address_line2
        FROM (
            SELECT DISTINCT ON (customer_id)
                customer_id, shipping_address_line2
            FROM orders
            WHERE customer_id IS NOT NULL
              AND shipping_address_line2 IS NOT NULL
              AND btrim(shipping_address_line2) <> ''
            ORDER BY customer_id, id DESC
        ) src
        WHERE c.id = src.customer_id
          AND (c.address_line2 IS NULL OR btrim(c.address_line2) = '')
        """
    )
    op.execute(
        """
        UPDATE customer c
        SET city = src.shipping_city
        FROM (
            SELECT DISTINCT ON (customer_id)
                customer_id, shipping_city
            FROM orders
            WHERE customer_id IS NOT NULL
              AND shipping_city IS NOT NULL
              AND btrim(shipping_city) <> ''
            ORDER BY customer_id, id DESC
        ) src
        WHERE c.id = src.customer_id
          AND (c.city IS NULL OR btrim(c.city) = '')
        """
    )
    op.execute(
        """
        UPDATE customer c
        SET state = src.shipping_state
        FROM (
            SELECT DISTINCT ON (customer_id)
                customer_id, shipping_state
            FROM orders
            WHERE customer_id IS NOT NULL
              AND shipping_state IS NOT NULL
              AND btrim(shipping_state) <> ''
            ORDER BY customer_id, id DESC
        ) src
        WHERE c.id = src.customer_id
          AND (c.state IS NULL OR btrim(c.state) = '')
        """
    )
    op.execute(
        """
        UPDATE customer c
        SET postal_code = src.shipping_postal_code
        FROM (
            SELECT DISTINCT ON (customer_id)
                customer_id, shipping_postal_code
            FROM orders
            WHERE customer_id IS NOT NULL
              AND shipping_postal_code IS NOT NULL
              AND btrim(shipping_postal_code) <> ''
            ORDER BY customer_id, id DESC
        ) src
        WHERE c.id = src.customer_id
          AND (c.postal_code IS NULL OR btrim(c.postal_code) = '')
        """
    )
    op.execute(
        """
        UPDATE customer c
        SET country = src.shipping_country
        FROM (
            SELECT DISTINCT ON (customer_id)
                customer_id, shipping_country
            FROM orders
            WHERE customer_id IS NOT NULL
              AND shipping_country IS NOT NULL
              AND btrim(shipping_country) <> ''
            ORDER BY customer_id, id DESC
        ) src
        WHERE c.id = src.customer_id
          AND (c.country IS NULL OR btrim(c.country) = '')
        """
    )


def upgrade() -> None:
    _backfill_customer_from_orders()
    op.drop_column("orders", "customer_name")
    op.drop_column("orders", "customer_email")
    op.drop_column("orders", "shipping_address_line1")
    op.drop_column("orders", "shipping_address_line2")
    op.drop_column("orders", "shipping_address_line3")
    op.drop_column("orders", "shipping_city")
    op.drop_column("orders", "shipping_state")
    op.drop_column("orders", "shipping_postal_code")
    op.drop_column("orders", "shipping_country")


def downgrade() -> None:
    op.add_column("orders", sa.Column("shipping_country", sa.String(length=100), nullable=True, server_default="US"))
    op.add_column("orders", sa.Column("shipping_postal_code", sa.String(length=20), nullable=True))
    op.add_column("orders", sa.Column("shipping_state", sa.String(length=100), nullable=True))
    op.add_column("orders", sa.Column("shipping_city", sa.String(length=100), nullable=True))
    op.add_column("orders", sa.Column("shipping_address_line3", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("shipping_address_line2", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("shipping_address_line1", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("customer_email", sa.String(length=200), nullable=True))
    op.add_column("orders", sa.Column("customer_name", sa.String(length=200), nullable=True))
