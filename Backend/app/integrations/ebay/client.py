"""
eBay Trading API Client.

Implements the BasePlatformClient interface for eBay stores.
"""
import asyncio
from datetime import datetime, date, timedelta, timezone
from typing import Any, List, Optional
import logging
import socket
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
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
_TRADING_NS = {"eb": "urn:ebay:apis:eBLBaseComponents"}
EBAY_ISO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"


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

        oauth_host = urlparse(self.oauth_url).hostname or ""
        oauth_port = 443

        last_err: Exception | None = None
        for attempt in range(1, _TOKEN_REFRESH_ATTEMPTS + 1):
            try:
                resolved_ips: list[str] = []
                if oauth_host:
                    try:
                        loop = asyncio.get_running_loop()
                        addrinfo = await loop.getaddrinfo(
                            oauth_host,
                            oauth_port,
                            type=socket.SOCK_STREAM,
                        )
                        resolved_ips = sorted(
                            {
                                str(info[4][0])
                                for info in addrinfo
                                if info and len(info) >= 5 and info[4]
                            }
                        )
                    except Exception as dns_exc:
                        logger.debug(
                            "eBay %s token refresh DNS lookup failed on attempt %s/%s | host=%s error=%s",
                            self.store_name,
                            attempt,
                            _TOKEN_REFRESH_ATTEMPTS,
                            oauth_host,
                            dns_exc,
                        )

                logger.debug(
                    "eBay %s token refresh connection attempt %s/%s | url=%s host=%s resolved_ips=%s transport_retries=%s",
                    self.store_name,
                    attempt,
                    _TOKEN_REFRESH_ATTEMPTS,
                    self.oauth_url,
                    oauth_host or "unknown",
                    resolved_ips or ["unresolved"],
                    _TRANSPORT_RETRIES,
                )

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

                    logger.debug(
                        f"[DEBUG.EXTERNAL_API] eBay {self.store_name} access token refreshed "
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

    async def fetch_buying_orders_xml(
        self,
        since: datetime,
        until: datetime,
        *,
        max_pages: int = 50,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch buyer orders via Trading API GetOrders (XML) and normalize for purchasing import."""
        if not self.is_configured:
            raise RuntimeError(f"eBay {self.store_name} credentials not configured")

        # Normalize caller-supplied boundaries for safe comparison with API timestamps.
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        else:
            since = since.astimezone(timezone.utc)

        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        else:
            until = until.astimezone(timezone.utc)

        access_token = await self._get_access_token()
        if not access_token:
            raise RuntimeError(f"eBay {self.store_name} unable to obtain access token")

        orders_by_id: dict[str, dict[str, Any]] = {}
        order_item_keys: dict[str, set[tuple[str, str, int, float]]] = {}
        trading_url = f"{self.base_url}/ws/api.dll"
        last_page_signature: tuple[str, ...] | None = None
        total_transactions_seen = 0
        total_items_added = 0
        total_skipped_missing_order_id = 0
        total_skipped_missing_created_at = 0
        total_skipped_out_of_range = 0
        total_skipped_deduped = 0

        for page in range(1, max_pages + 1):
            page_transactions_seen = 0
            page_items_added = 0
            page_skipped_missing_order_id = 0
            page_skipped_missing_created_at = 0
            page_skipped_out_of_range = 0
            page_skipped_deduped = 0

            since_str = since.strftime(EBAY_ISO_DATE_FORMAT)
            until_str = until.strftime(EBAY_ISO_DATE_FORMAT)
            request_xml = f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
<GetOrdersRequest xmlns=\"urn:ebay:apis:eBLBaseComponents\">
    <CreateTimeFrom>{since_str}</CreateTimeFrom>
    <CreateTimeTo>{until_str}</CreateTimeTo>
    <OrderRole>Buyer</OrderRole>
    <OrderStatus>All</OrderStatus>
    <SortingOrder>Descending</SortingOrder>
    <Pagination>
        <EntriesPerPage>{per_page}</EntriesPerPage>
        <PageNumber>{page}</PageNumber>
    </Pagination>
</GetOrdersRequest>"""

            headers = {
                "Content-Type": "text/xml",
                "X-EBAY-API-CALL-NAME": "GetOrders",
                "X-EBAY-API-COMPATIBILITY-LEVEL": "1231",
                "X-EBAY-API-SITEID": "0",
                "X-EBAY-API-IAF-TOKEN": access_token,
            }

            transport = httpx.AsyncHTTPTransport(retries=_TRANSPORT_RETRIES)
            async with httpx.AsyncClient(transport=transport, timeout=30.0) as client:
                response = await client.post(trading_url, headers=headers, content=request_xml)
                response.raise_for_status()

            root = ET.fromstring(response.text)
            ack = self._xml_text(root, "./eb:Ack")
            if ack and ack.lower() in {"failure", "partialfailure"}:
                short_message = self._xml_text(
                    root,
                    "./eb:Errors/eb:ShortMessage",
                ) or "Unknown eBay Trading API error"
                raise RuntimeError(f"eBay {self.store_name} GetOrders failed: {short_message}")

            order_nodes = root.findall(".//eb:OrderArray/eb:Order", _TRADING_NS)
            if not order_nodes:
                logger.debug(
                    "[DEBUG.EXTERNAL_API] eBay %s GetOrders page=%s has no Order nodes; stopping pagination",
                    self.store_name,
                    page,
                )
                break
            page_transactions_seen = len(order_nodes)
            total_transactions_seen += page_transactions_seen

            page_signature = tuple(
                sorted(
                    filter(
                        None,
                        (
                            self._xml_text(order_node, "./eb:OrderID")
                            or self._xml_text(order_node, "./eb:ExtendedOrderID")
                            for order_node in order_nodes
                        ),
                    )
                )
            )
            if page_signature and page_signature == last_page_signature:
                logger.debug(
                    "[DEBUG.EXTERNAL_API] eBay %s GetOrders repeated page signature at page %s; stopping pagination",
                    self.store_name,
                    page,
                )
                break
            last_page_signature = page_signature

            page_added = 0
            for order_node in order_nodes:
                order_id = (
                    self._xml_text(order_node, "./eb:OrderID")
                    or self._xml_text(order_node, "./eb:ExtendedOrderID")
                )
                if not order_id:
                    page_skipped_missing_order_id += 1
                    total_skipped_missing_order_id += 1
                    continue

                created_at_raw = (
                    self._xml_text(order_node, "./eb:CreatedTime")
                    or self._xml_text(order_node, "./eb:PaidTime")
                    or self._xml_text(order_node, "./eb:CheckoutStatus/eb:LastModifiedTime")
                )
                created_at = self._parse_ebay_datetime(created_at_raw)
                if created_at is None:
                    page_skipped_missing_created_at += 1
                    total_skipped_missing_created_at += 1
                    continue
                if created_at < since or created_at > until:
                    page_skipped_out_of_range += 1
                    total_skipped_out_of_range += 1
                    continue

                transaction_nodes = order_node.findall("./eb:TransactionArray/eb:Transaction", _TRADING_NS)
                if not transaction_nodes:
                    page_skipped_missing_created_at += 1
                    total_skipped_missing_created_at += 1
                    continue

                order_data = orders_by_id.setdefault(
                    order_id,
                    {
                        "po_number": order_id,
                        "order_date": created_at.date(),
                        "currency": self._xml_attr(order_node, "./eb:Total", "currencyID") or "USD",
                        "tracking_number": self._xml_text(order_node, "./eb:ShippingDetails/eb:ShipmentTrackingDetails/eb:ShipmentTrackingNumber"),
                        "tax_amount": self._to_float_safe(
                            self._xml_text(order_node, "./eb:TransactionArray/eb:Transaction/eb:Taxes/eb:TotalTaxAmount")
                            or self._xml_text(order_node, "./eb:TotalTaxAmount")
                            or "0"
                        ),
                        "shipping_amount": self._to_float_safe(
                            self._xml_text(order_node, "./eb:ShippingServiceSelected/eb:ShippingServiceCost")
                            or self._xml_text(order_node, "./eb:ShippingDetails/eb:ShippingServiceOptions/eb:ShippingServiceCost")
                        ),
                        "handling_amount": 0.0,
                        "total_amount": self._to_float_safe(
                            self._xml_text(order_node, "./eb:Total")
                            or self._xml_text(order_node, "./eb:AmountPaid")
                            or "0"
                        ),
                        "vendor_name": self._xml_text(order_node, "./eb:SellerUserID") or f"eBay Seller ({self.store_name})",
                        "items": [],
                    },
                )

                if not order_data.get("tracking_number"):
                    order_data["tracking_number"] = self._xml_text(
                        order_node,
                        "./eb:TransactionArray/eb:Transaction/eb:ShippingDetails/eb:ShipmentTrackingDetails/eb:ShipmentTrackingNumber",
                    )

                for transaction_node in transaction_nodes:
                    item_node = transaction_node.find("./eb:Item", _TRADING_NS)
                    quantity = self._to_int_safe(
                        self._xml_text(transaction_node, "./eb:QuantityPurchased")
                        or self._xml_text(transaction_node, "./eb:QuantityBought")
                        or "1"
                    )
                    unit_price = self._to_float_safe(
                        self._xml_text(transaction_node, "./eb:TransactionPrice")
                        or self._xml_text(transaction_node, "./eb:ConvertedTransactionPrice")
                        or "0"
                    )
                    if quantity <= 0:
                        quantity = 1

                    item_id = self._xml_text(item_node, "./eb:ItemID")
                    item_title = self._xml_text(item_node, "./eb:Title") or "Unknown eBay item"
                    transaction_id = self._xml_text(transaction_node, "./eb:TransactionID")

                    dedupe_key = (
                        str(item_id or ""),
                        str(transaction_id or ""),
                        item_title,
                        quantity,
                        unit_price,
                    )
                    existing_item_keys = order_item_keys.setdefault(order_id, set())
                    if dedupe_key in existing_item_keys:
                        page_skipped_deduped += 1
                        total_skipped_deduped += 1
                        continue
                    existing_item_keys.add(dedupe_key)

                    order_data["items"].append(
                        {
                            "external_item_id": item_id,
                            "purchase_item_link": f"https://www.ebay.com/itm/{item_id}" if item_id else None,
                            "external_item_name": item_title,
                            "quantity": quantity,
                            "unit_price": unit_price,
                        }
                    )
                    page_added += 1
                    page_items_added += 1
                    total_items_added += 1

            logger.debug(
                (
                    "[DEBUG.EXTERNAL_API] eBay %s GetOrders page=%s stats: orders=%s, items_added=%s, "
                    "skip_missing_order_id=%s, skip_missing_created_at=%s, skip_out_of_range=%s, "
                    "skip_deduped=%s, unique_orders_so_far=%s"
                ),
                self.store_name,
                page,
                page_transactions_seen,
                page_items_added,
                page_skipped_missing_order_id,
                page_skipped_missing_created_at,
                page_skipped_out_of_range,
                page_skipped_deduped,
                len(orders_by_id),
            )

            if page_added == 0:
                logger.debug(
                    "[DEBUG.EXTERNAL_API] eBay %s GetOrders page=%s added zero items; stopping pagination",
                    self.store_name,
                    page,
                )
                break

            has_more = self._xml_text(root, ".//eb:HasMoreOrders")
            if has_more and has_more.lower() == "false":
                break

            total_pages = self._to_int_safe(
                self._xml_text(root, ".//eb:PaginationResult/eb:TotalNumberOfPages")
            )
            if total_pages > 0 and page >= total_pages:
                break

        for order in orders_by_id.values():
            if order.get("total_amount", 0) <= 0:
                order["total_amount"] = sum(
                    float(item.get("unit_price", 0)) * int(item.get("quantity", 0))
                    for item in order.get("items", [])
                ) + float(order.get("shipping_amount", 0))

        logger.debug(
            (
                "[DEBUG.EXTERNAL_API] eBay %s GetOrders summary: unique_orders=%s, items_added=%s, "
                "orders_seen=%s, skip_missing_order_id=%s, skip_missing_created_at=%s, "
                "skip_out_of_range=%s, skip_deduped=%s, since=%s, until=%s"
            ),
            self.store_name,
            len(orders_by_id),
            total_items_added,
            total_transactions_seen,
            total_skipped_missing_order_id,
            total_skipped_missing_created_at,
            total_skipped_out_of_range,
            total_skipped_deduped,
            since.isoformat(),
            until.isoformat(),
        )

        return list(orders_by_id.values())

    def _xml_text(self, node: ET.Element | None, path: str) -> str | None:
        if node is None:
            return None
        target = node.find(path, _TRADING_NS)
        if target is None or target.text is None:
            return None
        text = target.text.strip()
        return text or None

    def _xml_attr(self, node: ET.Element | None, path: str, attr_name: str) -> str | None:
        if node is None:
            return None
        target = node.find(path, _TRADING_NS)
        if target is None:
            return None
        value = str(target.attrib.get(attr_name) or "").strip()
        return value or None

    def _parse_ebay_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _to_float_safe(self, value: str | None) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _to_int_safe(self, value: str | None) -> int:
        try:
            return int(float(value or 0))
        except Exception:
            return 0

    def _normalize_order_line_item_id(self, value: str | None) -> str | None:
        """Convert eBay OrderLineItemID (itemId-transactionId) into a single stable ID segment."""
        raw = str(value or "").strip()
        if not raw:
            return None

        if "-" not in raw:
            return raw

        segments = [segment.strip() for segment in raw.split("-") if segment.strip()]
        if not segments:
            return None

        # Prefer transaction ID segment to avoid very long combined identifiers in PO numbers.
        return segments[-1]
    
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
        
        logger.debug(
            f"[DEBUG.EXTERNAL_API] Fetching eBay {self.store_name} orders from {start_time} to {end_time}"
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
        logger.debug(f"[DEBUG.EXTERNAL_API] eBay {self.store_name} fetch_orders called: since={since}, until={until}, status={status}")
        
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
                since_str = since.strftime(EBAY_ISO_DATE_FORMAT)
                if until:
                    until_str = until.strftime(EBAY_ISO_DATE_FORMAT)
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
                
                logger.debug(f"[DEBUG.EXTERNAL_API] eBay {self.store_name}: Starting order fetch with filter={filter_param}")
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
                
                logger.debug(f"[DEBUG.EXTERNAL_API] eBay {self.store_name}: Successfully fetched {len(orders)} orders")
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
        logger.debug(f"[DEBUG.EXTERNAL_API] Fetching eBay {self.store_name} order: {order_id}")
        
        # TODO: Implement actual API call
        return None
    
    async def update_stock(self, updates: List[StockUpdate]) -> List[StockUpdateResult]:
        """
        Update inventory levels on eBay.
        
        Uses the Inventory API: PUT /sell/inventory/v1/inventory_item/{sku}
        """
        logger.debug(f"[DEBUG.EXTERNAL_API] Updating eBay {self.store_name} stock for {len(updates)} items")
        
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
        logger.debug(f"[DEBUG.EXTERNAL_API] Updating tracking for eBay order {order_id}: {carrier} {tracking_number}")
        
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
            customer_phone=shipping.get("primaryPhone", {}).get("phoneNumber") if isinstance(shipping.get("primaryPhone"), dict) else None,
            customer_source=f"{self.platform_name}_API",
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

