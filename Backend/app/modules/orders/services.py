"""
Order Services.

Business logic for order processing, SKU matching, and inventory allocation.
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.orders.models import Order, OrderItem, OrderPlatform, OrderStatus, OrderItemStatus
from app.models.entities import PlatformListing, ProductVariant, InventoryItem, InventoryStatus, Platform
from app.integrations.base import ExternalOrder
from app.core.config import settings

import logging

logger = logging.getLogger(__name__)


class OrderService:
    """Service class for order operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_order(self, order_data: dict, items_data: list[dict]) -> Order:
        """
        Create a new order with items.
        
        Args:
            order_data: Order header data
            items_data: List of order item data
            
        Returns:
            Created Order with items
        """
        # Calculate totals
        total_price = sum(
            Decimal(str(item.get("quantity", 1))) * Decimal(str(item["unit_price"]))
            for item in items_data
        )
        
        order = Order(
            **order_data,
            status=OrderStatus.PENDING,
        )
        
        self.db.add(order)
        await self.db.flush()  # Get order ID
        
        # Create order items
        for item_data in items_data:
            quantity = item_data.get("quantity", 1)
            unit_price = Decimal(str(item_data["unit_price"]))
            total = quantity * unit_price
            
            item = OrderItem(
                order_id=order.id,
                item_name=item_data["item_name"],
                quantity=quantity,
                unit_price=unit_price,
                total_price=total,
                external_item_id=item_data.get("external_item_id"),
                external_sku=item_data.get("external_sku"),
                external_asin=item_data.get("external_asin"),
                item_metadata=item_data.get("item_metadata"),
                status=OrderItemStatus.UNMATCHED,
            )
            self.db.add(item)
        
        await self.db.flush()
        return order
    
    async def get_order(self, order_id: int) -> Optional[Order]:
        """Get an order by ID with items."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id)
        )
        return result.scalar_one_or_none()
    
    async def get_order_by_external_id(
        self, 
        platform: OrderPlatform, 
        external_order_id: str
    ) -> Optional[Order]:
        """Get an order by platform and external ID."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.platform == platform,
                Order.external_order_id == external_order_id
            )
        )
        return result.scalar_one_or_none()
    
    async def list_orders(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[OrderStatus] = None,
        platform: Optional[OrderPlatform] = None,
    ) -> List[Order]:
        """List orders with optional filtering."""
        query = select(Order).options(selectinload(Order.items))
        
        if status:
            query = query.where(Order.status == status)
        if platform:
            query = query.where(Order.platform == platform)
        
        query = query.order_by(Order.created_at.desc()).offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def count_orders(
        self,
        status: Optional[OrderStatus] = None,
        platform: Optional[OrderPlatform] = None,
    ) -> int:
        """Count orders with optional filtering."""
        query = select(func.count(Order.id))
        
        if status:
            query = query.where(Order.status == status)
        if platform:
            query = query.where(Order.platform == platform)
        
        result = await self.db.execute(query)
        return result.scalar() or 0
    
    async def update_order_status(
        self, 
        order_id: int, 
        status: OrderStatus,
        notes: Optional[str] = None
    ) -> Optional[Order]:
        """Update order status."""
        order = await self.get_order(order_id)
        if not order:
            return None
        
        order.status = status
        if notes:
            order.processing_notes = notes
        
        if status == OrderStatus.SHIPPED:
            order.shipped_at = datetime.now()
        
        await self.db.flush()
        return order
    
    async def auto_match_sku(self, order_item: OrderItem) -> bool:
        """
        Attempt to automatically match an order item to an internal SKU.
        
        Matching strategy:
        1. Try matching by platform listing external_ref_id (ASIN, eBay Item ID)
        2. Try matching by external_sku to variant full_sku
        
        Returns:
            True if match found, False otherwise
        """
        # Convert OrderPlatform to Platform for listing lookup
        platform_map = {
            OrderPlatform.AMAZON: Platform.AMAZON,
            OrderPlatform.EBAY_MEKONG: Platform.EBAY_MEKONG,
            OrderPlatform.EBAY_USAV: Platform.EBAY_USAV,
            OrderPlatform.EBAY_DRAGON: Platform.EBAY_DRAGON,
            OrderPlatform.ECWID: Platform.ECWID,
        }
        
        # Get parent order for platform info
        order = await self.db.get(Order, order_item.order_id)
        if not order:
            return False
        
        # Strategy 1: Match by ASIN (Amazon)
        if order_item.external_asin:
            result = await self.db.execute(
                select(PlatformListing)
                .where(
                    PlatformListing.external_ref_id == order_item.external_asin,
                    PlatformListing.platform == Platform.AMAZON
                )
            )
            listing = result.scalar_one_or_none()
            if listing:
                order_item.variant_id = listing.variant_id
                order_item.status = OrderItemStatus.MATCHED
                order_item.matching_notes = f"Auto-matched by ASIN: {order_item.external_asin}"
                await self.db.flush()
                return True
        
        # Strategy 2: Match by platform listing external ref
        if order.platform in platform_map:
            platform_enum = platform_map[order.platform]
            if order_item.external_item_id:
                result = await self.db.execute(
                    select(PlatformListing)
                    .where(
                        PlatformListing.external_ref_id == order_item.external_item_id,
                        PlatformListing.platform == platform_enum
                    )
                )
                listing = result.scalar_one_or_none()
                if listing:
                    order_item.variant_id = listing.variant_id
                    order_item.status = OrderItemStatus.MATCHED
                    order_item.matching_notes = f"Auto-matched by platform item ID: {order_item.external_item_id}"
                    await self.db.flush()
                    return True
        
        # Strategy 3: Match by SKU directly
        if order_item.external_sku:
            result = await self.db.execute(
                select(ProductVariant)
                .where(ProductVariant.full_sku == order_item.external_sku.upper())
            )
            variant = result.scalar_one_or_none()
            if variant:
                order_item.variant_id = variant.id
                order_item.status = OrderItemStatus.MATCHED
                order_item.matching_notes = f"Auto-matched by SKU: {order_item.external_sku}"
                await self.db.flush()
                return True
        
        return False
    
    async def match_sku_manually(
        self,
        order_item_id: int,
        variant_id: int,
        notes: Optional[str] = None
    ) -> Optional[OrderItem]:
        """Manually match an order item to a variant."""
        item = await self.db.get(OrderItem, order_item_id)
        if not item:
            return None
        
        # Verify variant exists
        variant = await self.db.get(ProductVariant, variant_id)
        if not variant:
            return None
        
        item.variant_id = variant_id
        item.status = OrderItemStatus.MATCHED
        item.matching_notes = notes or f"Manually matched to SKU: {variant.full_sku}"
        
        await self.db.flush()
        return item
    
    async def allocate_inventory(
        self,
        order_item_id: int,
        inventory_item_id: int
    ) -> Optional[OrderItem]:
        """
        Allocate a specific inventory item to an order item.
        
        This reserves the inventory item and links it to the order.
        """
        item = await self.db.get(OrderItem, order_item_id)
        if not item:
            return None
        
        # Verify inventory item exists and is available
        inventory = await self.db.get(InventoryItem, inventory_item_id)
        if not inventory or inventory.status != InventoryStatus.AVAILABLE:
            return None
        
        # Verify SKU match
        if item.variant_id != inventory.variant_id:
            return None
        
        # Reserve inventory
        inventory.status = InventoryStatus.RESERVED
        item.allocated_inventory_id = inventory_item_id
        item.status = OrderItemStatus.ALLOCATED
        
        await self.db.flush()
        return item
    
    async def process_incoming_order(self, order_data: dict, items_data: list[dict]) -> Order:
        """
        Process a new incoming order from an external platform.
        
        1. Create the order record
        2. Attempt auto-matching for all items
        3. Update order status based on matching results
        """
        # Create order
        order = await self.create_order(order_data, items_data)
        
        # Reload with items
        order = await self.get_order(order.id)
        
        # Auto-match items
        all_matched = True
        for item in order.items:
            matched = await self.auto_match_sku(item)
            if not matched:
                all_matched = False
        
        # Update order status
        if all_matched:
            order.status = OrderStatus.PROCESSING
            order.processing_notes = "All items auto-matched"
        else:
            order.status = OrderStatus.PENDING
            unmatched = sum(1 for i in order.items if i.status == OrderItemStatus.UNMATCHED)
            order.processing_notes = f"{unmatched} item(s) require manual SKU matching"
        
        await self.db.flush()
        return order
    
    async def sync_orders_from_platform(
        self,
        platform: OrderPlatform,
        order_date: date
    ) -> dict:
        """
        Sync orders from an external platform for a specific date.
        
        Args:
            platform: The platform to sync from (EBAY_MEKONG, EBAY_USAV, EBAY_DRAGON, ECWID)
            order_date: The date to fetch orders from
            
        Returns:
            Dictionary with sync results (total, new, existing, errors)
        """
        logger.info(f"Starting order sync from {platform.value} for date {order_date}")
        
        # Import clients here to avoid circular imports
        from app.integrations.ebay.client import EbayClient
        from app.integrations.ecwid.client import EcwidClient
        
        # Initialize the appropriate client based on platform
        client = None
        
        if platform == OrderPlatform.EBAY_MEKONG:
            client = EbayClient(
                store_name="MEKONG",
                app_id=settings.ebay_app_id,
                cert_id=settings.ebay_cert_id,
                refresh_token=settings.ebay_refresh_token_mekong,
                sandbox=settings.ebay_sandbox,
            )
        elif platform == OrderPlatform.EBAY_USAV:
            client = EbayClient(
                store_name="USAV",
                app_id=settings.ebay_app_id,
                cert_id=settings.ebay_cert_id,
                refresh_token=settings.ebay_refresh_token_usav,
                sandbox=settings.ebay_sandbox,
            )
        elif platform == OrderPlatform.EBAY_DRAGON:
            client = EbayClient(
                store_name="DRAGON",
                app_id=settings.ebay_app_id,
                cert_id=settings.ebay_cert_id,
                refresh_token=settings.ebay_refresh_token_dragon,
                sandbox=settings.ebay_sandbox,
            )
        elif platform == OrderPlatform.ECWID:
            client = EcwidClient(
                store_id=settings.ecwid_store_id,
                access_token=settings.ecwid_secret,
                api_base_url=settings.ecwid_api_base_url,
            )
        else:
            raise ValueError(f"Platform {platform} not supported for sync")
        
        if not client.is_configured:
            raise ValueError(f"Platform {platform} is not properly configured")
        
        # Fetch orders from the platform
        try:
            external_orders: List[ExternalOrder] = await client.fetch_daily_orders(order_date)
            logger.info(f"Fetched {len(external_orders)} orders from {platform.value}")
        except Exception as e:
            logger.error(f"Error fetching orders from {platform.value}: {e}", exc_info=True)
            return {
                "total_fetched": 0,
                "new_orders": 0,
                "existing_orders": 0,
                "errors": 1,
                "error_message": str(e)
            }
        
        # Process each order
        new_count = 0
        existing_count = 0
        error_count = 0
        
        for ext_order in external_orders:
            try:
                # Check if order already exists
                existing = await self.get_order_by_external_id(
                    platform=platform,
                    external_order_id=ext_order.platform_order_id
                )
                
                if existing:
                    logger.debug(f"Order {ext_order.platform_order_id} already exists, skipping")
                    existing_count += 1
                    continue
                
                # Create order data
                order_data = {
                    "platform": platform,
                    "external_order_id": ext_order.platform_order_id,
                    "external_order_number": ext_order.platform_order_number,
                    "customer_name": ext_order.customer_name,
                    "customer_email": ext_order.customer_email,
                    "ship_address_line1": ext_order.ship_address_line1,
                    "ship_address_line2": ext_order.ship_address_line2,
                    "ship_city": ext_order.ship_city,
                    "ship_state": ext_order.ship_state,
                    "ship_postal_code": ext_order.ship_postal_code,
                    "ship_country": ext_order.ship_country,
                    "subtotal_amount": ext_order.subtotal,
                    "tax_amount": ext_order.tax,
                    "shipping_amount": ext_order.shipping,
                    "total_amount": ext_order.total,
                    "currency": ext_order.currency,
                    "ordered_at": ext_order.ordered_at,
                    "order_metadata": ext_order.raw_data,
                }
                
                # Prepare items data
                items_data = []
                for ext_item in ext_order.items:
                    item_data = {
                        "item_name": ext_item.title,
                        "quantity": ext_item.quantity,
                        "unit_price": ext_item.unit_price,
                        "external_item_id": ext_item.platform_item_id,
                        "external_sku": ext_item.platform_sku,
                        "external_asin": ext_item.asin,
                        "item_metadata": ext_item.raw_data,
                    }
                    items_data.append(item_data)
                
                # Process the order (create + auto-match)
                await self.process_incoming_order(order_data, items_data)
                new_count += 1
                logger.info(f"Created order {ext_order.platform_order_id} from {platform.value}")
                
            except Exception as e:
                logger.error(
                    f"Error processing order {ext_order.platform_order_id}: {e}",
                    exc_info=True
                )
                error_count += 1
        
        # Commit all changes
        await self.db.commit()
        
        result = {
            "total_fetched": len(external_orders),
            "new_orders": new_count,
            "existing_orders": existing_count,
            "errors": error_count,
        }
        
        logger.info(f"Order sync completed: {result}")
        return result
    
    async def get_order_summary(self) -> dict:
        """Get summary statistics for orders."""
        # Count by status
        pending = await self.count_orders(status=OrderStatus.PENDING)
        processing = await self.count_orders(status=OrderStatus.PROCESSING)
        ready_to_ship = await self.count_orders(status=OrderStatus.READY_TO_SHIP)
        shipped = await self.count_orders(status=OrderStatus.SHIPPED)
        errors = await self.count_orders(status=OrderStatus.ERROR)
        total = await self.count_orders()
        
        # Total revenue (shipped orders)
        revenue_result = await self.db.execute(
            select(func.sum(Order.total_amount))
            .where(Order.status == OrderStatus.SHIPPED)
        )
        total_revenue = revenue_result.scalar() or Decimal("0")
        
        # Unmatched items
        unmatched_result = await self.db.execute(
            select(func.count(OrderItem.id))
            .where(OrderItem.status == OrderItemStatus.UNMATCHED)
        )
        unmatched_items = unmatched_result.scalar() or 0
        
        return {
            "total_orders": total,
            "pending_orders": pending,
            "processing_orders": processing,
            "ready_to_ship_orders": ready_to_ship,
            "shipped_orders": shipped,
            "orders_with_errors": errors,
            "total_revenue": total_revenue,
            "unmatched_items": unmatched_items,
        }

