"""Add order tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-02-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create order_platform_enum using raw SQL to avoid duplicate error
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE order_platform_enum AS ENUM (
                'AMAZON', 'EBAY_MEKONG', 'EBAY_USAV', 'EBAY_DRAGON', 'ZOHO', 'MANUAL'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create order_status_enum using raw SQL to avoid duplicate error
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE order_status_enum AS ENUM (
                'PENDING', 'PROCESSING', 'READY_TO_SHIP', 'SHIPPED', 
                'DELIVERED', 'CANCELLED', 'REFUNDED', 'ON_HOLD', 'ERROR'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create order_item_status_enum using raw SQL to avoid duplicate error
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE order_item_status_enum AS ENUM (
                'UNMATCHED', 'MATCHED', 'ALLOCATED', 'SHIPPED', 'CANCELLED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create order table
    op.create_table(
        'order',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('platform', postgresql.ENUM('AMAZON', 'EBAY_MEKONG', 'EBAY_USAV', 'EBAY_DRAGON', 'ZOHO', 'MANUAL', name='order_platform_enum', create_type=False), nullable=False, comment='Source platform (AMAZON, EBAY, etc.).'),
        sa.Column('external_order_id', sa.String(length=100), nullable=False, comment='Order ID on the external platform.'),
        sa.Column('external_order_number', sa.String(length=100), nullable=True, comment='Human-readable order number (if different from ID).'),
        sa.Column('status', postgresql.ENUM('PENDING', 'PROCESSING', 'READY_TO_SHIP', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED', 'ON_HOLD', 'ERROR', name='order_status_enum', create_type=False), nullable=False, comment='Current order processing status.'),
        
        # Customer info
        sa.Column('customer_name', sa.String(length=200), nullable=True, comment='Customer full name.'),
        sa.Column('customer_email', sa.String(length=200), nullable=True, comment='Customer email address.'),
        
        # Shipping address
        sa.Column('shipping_address_line1', sa.String(length=255), nullable=True),
        sa.Column('shipping_address_line2', sa.String(length=255), nullable=True),
        sa.Column('shipping_city', sa.String(length=100), nullable=True),
        sa.Column('shipping_state', sa.String(length=100), nullable=True),
        sa.Column('shipping_postal_code', sa.String(length=20), nullable=True),
        sa.Column('shipping_country', sa.String(length=100), nullable=True, server_default='US'),
        
        # Financial
        sa.Column('subtotal_amount', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0', comment='Order subtotal before tax/shipping.'),
        sa.Column('tax_amount', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0', comment='Total tax amount.'),
        sa.Column('shipping_amount', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0', comment='Shipping cost.'),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False, comment='Total order amount.'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD', comment='Currency code (ISO 4217).'),
        
        # Timestamps
        sa.Column('ordered_at', sa.DateTime(timezone=True), nullable=True, comment='When the order was placed on the platform.'),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True, comment='When the order was shipped.'),
        
        # Tracking
        sa.Column('tracking_number', sa.String(length=100), nullable=True, comment='Shipment tracking number.'),
        sa.Column('carrier', sa.String(length=50), nullable=True, comment='Shipping carrier (UPS, FedEx, USPS).'),
        
        # Metadata
        sa.Column('platform_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Raw platform-specific order data.'),
        sa.Column('processing_notes', sa.Text(), nullable=True, comment='Internal notes about order processing.'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='Error message if processing failed.'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('platform', 'external_order_id', name='uq_order_platform_external_id'),
        sa.CheckConstraint('total_amount >= 0', name='ck_order_positive_total'),
    )
    
    # Create indexes for order table
    op.create_index('ix_order_platform', 'order', ['platform'])
    op.create_index('ix_order_status', 'order', ['status'])
    op.create_index('ix_order_ordered_at', 'order', ['ordered_at'])
    op.create_index('ix_order_external_id', 'order', ['external_order_id'])
    
    # Create order_item table
    op.create_table(
        'order_item',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False, comment='Parent order.'),
        
        # External identification
        sa.Column('external_item_id', sa.String(length=100), nullable=True, comment='Item ID on the external platform.'),
        sa.Column('external_sku', sa.String(length=100), nullable=True, comment='SKU as listed on the platform.'),
        sa.Column('external_asin', sa.String(length=20), nullable=True, comment='Amazon ASIN (if Amazon order).'),
        
        # Internal matching
        sa.Column('variant_id', sa.BigInteger(), nullable=True, comment='Matched internal product variant.'),
        sa.Column('allocated_inventory_id', sa.BigInteger(), nullable=True, comment='Allocated physical inventory item.'),
        
        sa.Column('status', postgresql.ENUM('UNMATCHED', 'MATCHED', 'ALLOCATED', 'SHIPPED', 'CANCELLED', name='order_item_status_enum', create_type=False), nullable=False, comment='Item processing status.'),
        
        # Item details
        sa.Column('item_name', sa.String(length=500), nullable=False, comment='Item name/title from the platform.'),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1', comment='Quantity ordered.'),
        sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False, comment='Price per unit.'),
        sa.Column('total_price', sa.Numeric(precision=12, scale=2), nullable=False, comment='Total price (quantity * unit_price).'),
        
        # Metadata
        sa.Column('item_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Platform-specific item data.'),
        sa.Column('matching_notes', sa.Text(), nullable=True, comment='Notes about SKU matching process.'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['order_id'], ['order.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['variant_id'], ['product_variant.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['allocated_inventory_id'], ['inventory_item.id'], ondelete='SET NULL'),
        sa.CheckConstraint('quantity > 0', name='ck_order_item_positive_quantity'),
        sa.CheckConstraint('unit_price >= 0', name='ck_order_item_non_negative_price'),
    )
    
    # Create indexes for order_item table
    op.create_index('ix_order_item_order_id', 'order_item', ['order_id'])
    op.create_index('ix_order_item_variant_id', 'order_item', ['variant_id'])
    op.create_index('ix_order_item_status', 'order_item', ['status'])
    op.create_index('ix_order_item_external_sku', 'order_item', ['external_sku'])
    op.create_index('ix_order_item_external_asin', 'order_item', ['external_asin'])


def downgrade() -> None:
    # Drop order_item table and indexes
    op.drop_index('ix_order_item_external_asin', table_name='order_item')
    op.drop_index('ix_order_item_external_sku', table_name='order_item')
    op.drop_index('ix_order_item_status', table_name='order_item')
    op.drop_index('ix_order_item_variant_id', table_name='order_item')
    op.drop_index('ix_order_item_order_id', table_name='order_item')
    op.drop_table('order_item')
    
    # Drop order table and indexes
    op.drop_index('ix_order_external_id', table_name='order')
    op.drop_index('ix_order_ordered_at', table_name='order')
    op.drop_index('ix_order_status', table_name='order')
    op.drop_index('ix_order_platform', table_name='order')
    op.drop_table('order')
    
    # Drop enums using raw SQL
    op.execute("DROP TYPE IF EXISTS order_item_status_enum")
    op.execute("DROP TYPE IF EXISTS order_status_enum")
    op.execute("DROP TYPE IF EXISTS order_platform_enum")

