"""
USAV Inventory Worker Service.

Background worker that handles:
- Order syncing from external platforms (Amazon, eBay)
- Inventory level sync to external platforms
- Zoho sync operations

This runs as a separate Docker container from the API service.
"""
import asyncio
import logging
import sys
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import engine, async_session_factory
from app.modules.orders.models import Order, OrderItem, OrderPlatform, OrderStatus
from app.modules.orders.services import OrderService
from app.integrations.amazon.client import AmazonClient
from app.integrations.ebay.client import EbayClient
from app.integrations.zoho.client import ZohoClient
from app.integrations.base import PlatformClientFactory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("worker")


# ============================================================================
# WORKER CONFIGURATION
# ============================================================================

class WorkerConfig:
    """Worker configuration settings."""
    
    # How often to check for new orders (seconds)
    ORDER_SYNC_INTERVAL: int = 300  # 5 minutes
    
    # How often to push stock updates (seconds)
    STOCK_SYNC_INTERVAL: int = 600  # 10 minutes
    
    # How often to run health checks (seconds)
    HEALTH_CHECK_INTERVAL: int = 60  # 1 minute
    
    # How far back to look for orders on initial sync
    INITIAL_ORDER_LOOKBACK_HOURS: int = 24
    
    # Max orders to fetch per sync cycle
    MAX_ORDERS_PER_SYNC: int = 100


# ============================================================================
# PLATFORM CLIENTS INITIALIZATION
# ============================================================================

def init_platform_clients():
    """Initialize platform clients with credentials from settings."""
    clients = {}
    
    # Amazon client (if credentials configured)
    if settings.amazon_refresh_token:
        clients["AMAZON"] = AmazonClient(
            refresh_token=settings.amazon_refresh_token,
            client_id=settings.amazon_client_id,
            client_secret=settings.amazon_client_secret,
        )
        logger.info("Amazon client initialized")
    
    # eBay clients (multiple stores)
    for store_name in ["MEKONG", "USAV", "DRAGON"]:
        env_prefix = f"EBAY_{store_name}"
        app_id = getattr(settings, f"{env_prefix.lower()}_app_id", None)
        if app_id:
            clients[f"EBAY_{store_name}"] = EbayClient(
                store_name=store_name,
                app_id=app_id,
                cert_id=getattr(settings, f"{env_prefix.lower()}_cert_id", None),
                user_token=getattr(settings, f"{env_prefix.lower()}_user_token", None),
            )
            logger.info(f"eBay {store_name} client initialized")
    
    # Zoho client
    if settings.zoho_client_id:
        clients["ZOHO"] = ZohoClient()
        logger.info("Zoho client initialized")
    
    return clients


# ============================================================================
# WORKER TASKS
# ============================================================================

async def sync_orders_from_platform(
    platform_name: str,
    client,
    db_session: AsyncSession,
    since: Optional[datetime] = None,
):
    """
    Sync orders from a single platform.
    
    Args:
        platform_name: Platform identifier (AMAZON, EBAY_MEKONG, etc.)
        client: Platform client instance
        db_session: Database session
        since: Only fetch orders after this time
    """
    logger.info(f"Syncing orders from {platform_name} since {since}")
    
    try:
        # Authenticate
        if not await client.authenticate():
            logger.warning(f"Failed to authenticate with {platform_name}")
            return
        
        # Fetch orders
        external_orders = await client.fetch_orders(since=since)
        logger.info(f"Fetched {len(external_orders)} orders from {platform_name}")
        
        if not external_orders:
            return
        
        order_service = OrderService(db_session)
        
        # Map platform name to OrderPlatform enum
        platform_map = {
            "AMAZON": OrderPlatform.AMAZON,
            "EBAY_MEKONG": OrderPlatform.EBAY_MEKONG,
            "EBAY_USAV": OrderPlatform.EBAY_USAV,
            "EBAY_DRAGON": OrderPlatform.EBAY_DRAGON,
        }
        
        platform_enum = platform_map.get(platform_name)
        if not platform_enum:
            logger.warning(f"Unknown platform: {platform_name}")
            return
        
        # Process each order
        created = 0
        skipped = 0
        for ext_order in external_orders:
            # Check if order already exists
            existing = await order_service.get_order_by_external_id(
                platform_enum,
                ext_order.platform_order_id
            )
            
            if existing:
                skipped += 1
                continue
            
            # Create order data
            order_data = {
                "platform": platform_enum,
                "external_order_id": ext_order.platform_order_id,
                "external_order_number": ext_order.platform_order_number,
                "customer_name": ext_order.customer_name,
                "customer_email": ext_order.customer_email,
                "shipping_address_line1": ext_order.ship_address_line1,
                "shipping_address_line2": ext_order.ship_address_line2,
                "shipping_city": ext_order.ship_city,
                "shipping_state": ext_order.ship_state,
                "shipping_postal_code": ext_order.ship_postal_code,
                "shipping_country": ext_order.ship_country,
                "subtotal_amount": ext_order.subtotal,
                "tax_amount": ext_order.tax,
                "shipping_amount": ext_order.shipping,
                "total_amount": ext_order.total,
                "currency": ext_order.currency,
                "ordered_at": ext_order.ordered_at,
                "platform_data": ext_order.raw_data,
            }
            
            # Create items data
            items_data = [
                {
                    "item_name": item.title,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "external_item_id": item.platform_item_id,
                    "external_sku": item.platform_sku,
                    "external_asin": item.asin,
                    "item_metadata": item.raw_data,
                }
                for item in ext_order.items
            ]
            
            # Process the order (creates and auto-matches)
            try:
                await order_service.process_incoming_order(order_data, items_data)
                created += 1
            except Exception as e:
                logger.error(f"Failed to create order {ext_order.platform_order_id}: {e}")
        
        await db_session.commit()
        logger.info(f"Order sync complete for {platform_name}: {created} created, {skipped} skipped")
        
    except Exception as e:
        logger.error(f"Error syncing orders from {platform_name}: {e}")
        await db_session.rollback()


