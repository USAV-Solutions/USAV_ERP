"""
eBay Trading API Client.

Implements the BasePlatformClient interface for eBay stores.
"""
import asyncio
from datetime import datetime, date, timedelta
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

# eBay's CDN occasionally returns stale edge-node IPs that refuse TCP
# connections.  Transport-level retries force httpcore to re-resolve DNS
# on each attempt, working around transient CDN routing issues.
_TRANSPORT_RETRIES = 3          # retries at the httpcore transport layer
_TOKEN_REFRESH_ATTEMPTS = 3     # higher-level retries around OAuth token refresh
_TOKEN_RETRY_DELAY_SECS = 2     # pause between token-refresh retries


class EbayClient(BasePlatformClient):
    """
    eBay API client for order management and inventory sync.
    
    Supports multiple eBay stores (MEKONG, USAV, DRAGON) via different OAuth refresh tokens.
    
    Uses eBay OAuth 2.0 with refresh tokens to obtain access tokens.
    - Fulfillment API for orders
    - Inventory API for stock updates
    """
    
    def __init__(
        self,
        store_name: str = "USAV",
        app_id: str = None,
        cert_id: str = None,
        refresh_token: str = None,
        sandbox: bool = False,
        **kwargs
    ):
        self.store_name = store_name
        self.app_id = app_id
        self.cert_id = cert_id
        self.refresh_token = refresh_token
        self.sandbox = sandbox
        
        # OAuth access token (will be refreshed as needed)
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        
        # API base URLs
        self.base_url = (
            "https://api.sandbox.ebay.com" if sandbox
            else "https://api.ebay.com"
        )
        self.oauth_url = (
            "https://api.sandbox.ebay.com/identity/v1/oauth2/token" if sandbox
            else "https://api.ebay.com/identity/v1/oauth2/token"
        )
    
    @property
    def platform_name(self) -> str:
        return f"EBAY_{self.store_name.upper()}"
    
    @property
    def is_configured(self) -> bool:
        """Check if credentials are configured."""
        return all([self.app_id, self.cert_id, self.refresh_token])
    
    async def _refresh_access_token(self) -> bool:
        """
        Refresh the OAuth access token using the refresh token.

        Retries up to ``_TOKEN_REFRESH_ATTEMPTS`` times with a short delay
        to work around transient CDN / DNS issues (eBay edge nodes that
        refuse TCP connections).

        Returns:
            True if token was refreshed successfully
        """
        if not self.is_configured:
            logger.error(f"eBay {self.store_name} credentials not configured")
            return False

        import base64

        credentials = f"{self.app_id}:{self.cert_id}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {encoded_credentials}",
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "scope": (
                "https://api.ebay.com/oauth/api_scope "
                "https://api.ebay.com/oauth/api_scope/sell.fulfillment "
                "https://api.ebay.com/oauth/api_scope/sell.inventory"
            ),
        }

        last_err: Exception | None = None
        for attempt in range(1, _TOKEN_REFRESH_ATTEMPTS + 1):
            try:
                transport = httpx.AsyncHTTPTransport(retries=_TRANSPORT_RETRIES)
                async with httpx.AsyncClient(
                    transport=transport, timeout=30.0
                ) as client:
                    response = await client.post(
                        self.oauth_url, headers=headers, data=data
                    )
                    response.raise_for_status()

                    token_data = response.json()
                    self._access_token = token_data.get("access_token")
                    expires_in = token_data.get("expires_in", 7200)

                    # Refresh 5 minutes before actual expiry
                    self._token_expires_at = datetime.now() + timedelta(
                        seconds=expires_in - 300
                    )

                    logger.info(
                        f"eBay {self.store_name} access token refreshed "
                        f"successfully (attempt {attempt})"
                    )
                    return True

            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_err = e
                logger.warning(
                    f"eBay {self.store_name} token refresh attempt {attempt}/"
                    f"{_TOKEN_REFRESH_ATTEMPTS} failed (connect): {e}"
                )
                if attempt < _TOKEN_REFRESH_ATTEMPTS:
                    await asyncio.sleep(_TOKEN_RETRY_DELAY_SECS * attempt)
            except Exception as e:
                logger.error(
                    f"Error refreshing eBay {self.store_name} token: {e}",
                    exc_info=True,
                )
                return False

        logger.error(
            f"eBay {self.store_name} token refresh failed after "
            f"{_TOKEN_REFRESH_ATTEMPTS} attempts: {last_err}",
            exc_info=True,
        )
        return False
    
    async def _get_access_token(self) -> Optional[str]:
        """
        Get a valid access token, refreshing if necessary.
        
        Returns:
            Valid access token or None if unable to obtain
        """
        # Check if token needs refresh
        if not self._access_token or not self._token_expires_at or datetime.now() >= self._token_expires_at:
            if not await self._refresh_access_token():
                return None
        
        return self._access_token
    
    async def authenticate(self) -> bool:
        """
        Authenticate with eBay API by obtaining an access token.
        
        Returns:
            True if authentication successful
        """
        if not self.is_configured:
            logger.warning(f"eBay {self.store_name} credentials not configured")
            return False
        
        token = await self._get_access_token()
        return token is not None
    
    async def fetch_daily_orders(self, order_date: date) -> List[ExternalOrder]:
        """
        Fetch all orders from a specific date.
        
        Args:
            order_date: The date to fetch orders from
            
        Returns:
            List of ExternalOrder objects for the specified date
        """
        if not self.is_configured:
            logger.error(f"eBay {self.store_name} not configured, skipping fetch")
            return []
        
        # Set time range for the entire day
        start_time = datetime.combine(order_date, datetime.min.time())
        end_time = start_time + timedelta(days=1)
        
        logger.info(
            f"Fetching eBay {self.store_name} orders from {start_time} to {end_time}"
        )
        
        return await self.fetch_orders(since=start_time, until=end_time)
    
    async def fetch_orders(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> List[ExternalOrder]:
        """
        Fetch orders from eBay using Fulfillment API.
        
        Endpoint: GET /sell/fulfillment/v1/order
        
        Args:
            since: Start datetime for order filter
            until: End datetime for order filter
            status: Order status filter (NOT_STARTED, IN_PROGRESS, FULFILLED, etc.)
        
        Returns:
            List of ExternalOrder objects
        """
        logger.info(f"eBay {self.store_name} fetch_orders called: since={since}, until={until}, status={status}")
        
        if not self.is_configured:
            message = f"eBay {self.store_name} credentials not configured"
            logger.error(message)
            raise RuntimeError(message)
        
        # Get valid access token
        logger.debug(f"eBay {self.store_name}: Obtaining access token")
        access_token = await self._get_access_token()
        if not access_token:
            message = f"eBay {self.store_name} unable to obtain access token"
            logger.error(message)
            raise RuntimeError(message)
        
        try:
            # Build filter string for eBay API
            filters = []
            logger.debug(f"eBay {self.store_name}: Building filter params")
            if since:
                since_str = since.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                if until:
                    until_str = until.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    filters.append(f"creationdate:[{since_str}..{until_str}]")
                    logger.debug(f"eBay {self.store_name}: Date range filter: {since_str} to {until_str}")
                else:
                    filters.append(f"creationdate:[{since_str}..]")
                    logger.debug(f"eBay {self.store_name}: Open-ended date filter from: {since_str}")
            
            if status:
                filters.append(f"orderfulfillmentstatus:{{{status}}}")
                logger.debug(f"eBay {self.store_name}: Status filter: {status}")
            
            filter_param = ",".join(filters) if filters else None
            
            # Make API request – use transport-level retries so that
            # httpcore re-resolves DNS on each retry, working around
            # transient CDN edge-node failures.
            transport = httpx.AsyncHTTPTransport(retries=_TRANSPORT_RETRIES)
            async with httpx.AsyncClient(
                transport=transport, timeout=30.0
            ) as client:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                
                params = {}
                if filter_param:
                    params["filter"] = filter_param
                params["limit"] = 200  # eBay max is 200 per page
                
                logger.info(f"eBay {self.store_name}: Starting order fetch with filter={filter_param}")
                orders = []
                offset = 0
                
                while True:
                    params["offset"] = offset
                    
                    url = f"{self.base_url}/sell/fulfillment/v1/order"
                    logger.debug(f"eBay {self.store_name}: API request offset={offset}, url={url}")
                    
                    response = await client.get(url, headers=headers, params=params)
                    response.raise_for_status()
                    
                    data = response.json()
                    page_orders = data.get("orders", [])
                    logger.debug(f"eBay {self.store_name}: Retrieved {len(page_orders)} orders in this batch")
                    
                    if not page_orders:
                        logger.debug(f"eBay {self.store_name}: No more orders, stopping pagination")
                        break
                    
                    # Convert each order
                    for order_data in page_orders:
                        try:
                            order = self._convert_order(order_data)
                            orders.append(order)
                        except Exception as e:
                            logger.error(
                                f"eBay {self.store_name}: Error converting order {order_data.get('orderId')}: {e}",
                                exc_info=True
                            )
                    
                    # Check if there are more pages
                    total = data.get("total", 0)
                    offset += len(page_orders)
                    logger.debug(f"eBay {self.store_name}: Progress {offset}/{total}")
                    
                    if offset >= total:
                        logger.debug(f"eBay {self.store_name}: Reached end of results")
                        break
                
                logger.info(f"eBay {self.store_name}: Successfully fetched {len(orders)} orders")
                return orders
                
        except httpx.HTTPStatusError as e:
            message = (
                f"eBay {self.store_name}: HTTP error {e.response.status_code} - {e.response.text}"
            )
            logger.error(message, exc_info=True)
            raise RuntimeError(message) from e
        except Exception as e:
            message = f"eBay {self.store_name}: Error fetching orders: {e}"
            logger.error(message, exc_info=True)
            raise RuntimeError(message) from e
    
    async def get_order(self, order_id: str) -> Optional[ExternalOrder]:
        """
        Get a specific eBay order.
        
        Endpoint: GET /sell/fulfillment/v1/order/{orderId}
        """
        logger.info(f"Fetching eBay {self.store_name} order: {order_id}")
        
        # TODO: Implement actual API call
        return None
    
    async def update_stock(self, updates: List[StockUpdate]) -> List[StockUpdateResult]:
        """
        Update inventory levels on eBay.
        
        Uses the Inventory API: PUT /sell/inventory/v1/inventory_item/{sku}
        """
        logger.info(f"Updating eBay {self.store_name} stock for {len(updates)} items")
        
        results = []
        for update in updates:
            # TODO: Implement actual API call
            results.append(StockUpdateResult(
                sku=update.sku,
                success=False,
                message="Not implemented",
            ))
        
        return results
    
    async def update_tracking(
        self,
        order_id: str,
        tracking_number: str,
        carrier: str
    ) -> bool:
        """
        Update shipment tracking for an eBay order.
        
        Endpoint: POST /sell/fulfillment/v1/order/{orderId}/shipping_fulfillment
        """
        logger.info(f"Updating tracking for eBay order {order_id}: {carrier} {tracking_number}")
        
        # TODO: Implement actual API call
        return False
    
    def _convert_order(self, ebay_order: dict) -> ExternalOrder:
        """Convert eBay order JSON to ExternalOrder."""
        # Extract shipping address
        instructions = ebay_order.get("fulfillmentStartInstructions") or []
        shipping = (
            instructions[0].get("shippingStep", {}).get("shipTo", {})
            if instructions
            else {}
        )
        
        # Convert line items
        items = []
        for item in ebay_order.get("lineItems", []):
            items.append(ExternalOrderItem(
                platform_item_id=item.get("lineItemId"),
                platform_sku=item.get("sku"),
                asin=None,  # eBay doesn't have ASIN
                title=item.get("title", "Unknown Item"),
                quantity=int(item.get("quantity", 1)),
                unit_price=float(item.get("lineItemCost", {}).get("value", 0)),
                total_price=float(item.get("total", {}).get("value", 0)),
                raw_data=item,
            ))
        
        # Calculate totals
        pricing = ebay_order.get("pricingSummary", {})
        
        return ExternalOrder(
            platform_order_id=ebay_order.get("orderId"),
            platform_order_number=ebay_order.get("legacyOrderId"),
            customer_name=shipping.get("fullName"),
            customer_email=ebay_order.get("buyer", {}).get("email"),
            ship_address_line1=shipping.get("contactAddress", {}).get("addressLine1"),
            ship_address_line2=shipping.get("contactAddress", {}).get("addressLine2"),
            ship_city=shipping.get("contactAddress", {}).get("city"),
            ship_state=shipping.get("contactAddress", {}).get("stateOrProvince"),
            ship_postal_code=shipping.get("contactAddress", {}).get("postalCode"),
            ship_country=shipping.get("contactAddress", {}).get("countryCode", "US"),
            subtotal=float(pricing.get("priceSubtotal", {}).get("value", 0)),
            tax=float(pricing.get("tax", {}).get("value", 0)),
            shipping=float(pricing.get("deliveryCost", {}).get("value", 0)),
            total=float(pricing.get("total", {}).get("value", 0)),
            currency=pricing.get("total", {}).get("currency", "USD"),
            ordered_at=datetime.fromisoformat(
                ebay_order.get("creationDate", "").replace("Z", "+00:00")
            ) if ebay_order.get("creationDate") else None,
            items=items,
            raw_data=ebay_order,
        )

