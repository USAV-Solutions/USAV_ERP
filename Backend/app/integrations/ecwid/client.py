"""
Ecwid API Client.

Implements integration with Ecwid e-commerce platform for orders and inventory.
Ecwid API Documentation: https://api-docs.ecwid.com/reference/overview
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import logging

import httpx

from app.integrations.base import (
    BasePlatformClient,
    ExternalOrder,
    ExternalOrderItem,
    StockUpdate,
    StockUpdateResult,
)

logger = logging.getLogger(__name__)


class EcwidClient(BasePlatformClient):
    """
    Ecwid API client for order retrieval and inventory management.
    
    Requires:
    - store_id: Your Ecwid store ID
    - access_token: OAuth access token with read/write permissions
    
    API Docs: https://api-docs.ecwid.com
    """
    
    def __init__(
        self,
        store_id: str,
        access_token: str,
        api_base_url: str = "https://app.ecwid.com/api/v3",
        **kwargs
    ):
        self.store_id = store_id
        self.access_token = access_token
        self.api_base_url = api_base_url
        self.base_url = f"{api_base_url}/{store_id}"
        
        if not store_id or not access_token:
            logger.warning("Ecwid credentials not configured")
    
    @property
    def platform_name(self) -> str:
        """Return the platform identifier."""
        return "ECWID"
    
    @property
    def is_configured(self) -> bool:
        """Check if client has required credentials."""
        return bool(self.store_id and self.access_token)
    
    def _get_headers(self) -> dict:
        """Get standard headers for Ecwid API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    async def get_store_profile(self) -> Optional[dict]:
        """
        Get store profile information from Ecwid.
        
        Returns:
            Store profile data if successful, None otherwise
        """
        if not self.is_configured:
            logger.error("Ecwid client not configured")
            return None
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/profile",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch Ecwid store profile: {e}")
            return None
    
    async def test_connection(self) -> dict:
        """
        Test the Ecwid API connection and return connection status.
        
        Returns:
            Dictionary with connection test results
        """
        result = {
            "success": False,
            "authenticated": False,
            "store_info": None,
            "error": None
        }
        
        if not self.is_configured:
            result["error"] = "Ecwid client not configured - missing store_id or access_token"
            return result
        
        try:
            # Test authentication by fetching store profile
            profile = await self.get_store_profile()
            if profile:
                result["success"] = True
                result["authenticated"] = True
                result["store_info"] = {
                    "store_name": profile.get("generalInfo", {}).get("storeUrl", "Unknown"),
                    "store_id": self.store_id,
                    "account_name": profile.get("account", {}).get("accountName", "Unknown")
                }
                logger.info(f"Ecwid connection test successful for store {self.store_id}")
            else:
                result["error"] = "Failed to fetch store profile - authentication failed"
        except Exception as e:
            result["error"] = f"Connection test failed: {str(e)}"
            logger.error(f"Ecwid connection test failed: {e}")
        
        return result
    
    async def authenticate(self) -> bool:
        """
        Authenticate with the Ecwid API.
        
        Returns:
            True if authentication successful, False otherwise.
        """
        if not self.is_configured:
            logger.error("Ecwid client not configured")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/profile",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                logger.info("Ecwid authentication successful")
                return True
        except httpx.HTTPError as e:
            logger.error(f"Ecwid authentication failed: {e}")
            return False
    
    async def get_order(self, order_id: str) -> Optional[ExternalOrder]:
        """
        Get a specific order by ID.
        
        Args:
            order_id: Ecwid order ID or order number
            
        Returns:
            ExternalOrder if found, None otherwise
        """
        if not self.is_configured:
            logger.error("Ecwid client not configured")
            return None
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/orders/{order_id}",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                order_data = response.json()
                return self._parse_ecwid_order(order_data)
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch Ecwid order {order_id}: {e}")
            return None
    
    async def fetch_daily_orders(self, date: Optional[datetime] = None) -> List[ExternalOrder]:
        """
        Fetch all orders from a specific date.
        
        Args:
            date: Date to fetch orders from (defaults to today)
            
        Returns:
            List of ExternalOrder objects
        """
        if not self.is_configured:
            logger.error("Ecwid client not configured, cannot fetch orders")
            return []
        
        if date is None:
            date = datetime.now().date()
        elif isinstance(date, datetime):
            date = date.date()
        
        # Ecwid uses Unix timestamps for filtering
        start_timestamp = int(datetime.combine(date, datetime.min.time()).timestamp())
        end_timestamp = start_timestamp + 86400  # +24 hours
        
        logger.debug(
            f"[DEBUG.EXTERNAL_API] Fetching Ecwid orders from {date} "
            f"(timestamp {start_timestamp} to {end_timestamp})"
        )
        
        orders = []
        offset = 0
        limit = 100
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                try:
                    params = {
                        "createdFrom": start_timestamp,
                        "createdTo": end_timestamp,
                        "limit": limit,
                        "offset": offset,
                    }
                    
                    response = await client.get(
                        f"{self.base_url}/orders",
                        headers=self._get_headers(),
                        params=params
                    )
                    response.raise_for_status()
                    
                    data = response.json()
                    batch = data.get("items", [])
                    
                    if not batch:
                        break
                    
                    for order_data in batch:
                        try:
                            order = self._parse_ecwid_order(order_data)
                            orders.append(order)
                        except Exception as e:
                            logger.error(
                                f"Failed to parse Ecwid order {order_data.get('orderNumber')}: {e}"
                            )
                    
                    # Check if there are more orders
                    total = data.get("total", 0)
                    offset += len(batch)
                    
                    if offset >= total:
                        break
                        
                except httpx.HTTPError as e:
                    logger.error(f"Ecwid API request failed: {e}")
                    break
        
        logger.info(f"Fetched {len(orders)} orders from Ecwid")
        return orders
    
    def _parse_ecwid_order(self, order_data: dict) -> ExternalOrder:
        """
        Parse Ecwid order JSON to ExternalOrder format.
        
        Ecwid order structure: https://api-docs.ecwid.com/reference/orders
        """
        # Parse shipping address
        shipping = order_data.get("shippingPerson", {})
        
        # Parse order items
        items = []
        for item_data in order_data.get("items", []):
            # Handle both productId and id fields for item identification
            item_id = item_data.get("productId") or item_data.get("id")
            item = ExternalOrderItem(
                platform_item_id=str(item_id) if item_id else None,
                platform_sku=item_data.get("sku"),
                asin=None,  # Ecwid doesn't have ASIN
                title=item_data.get("name", "Unknown Item"),
                quantity=item_data.get("quantity", 1),
                unit_price=float(item_data.get("price", 0)),
                total_price=float(item_data.get("price", 0)) * item_data.get("quantity", 1),
                raw_data=item_data,
            )
            items.append(item)
        
        # Parse timestamps - handle both createTimestamp and createDate
        created_timestamp = order_data.get("createTimestamp")
        create_date = order_data.get("createDate")
        
        ordered_at = None
        if created_timestamp:
            ordered_at = datetime.fromtimestamp(created_timestamp)
        elif create_date:
            try:
                ordered_at = datetime.fromisoformat(create_date.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass
        
        # Handle order identification - prefer id over orderNumber for consistency
        order_id = str(order_data.get("id", order_data.get("orderNumber", "")))
        order_number = str(order_data.get("orderNumber", order_data.get("vendorOrderNumber", order_id)))
        
        shipping_option = order_data.get("shippingOption") or {}
        shipping_amount = 0.0
        if shipping_option.get("shippingRate") is not None:
            shipping_amount = float(shipping_option.get("shippingRate") or 0)
        elif shipping_option.get("discountedShippingRate") is not None:
            shipping_amount = float(shipping_option.get("discountedShippingRate") or 0)
        elif order_data.get("shipping") is not None:
            shipping_amount = float(order_data.get("shipping") or 0)
        else:
            # Fallback for payloads that only expose per-line shipping values.
            shipping_amount = float(
                sum(float(item.get("shipping", 0) or 0) for item in order_data.get("items", []))
            )

        return ExternalOrder(
            platform_order_id=order_id,
            platform_order_number=order_number,
            customer_name=shipping.get("name"),
            customer_email=order_data.get("email"),
            customer_phone=shipping.get("phone") or order_data.get("customerPhone"),
            customer_company=shipping.get("companyName") or shipping.get("company"),
            customer_source="ECWID_API",
            ship_address_line1=shipping.get("street"),
            ship_address_line2=shipping.get("street2") or shipping.get("addressLine2"),
            ship_address_line3=shipping.get("street3") or shipping.get("addressLine3"),
            ship_city=shipping.get("city"),
            ship_state=shipping.get("stateOrProvinceCode"),
            ship_postal_code=shipping.get("postalCode"),
            ship_country=shipping.get("countryCode", "US"),
            subtotal=float(order_data.get("subtotal", 0)),
            tax=float(order_data.get("tax", 0)),
            shipping=shipping_amount,
            total=float(order_data.get("total", 0)),
            currency=order_data.get("currency", "USD"),
            ordered_at=ordered_at,
            items=items,
            raw_data=order_data,
            tracking_number=order_data.get("trackingNumber"),
        )
    
    async def fetch_orders_since_last_sync(
        self,
        last_sync_timestamp: Optional[datetime] = None,
        fulfillment_status: Optional[str] = None
    ) -> List[ExternalOrder]:
        """
        Fetch orders from Ecwid since the last successful sync.
        
        Args:
            last_sync_timestamp: Last successful sync datetime (defaults to 30 days ago)
            fulfillment_status: Optional fulfillment status filter (AWAITING_PROCESSING, SHIPPED, etc.)
            
        Returns:
            List of ExternalOrder objects
        """
        if not self.is_configured:
            logger.error("Ecwid client not configured")
            return []
        
        # Default to fetching last 30 days if no sync timestamp provided
        if last_sync_timestamp is None:
            last_sync_timestamp = datetime.now(timezone.utc) - timedelta(days=30)
        
        # Always sync up to current time
        current_time = datetime.now(timezone.utc)
        
        logger.debug(
            f"[DEBUG.EXTERNAL_API] Fetching Ecwid orders since last sync: {last_sync_timestamp} to {current_time}"
        )
        
    async def fetch_new_orders(
        self,
        fulfillment_status: str = "AWAITING_PROCESSING",
        payment_status: str = "PAID",
        hours_back: int = 24
    ) -> List[ExternalOrder]:
        """
        Fetch new/recent orders from Ecwid with specific status filters.
        Optimized for regular sync operations.
        
        Args:
            fulfillment_status: Fulfillment status to filter by (AWAITING_PROCESSING, SHIPPED, DELIVERED, etc.)
            payment_status: Payment status to filter by (PAID, AWAITING_PAYMENT, etc.)  
            hours_back: How many hours back to look for orders (default 24)
            
        Returns:
            List of ExternalOrder objects
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        
        logger.debug(
            f"[DEBUG.EXTERNAL_API] Fetching new Ecwid orders: fulfillment={fulfillment_status}, "
            f"payment={payment_status}, since={since}"
        )
        
        return await self.fetch_orders(
            since=since,
            status=payment_status,
            fulfillment_status=fulfillment_status
        )
    
    async def fetch_orders(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        status: Optional[str] = None,
        fulfillment_status: Optional[str] = None,
    ) -> List[ExternalOrder]:
        """
        Fetch orders from Ecwid (matching base class signature).
        
        Args:
            since: Start datetime for order filter
            until: End datetime for order filter (defaults to now)
            status: Optional Ecwid payment status filter (PAID, AWAITING_PAYMENT, etc.)
            fulfillment_status: Optional fulfillment status filter (AWAITING_PROCESSING, SHIPPED, etc.)
            
        Returns:
            List of ExternalOrder objects
        """
        logger.debug(f"[DEBUG.EXTERNAL_API] Ecwid fetch_orders called: since={since}, until={until}, status={status}, fulfillment_status={fulfillment_status}")
        
        if not self.is_configured:
            logger.error("Ecwid client not configured")
            return []
        
        # Default to fetching last 30 days if no since provided
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(days=30)
        # Default to now if no until provided
        if until is None:
            until = datetime.now(timezone.utc)
        
        start_timestamp = int(since.timestamp())
        end_timestamp = int(until.timestamp())
        
        logger.debug(
            f"[DEBUG.EXTERNAL_API] Fetching Ecwid orders from {since.date()} to {until.date()} (timestamps: {start_timestamp} - {end_timestamp})"
        )
        
        orders = []
        offset = 0
        limit = 100  # Ecwid max limit is 100
        
        async with httpx.AsyncClient(timeout=60.0) as client:  # Increased timeout for large requests
            while True:
                try:
                    params = {
                        "createdFrom": start_timestamp,
                        "createdTo": end_timestamp,
                        "limit": limit,
                        "offset": offset,
                    }
                    
                    # Add optional filters
                    if status:
                        params["paymentStatus"] = status
                    if fulfillment_status:
                        params["fulfillmentStatus"] = fulfillment_status
                    
                    logger.debug(f"Ecwid API request: offset={offset}, params={params}")
                    
                    response = await client.get(
                        f"{self.base_url}/orders",
                        headers=self._get_headers(),
                        params=params
                    )
                    response.raise_for_status()
                    
                    data = response.json()
                    batch = data.get("items", [])
                    total = data.get("total", 0)
                    count = data.get("count", 0)
                    
                    logger.debug(f"Ecwid API response: {len(batch)} orders in batch, {total} total, count={count}")
                    
                    if not batch:
                        break
                    
                    for order_data in batch:
                        try:
                            order = self._parse_ecwid_order(order_data)
                            orders.append(order)
                        except Exception as e:
                            order_id = order_data.get('id', 'unknown')
                            logger.error(f"Failed to parse Ecwid order {order_id}: {e}", exc_info=True)
                    
                    offset += len(batch)
                    logger.debug(f"Ecwid batch processed: {len(batch)} orders, offset now {offset}/{total}")
                    
                    # Check if we've retrieved all orders
                    if offset >= total or len(batch) < limit:
                        break
                        
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:  # Rate limit
                        logger.warning("Ecwid API rate limit hit, waiting...")
                        await asyncio.sleep(60)  # Wait 1 minute before retrying
                        continue
                    logger.error(f"Ecwid API HTTP error: {e.response.status_code} - {e.response.text}")
                    break
                except httpx.TimeoutException:
                    logger.error("Ecwid API request timed out")
                    break
                except httpx.RequestError as e:
                    logger.error(f"Ecwid API request failed: {e}")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error during Ecwid API request: {e}", exc_info=True)
                    break
        
        logger.info(f"Successfully fetched {len(orders)} orders from Ecwid")
        return orders
    
    async def update_stock(
        self, 
        stock_updates: List[StockUpdate]
    ) -> List[StockUpdateResult]:
        """
        Update inventory levels in Ecwid.
        
        Args:
            stock_updates: List of stock updates to apply
            
        Returns:
            List of update results
        """
        if not self.is_configured:
            logger.error("Ecwid client not configured")
            return [
                StockUpdateResult(sku=update.sku, success=False, message="Not configured")
                for update in stock_updates
            ]
        
        results = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for update in stock_updates:
                try:
                    # First, find the product by SKU
                    search_response = await client.get(
                        f"{self.base_url}/products",
                        headers=self._get_headers(),
                        params={
                            "keyword": update.sku,
                            "limit": 1,
                        },
                    )
                    search_response.raise_for_status()
                    products = search_response.json().get("items", [])
                    
                    if not products:
                        results.append(
                            StockUpdateResult(
                                sku=update.sku,
                                success=False,
                                message="Product not found in Ecwid",
                            )
                        )
                        continue
                    
                    product_id = products[0].get("id")
                    
                    # Update the product quantity
                    update_response = await client.put(
                        f"{self.base_url}/products/{product_id}",
                        headers=self._get_headers(),
                        json={"unlimited": False, "quantity": update.quantity},
                    )
                    update_response.raise_for_status()
                    
                    results.append(
                        StockUpdateResult(
                            sku=update.sku,
                            success=True,
                            message=f"Updated to {update.quantity} units",
                            external_ref_id=str(product_id),
                        )
                    )
                    logger.info(f"Updated Ecwid stock for {update.sku}: {update.quantity}")
                    
                except httpx.HTTPError as e:
                    logger.error(f"Failed to update stock for {update.sku}: {e}")
                    results.append(
                        StockUpdateResult(
                            sku=update.sku,
                            success=False,
                            message=str(e),
                        )
                    )
        
        return results
    
    async def update_tracking(
        self,
        order_id: str,
        tracking_number: str,
        carrier: str
    ) -> bool:
        """
        Update shipment tracking information on Ecwid.
        
        Args:
            order_id: Ecwid order ID
            tracking_number: Shipment tracking number
            carrier: Shipping carrier name
            
        Returns:
            True if update successful, False otherwise
        """
        if not self.is_configured:
            logger.error("Ecwid client not configured")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(
                    f"{self.base_url}/orders/{order_id}",
                    headers=self._get_headers(),
                    json={
                        "trackingNumber": tracking_number,
                        "shippingCarrierName": carrier,
                    }
                )
                response.raise_for_status()
                logger.info(f"Updated tracking for order {order_id}: {tracking_number}")
                return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to update tracking for order {order_id}: {e}")
            return False