async def sync_stock_to_platforms(
    clients: dict,
    db_session: AsyncSession,
):
    """
    Push stock level updates to all connected platforms.
    
    This queries variants with dirty sync status and pushes updates.
    """
    logger.info("Starting stock sync to platforms")
    
    # TODO: Query variants/listings that need sync
    # For each platform, batch the updates and push
    
    for platform_name, client in clients.items():
        if platform_name == "ZOHO":
            continue  # Zoho has separate sync
        
        try:
            # Get listings pending sync for this platform
            # updates = await get_pending_stock_updates(db_session, platform_name)
            # results = await client.update_stock(updates)
            # Process results...
            pass
        except Exception as e:
            logger.error(f"Error syncing stock to {platform_name}: {e}")


async def run_health_checks(clients: dict):
    """Run health checks on all platform connections."""
    for platform_name, client in clients.items():
        try:
            healthy = await client.health_check() if hasattr(client, 'health_check') else True
            status = "healthy" if healthy else "unhealthy"
            logger.debug(f"Platform {platform_name}: {status}")
        except Exception as e:
            logger.warning(f"Health check failed for {platform_name}: {e}")


# ============================================================================
# MAIN WORKER LOOP
# ============================================================================

async def worker_main():
    """
    Main worker loop.
    
    Runs continuously, performing periodic tasks:
    - Order syncing from external platforms
    - Stock level sync to platforms
    - Health checks
    """
    logger.info("=" * 60)
    logger.info("🚀 USAV Inventory Worker Starting")
    logger.info(f"📊 Environment: {settings.environment}")
    logger.info(f"🔗 Database: {settings.db_host}:{settings.db_port}/{settings.db_name}")
    logger.info("=" * 60)
    
    # Initialize platform clients
    clients = init_platform_clients()
    
    if not clients:
        logger.warning("No platform clients configured. Worker will run in standby mode.")
    
    config = WorkerConfig()
    
    # Track last sync times
    last_order_sync = datetime.min
    last_stock_sync = datetime.min
    last_health_check = datetime.min
    
    # Initial lookback for orders
    initial_lookback = datetime.now() - timedelta(hours=config.INITIAL_ORDER_LOOKBACK_HOURS)
    
    logger.info(f"Worker loop starting. Order sync every {config.ORDER_SYNC_INTERVAL}s")
    
    while True:
        try:
            now = datetime.now()
            
            # Health checks
            if (now - last_health_check).total_seconds() >= config.HEALTH_CHECK_INTERVAL:
                await run_health_checks(clients)
                last_health_check = now
            
            # Order sync
            if (now - last_order_sync).total_seconds() >= config.ORDER_SYNC_INTERVAL:
                # Use initial lookback on first run, then use last sync time
                since = initial_lookback if last_order_sync == datetime.min else last_order_sync
                
                for platform_name, client in clients.items():
                    if platform_name == "ZOHO":
                        continue  # Zoho doesn't provide orders this way
                    
                    async with async_session_factory() as session:
                        await sync_orders_from_platform(
                            platform_name,
                            client,
                            session,
                            since=since,
                        )
                
                last_order_sync = now
                logger.info(f"Order sync cycle complete. Next sync in {config.ORDER_SYNC_INTERVAL}s")
            
            # Stock sync
            if (now - last_stock_sync).total_seconds() >= config.STOCK_SYNC_INTERVAL:
                async with async_session_factory() as session:
                    await sync_stock_to_platforms(clients, session)
                last_stock_sync = now
            
            # Sleep before next iteration
            await asyncio.sleep(10)  # Check every 10 seconds
            
        except KeyboardInterrupt:
            logger.info("Worker received shutdown signal")
            break
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(60)  # Wait before retrying
    
    logger.info("Worker shutting down")


if __name__ == "__main__":
    try:
        asyncio.run(worker_main())
    except KeyboardInterrupt:
        print("\nWorker stopped by user")
    except Exception as e:
        print(f"Worker failed: {e}")
        sys.exit(1)

