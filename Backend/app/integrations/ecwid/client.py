"""
Ecwid API Client.

Implements integration with Ecwid e-commerce platform for orders and inventory.
Ecwid API Documentation: https://api-docs.ecwid.com/reference/overview
"""
from datetime import datetime, timedelta
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
                    params={"token": self.access_token}
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
                    params={"token": self.access_token}
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
        
        logger.info(
            f"Fetching Ecwid orders from {date} "
            f"(timestamp {start_timestamp} to {end_timestamp})"
        )
        
        orders = []
        offset = 0
        limit = 100
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                try:
                    response = await client.get(
                        f"{self.base_url}/orders",
                        params={
                            "token": self.access_token,
                            "createdFrom": start_timestamp,
                            "createdTo": end_timestamp,
                            "limit": limit,
                            "offset": offset,
                        },
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
            item = ExternalOrderItem(
                platform_item_id=str(item_data.get("id")),
                platform_sku=item_data.get("sku"),
                asin=None,  # Ecwid doesn't have ASIN
                title=item_data.get("name", "Unknown Item"),
                quantity=item_data.get("quantity", 1),
                unit_price=float(item_data.get("price", 0)),
                total_price=float(item_data.get("price", 0)) * item_data.get("quantity", 1),
                raw_data=item_data,
            )
            items.append(item)
        
        # Parse timestamps
        created_timestamp = order_data.get("createTimestamp")
        ordered_at = (
            datetime.fromtimestamp(created_timestamp) if created_timestamp else None
        )
        
        return ExternalOrder(
            platform_order_id=str(order_data.get("orderNumber")),  # Use orderNumber as primary ID
            platform_order_number=str(order_data.get("vendorOrderNumber") or order_data.get("orderNumber")),
            customer_name=shipping.get("name"),
            customer_email=order_data.get("email"),
            ship_address_line1=shipping.get("street"),
            ship_address_line2=None,  # Ecwid combines address into 'street'
            ship_city=shipping.get("city"),
            ship_state=shipping.get("stateOrProvinceCode"),
            ship_postal_code=shipping.get("postalCode"),
            ship_country=shipping.get("countryCode", "US"),
            subtotal=float(order_data.get("subtotal", 0)),
            tax=float(order_data.get("tax", 0)),
            shipping=float(order_data.get("shipping", 0)),
            total=float(order_data.get("total", 0)),
            currency=order_data.get("currency", "USD"),
            ordered_at=ordered_at,
            items=items,
            raw_data=order_data,
        )
    
    async def fetch_orders(
        self,
        start_date: datetime,
        end_date: datetime,
        status_filter: Optional[str] = None,
    ) -> List[ExternalOrder]:
        """
        Fetch orders within a date range.
        
        Args:
            start_date: Start of date range
            end_date: End of date range
            status_filter: Optional Ecwid order status filter
            
        Returns:
            List of ExternalOrder objects
        """
        if not self.is_configured:
            logger.error("Ecwid client not configured")
            return []
        
        start_timestamp = int(start_date.timestamp())
        end_timestamp = int(end_date.timestamp())
        
        logger.info(
            f"Fetching Ecwid orders from {start_date.date()} to {end_date.date()}"
        )
        
        orders = []
        offset = 0
        limit = 100
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                try:
                    params = {
                        "token": self.access_token,
                        "createdFrom": start_timestamp,
                        "createdTo": end_timestamp,
                        "limit": limit,
                        "offset": offset,
                    }
                    
                    if status_filter:
                        params["paymentStatus"] = status_filter
                    
                    response = await client.get(
                        f"{self.base_url}/orders",
                        params=params,
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
                            logger.error(f"Failed to parse Ecwid order: {e}")
                    
                    total = data.get("total", 0)
                    offset += len(batch)
                    
                    if offset >= total:
                        break
                        
                except httpx.HTTPError as e:
                    logger.error(f"Ecwid API request failed: {e}")
                    break
        
        logger.info(f"Fetched {len(orders)} orders from Ecwid")
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
                        params={
                            "token": self.access_token,
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
                        params={"token": self.access_token},
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
                    params={"token": self.access_token},
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
