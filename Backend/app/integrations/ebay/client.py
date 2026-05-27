"""
eBay Trading API Client.

Implements the BasePlatformClient interface for eBay stores.
"""
import asyncio
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional
import logging
import socket
from html import escape
from urllib.parse import quote, urlparse
import xml.etree.ElementTree as ET
import httpx

from app.core.config import settings
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
                "https://api.ebay.com/oauth/api_scope/sell.inventory "
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
                    
                    # Hydrate each order from the detail endpoint so line items
                    # carry legacyItemId as the external ref id.
                    for order_data in page_orders:
                        try:
                            order_id = order_data.get("orderId")
                            if not order_id:
                                logger.debug(
                                    f"[DEBUG.EXTERNAL_API] eBay {self.store_name}: skipping order without orderId in list response"
                                )
                                continue
                            detailed_order = await self.get_order(order_id)
                            if detailed_order is not None:
                                orders.append(detailed_order)
                        except Exception as e:
                            logger.error(
                                f"eBay {self.store_name}: Error hydrating order {order_data.get('orderId')}: {e}",
                                exc_info=True
                            )
                    
                    # Check if there are more pages
                    total = data.get("total", 0)
                    offset += len(page_orders)
                    logger.debug(f"eBay {self.store_name}: Progress {offset}/{total}")
                    
                    if offset >= total:
                        logger.debug(f"eBay {self.store_name}: Reached end of results")
                        break
                
                logger.debug(f"[DEBUG.EXTERNAL_API] eBay {self.store_name}: Successfully fetched {len(orders)} orders via detail endpoint")
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
        try:
            path = f"/sell/fulfillment/v1/order/{quote(str(order_id), safe='')}"
            payload = await self._rest_get(path)
            if not payload:
                return None
            # Payload is the Order object
            return self._convert_order(payload)
        except httpx.HTTPStatusError as e:
            logger.error(
                f"eBay {self.store_name}: get_order HTTP {e.response.status_code} - {e.response.text}",
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error(
                f"eBay {self.store_name}: get_order error for {order_id}: {e}",
                exc_info=True,
            )
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

    def _store_key(self) -> str:
        return self.store_name.lower()

    def get_store_listing_defaults(self) -> dict[str, Any]:
        store = self._store_key()
        return {
            "marketplace_id": getattr(settings, f"ebay_marketplace_id_{store}", "EBAY_US"),
            "country": getattr(settings, f"ebay_country_{store}", "US"),
            "currency": getattr(settings, f"ebay_currency_{store}", "USD"),
            "location": getattr(settings, f"ebay_location_{store}", ""),
            "postal_code": getattr(settings, f"ebay_postal_code_{store}", ""),
            "dispatch_time_max": getattr(settings, f"ebay_dispatch_time_max_{store}", 1),
            "payment_profile_id": (
                getattr(settings, f"ebay_payment_policy_id_{store}", "")
                or getattr(settings, f"ebay_payment_profile_id_{store}", "")
            ),
            "return_profile_id": (
                getattr(settings, f"ebay_return_policy_id_{store}", "")
                or getattr(settings, f"ebay_return_profile_id_{store}", "")
            ),
            "shipping_profile_id": (
                getattr(settings, f"ebay_fulfillment_policy_id_light_{store}", "")
                or getattr(settings, f"ebay_shipping_policy_id_{store}", "")
                or getattr(settings, f"ebay_shipping_profile_id_{store}", "")
            ),
            "payment_policy_id": (
                getattr(settings, f"ebay_payment_policy_id_{store}", "")
                or getattr(settings, f"ebay_payment_profile_id_{store}", "")
            ),
            "return_policy_id": (
                getattr(settings, f"ebay_return_policy_id_{store}", "")
                or getattr(settings, f"ebay_return_profile_id_{store}", "")
            ),
            "fulfillment_policy_id": (
                getattr(settings, f"ebay_fulfillment_policy_id_light_{store}", "")
                or getattr(settings, f"ebay_shipping_policy_id_{store}", "")
                or getattr(settings, f"ebay_shipping_profile_id_{store}", "")
            ),
            "merchant_location_key": getattr(settings, f"ebay_merchant_location_key_{store}", ""),
            "warehouse_address1": getattr(settings, f"ebay_warehouse_address1_{store}", ""),
            "warehouse_address2": getattr(settings, f"ebay_warehouse_address2_{store}", ""),
            "warehouse_city": getattr(settings, f"ebay_warehouse_city_{store}", ""),
            "warehouse_state": getattr(settings, f"ebay_warehouse_state_{store}", ""),
            "warehouse_postal_code": getattr(settings, f"ebay_warehouse_postal_code_{store}", ""),
            "warehouse_country": getattr(settings, f"ebay_warehouse_country_{store}", "US"),
            "return_policy_id_no_returns": getattr(settings, f"ebay_return_policy_id_no_returns_{store}", ""),
            "fulfillment_policy_id_light": getattr(settings, f"ebay_fulfillment_policy_id_light_{store}", ""),
            "fulfillment_policy_id_heavy": getattr(settings, f"ebay_fulfillment_policy_id_heavy_{store}", ""),
            "fulfillment_policy_id_free": getattr(settings, f"ebay_fulfillment_policy_id_free_{store}", ""),
            "heavy_item_threshold_lbs": getattr(settings, f"ebay_heavy_item_threshold_lbs_{store}", 2.0),
        }

    @staticmethod
    def to_condition_id(raw_condition: str | None) -> int | None:
        text = (raw_condition or "").strip().upper()
        if not text:
            return None
        mapping = {
            "N": 1000,
            "NEW": 1000,
            "1000": 1000,
            "U": 3000,
            "USED": 3000,
            "3000": 3000,
            "R": 2000,
            "REFURBISHED": 2000,
            "2000": 2000,
            "FOR_PARTS": 7000,
            "FOR PARTS": 7000,
            "PARTS": 7000,
            "NOT_WORKING": 7000,
            "NOT WORKING": 7000,
            "7000": 7000,
        }
        return mapping.get(text)

    @staticmethod
    def to_item_specifics(
        *,
        brand: str | None,
        mpn: str | None,
        color: str | None,
        upc: str | None,
        extra_specifics: list[dict[str, str]] | None = None,
    ) -> list[dict[str, list[str]]]:
        specifics: list[dict[str, list[str]]] = []
        if brand:
            specifics.append({"Name": "Brand", "Value": [brand]})
        if mpn:
            specifics.append({"Name": "MPN", "Value": [mpn]})
        if color:
            specifics.append({"Name": "Color", "Value": [color]})
        if upc:
            specifics.append({"Name": "UPC", "Value": [upc]})
        if extra_specifics:
            for item in extra_specifics:
                name = (item.get("name") or "").strip()
                value = (item.get("value") or "").strip()
                if not name or not value:
                    continue
                specifics.append({"Name": name, "Value": [value]})
        return specifics

    @staticmethod
    def to_shipping_package_details(
        *,
        weight_lbs: float | None,
        length_in: float | None,
        width_in: float | None,
        height_in: float | None,
    ) -> dict[str, str] | None:
        if (
            weight_lbs is None
            or length_in is None
            or width_in is None
            or height_in is None
        ):
            return None
        total_oz = max(weight_lbs * 16.0, 0.0)
        weight_major = int(total_oz // 16)
        weight_minor = int(round(total_oz - (weight_major * 16)))
        return {
            "WeightMajor": str(weight_major),
            "WeightMinor": str(max(weight_minor, 0)),
            "PackageLength": f"{length_in:.2f}",
            "PackageWidth": f"{width_in:.2f}",
            "PackageDepth": f"{height_in:.2f}",
        }

    @staticmethod
    def _to_cdata(text: str) -> str:
        return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"

    @staticmethod
    def to_inventory_condition(raw_condition: str | None) -> str | None:
        text = (raw_condition or "").strip().upper()
        if not text:
            return None
        mapping = {
            "N": "NEW",
            "NEW": "NEW",
            "1000": "NEW",
            "U": "USED_GOOD",
            "USED": "USED_GOOD",
            "3000": "USED_GOOD",
            "R": "SELLER_REFURBISHED",
            "REFURBISHED": "SELLER_REFURBISHED",
            "2000": "SELLER_REFURBISHED",
            "FOR_PARTS": "FOR_PARTS_OR_NOT_WORKING",
            "FOR PARTS": "FOR_PARTS_OR_NOT_WORKING",
            "PARTS": "FOR_PARTS_OR_NOT_WORKING",
            "NOT_WORKING": "FOR_PARTS_OR_NOT_WORKING",
            "NOT WORKING": "FOR_PARTS_OR_NOT_WORKING",
            "7000": "FOR_PARTS_OR_NOT_WORKING",
        }
        return mapping.get(text)

    def build_add_fixed_price_item_xml(self, payload: dict[str, Any]) -> str:
        def text(value: Any) -> str:
            return escape(str(value if value is not None else ""))

        item_specifics_xml = ""
        for spec in payload.get("item_specifics", []):
            values_xml = "".join(f"<Value>{text(v)}</Value>" for v in spec.get("Value", []))
            item_specifics_xml += (
                "<NameValueList>"
                f"<Name>{text(spec.get('Name', ''))}</Name>"
                f"{values_xml}"
                "</NameValueList>"
            )

        picture_urls_xml = "".join(
            f"<PictureURL>{text(url)}</PictureURL>"
            for url in payload.get("picture_urls", [])
        )

        package_xml = ""
        package = payload.get("shipping_package_details") or {}
        if package:
            package_xml = (
                "<ShippingPackageDetails>"
                f"<WeightMajor>{text(package.get('WeightMajor'))}</WeightMajor>"
                f"<WeightMinor>{text(package.get('WeightMinor'))}</WeightMinor>"
                f"<PackageLength>{text(package.get('PackageLength'))}</PackageLength>"
                f"<PackageWidth>{text(package.get('PackageWidth'))}</PackageWidth>"
                f"<PackageDepth>{text(package.get('PackageDepth'))}</PackageDepth>"
                "</ShippingPackageDetails>"
            )

        seller_profiles_xml = ""
        payment_profile_id = (payload.get("payment_profile_id") or "").strip() if isinstance(payload.get("payment_profile_id"), str) else payload.get("payment_profile_id")
        return_profile_id = (payload.get("return_profile_id") or "").strip() if isinstance(payload.get("return_profile_id"), str) else payload.get("return_profile_id")
        shipping_profile_id = (payload.get("shipping_profile_id") or "").strip() if isinstance(payload.get("shipping_profile_id"), str) else payload.get("shipping_profile_id")
        if payment_profile_id and return_profile_id and shipping_profile_id:
            seller_profiles_xml = (
                "<SellerProfiles>"
                "<SellerPaymentProfile>"
                f"<PaymentProfileID>{text(payment_profile_id)}</PaymentProfileID>"
                "</SellerPaymentProfile>"
                "<SellerReturnProfile>"
                f"<ReturnProfileID>{text(return_profile_id)}</ReturnProfileID>"
                "</SellerReturnProfile>"
                "<SellerShippingProfile>"
                f"<ShippingProfileID>{text(shipping_profile_id)}</ShippingProfileID>"
                "</SellerShippingProfile>"
                "</SellerProfiles>"
            )

        return f"""<?xml version="1.0" encoding="utf-8"?>
<AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
  <Item>
    <Title>{text(payload["title"])}</Title>
    <Description>{self._to_cdata(payload["description"])}</Description>
    <PrimaryCategory>
      <CategoryID>{text(payload["category_id"])}</CategoryID>
    </PrimaryCategory>
    <StartPrice>{text(payload["price"])}</StartPrice>
    <ConditionID>{text(payload["condition_id"])}</ConditionID>
    <Country>{text(payload["country"])}</Country>
    <Currency>{text(payload["currency"])}</Currency>
    <DispatchTimeMax>{text(payload["dispatch_time_max"])}</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Location>{text(payload["location"])}</Location>
    <PostalCode>{text(payload["postal_code"])}</PostalCode>
    <Quantity>{text(payload["quantity"])}</Quantity>
    <SKU>{text(payload["sku"])}</SKU>
    <PictureDetails>{picture_urls_xml}</PictureDetails>
    <ItemSpecifics>{item_specifics_xml}</ItemSpecifics>
    {package_xml}
    {seller_profiles_xml}
  </Item>
</AddFixedPriceItemRequest>"""

    async def _rest_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> dict[str, Any]:
        access_token = await self._get_access_token()
        if not access_token:
            raise RuntimeError(f"eBay {self.store_name} unable to obtain access token")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": accept,
        }
        transport = httpx.AsyncHTTPTransport(retries=_TRANSPORT_RETRIES)
        async with httpx.AsyncClient(transport=transport, timeout=30.0) as client:
            response = await client.request(
                method.upper(),
                f"{self.base_url}{path}",
                headers=headers,
                params=params or {},
                json=json_body,
            )
            response.raise_for_status()
        if not response.content:
            return {}
        try:
            return response.json()
        except Exception:
            return {}

    async def _rest_get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._rest_request("GET", path, params=params)

    async def _rest_post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> dict[str, Any]:
        return await self._rest_request("POST", path, params=params, json_body=body, accept=accept)

    async def _rest_put(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> dict[str, Any]:
        return await self._rest_request("PUT", path, params=params, json_body=body, accept=accept)

    async def get_default_category_tree_id(self, marketplace_id: str) -> str:
        logger.debug(
            "[DEBUG.EXTERNAL_API] eBay %s taxonomy call method=GET url=%s params=%s headers=%s",
            self.store_name,
            f"{self.base_url}/commerce/taxonomy/v1/get_default_category_tree_id",
            {"marketplace_id": marketplace_id},
            {"Accept": "application/json", "Authorization": "Bearer <redacted>"},
        )
        payload = await self._rest_get(
            "/commerce/taxonomy/v1/get_default_category_tree_id",
            params={"marketplace_id": marketplace_id},
        )
        logger.debug(
            "[DEBUG.EXTERNAL_API] eBay %s taxonomy response get_default_category_tree_id=%s",
            self.store_name,
            payload,
        )
        category_tree_id = payload.get("categoryTreeId")
        if not category_tree_id:
            raise RuntimeError("eBay taxonomy did not return categoryTreeId")
        return str(category_tree_id)

    async def get_category_suggestions(self, category_tree_id: str, query_text: str) -> list[dict[str, Any]]:
        logger.debug(
            "[DEBUG.EXTERNAL_API] eBay %s taxonomy call method=GET url=%s params=%s headers=%s",
            self.store_name,
            f"{self.base_url}/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_category_suggestions",
            {"q": query_text},
            {"Accept": "application/json", "Authorization": "Bearer <redacted>"},
        )
        payload = await self._rest_get(
            f"/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_category_suggestions",
            params={"q": query_text},
        )
        logger.debug(
            "[DEBUG.EXTERNAL_API] eBay %s taxonomy response get_category_suggestions=%s",
            self.store_name,
            payload,
        )
        return payload.get("categorySuggestions", [])

    async def get_fulfillment_policies(self, marketplace_id: str) -> list[dict[str, Any]]:
        payload = await self._rest_get(
            "/sell/account/v1/fulfillment_policy",
            params={"marketplace_id": marketplace_id},
        )
        return payload.get("fulfillmentPolicies", [])

    async def put_inventory_item(self, sku: str, payload: dict[str, Any]) -> dict[str, Any]:
        encoded_sku = quote(sku, safe="")
        return await self._rest_put(
            f"/sell/inventory/v1/inventory_item/{encoded_sku}",
            body=payload,
        )

    async def get_offer_by_sku(self, sku: str, marketplace_id: str) -> dict[str, Any] | None:
        payload = await self._rest_get(
            "/sell/inventory/v1/offer",
            params={"sku": sku, "marketplace_id": marketplace_id},
        )
        offers = payload.get("offers") or []
        if not offers:
            return None
        first = offers[0] if isinstance(offers[0], dict) else None
        if not first:
            return None
        return first

    async def create_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._rest_post("/sell/inventory/v1/offer", body=payload)

    async def update_offer(self, offer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._rest_put(f"/sell/inventory/v1/offer/{offer_id}", body=payload)

    async def publish_offer(self, offer_id: str) -> dict[str, Any]:
        return await self._rest_post(f"/sell/inventory/v1/offer/{offer_id}/publish")

    async def get_item_aspects_for_category(
        self,
        *,
        category_tree_id: str,
        category_id: str,
    ) -> list[dict[str, Any]]:
        payload = await self._rest_get(
            f"/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_item_aspects_for_category",
            params={"category_id": category_id},
        )
        return payload.get("aspects", [])

    async def get_valid_conditions_for_category(
        self,
        *,
        marketplace_id: str,
        category_id: str,
    ) -> list[dict[str, Any]]:
        payload = await self._rest_get(
            f"/sell/metadata/v1/marketplace/{marketplace_id}/get_item_condition_policies",
            params={"filter": f"category_ids:{{{category_id}}}"},
        )
        policies = payload.get("itemConditionPolicies") or []
        if not policies:
            return []
        first = policies[0] if isinstance(policies[0], dict) else {}
        conditions = first.get("itemConditions") or []
        return [entry for entry in conditions if isinstance(entry, dict)]

    async def start_listing_previews_creation(self, external_product: dict[str, Any]) -> str:
        mutation = (
            "mutation StartListingPreviewsCreation($input: StartListingPreviewsCreationInput!) { "
            "startListingPreviewsCreation(input: $input) { "
            "listingPreviewsCreationTask { id } "
            "errors { errorDescription } "
            "} "
            "}"
        )
        payload = await self._rest_post(
            "/commerce/inventory_mapping/v1/graphql",
            body={
                "query": mutation,
                "variables": {"input": {"externalProducts": [external_product]}},
            },
        )
        result = (payload.get("data") or {}).get("startListingPreviewsCreation") or {}
        task = result.get("listingPreviewsCreationTask") or {}
        task_id = task.get("id")
        if task_id:
            return str(task_id)
        errors = result.get("errors") or payload.get("errors") or []
        if errors:
            message = ", ".join(
                str(err.get("errorDescription") or err.get("message") or "").strip()
                for err in errors
                if isinstance(err, dict)
            ).strip()
            if message:
                raise RuntimeError(message)
        raise RuntimeError("eBay GraphQL did not return listing preview task ID")

    async def poll_listing_previews_task_by_id(
        self,
        task_id: str,
        *,
        max_attempts: int = 10,
        delay_seconds: float = 2.0,
    ) -> dict[str, Any]:
        query = (
            "query($input: ListingPreviewsCreationTaskByIdInput!) { "
            "listingPreviewsCreationTaskById(input: $input) { "
            "listingPreviewsCreationTask { "
            "id "
            "result { "
            "completionStatus "
            "listingPreviews { title description category { id categoryId categoryName } aspects { name aspectValues values } } "
            "invalidProducts { clientProvidedProductDetails { title sku } } "
            "} "
            "} "
            "} "
            "}"
        )
        for _ in range(max_attempts):
            payload = await self._rest_post(
                "/commerce/inventory_mapping/v1/graphql",
                body={
                    "query": query,
                    "variables": {"input": {"id": task_id}},
                },
            )
            task = (
                ((payload.get("data") or {}).get("listingPreviewsCreationTaskById") or {}).get(
                    "listingPreviewsCreationTask"
                )
                or {}
            )
            result = task.get("result") or {}
            status = str(result.get("completionStatus") or "").strip().upper()
            if status in {"COMPLETED", "COMPLETED_WITH_ERROR"}:
                return result
            await asyncio.sleep(delay_seconds)
        raise RuntimeError("eBay listing preview task timed out")

    async def create_media_image_from_file(self, file_path: Path) -> str:
        if not file_path.is_file():
            raise FileNotFoundError(f"Image file not found: {file_path}")
        access_token = await self._get_access_token()
        if not access_token:
            raise RuntimeError(f"eBay {self.store_name} unable to obtain access token")

        content_type = "application/octet-stream"
        ext = file_path.suffix.lower()
        if ext in {".jpg", ".jpeg"}:
            content_type = "image/jpeg"
        elif ext == ".png":
            content_type = "image/png"
        elif ext == ".webp":
            content_type = "image/webp"
        elif ext == ".gif":
            content_type = "image/gif"
        elif ext == ".bmp":
            content_type = "image/bmp"
        elif ext == ".tiff":
            content_type = "image/tiff"
        elif ext == ".avif":
            content_type = "image/avif"
        elif ext == ".heic":
            content_type = "image/heic"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        url = f"{self.base_url}/commerce/media/v1_beta/image/create_image_from_file"
        logger.debug(
            "[DEBUG.EXTERNAL_API] eBay %s media upload call method=POST url=%s filename=%s content_type=%s headers=%s",
            self.store_name,
            url,
            file_path.name,
            content_type,
            {"Accept": "application/json", "Authorization": "Bearer <redacted>"},
        )
        transport = httpx.AsyncHTTPTransport(retries=_TRANSPORT_RETRIES)
        async with httpx.AsyncClient(transport=transport, timeout=60.0) as client:
            with file_path.open("rb") as image_file:
                files = {
                    "image": (file_path.name, image_file, content_type),
                }
                response = await client.post(url, headers=headers, files=files)
        if response.status_code >= 400:
            logger.debug(
                "[DEBUG.EXTERNAL_API] eBay %s media upload failure status=%s body=%s",
                self.store_name,
                response.status_code,
                response.text,
            )
            response.raise_for_status()
        payload = response.json()
        logger.debug(
            "[DEBUG.EXTERNAL_API] eBay %s media upload response=%s",
            self.store_name,
            payload,
        )
        image_url = payload.get("imageUrl")
        if not image_url:
            raise RuntimeError("eBay Media API response missing imageUrl")
        return str(image_url)

    async def _post_trading_xml(self, call_name: str, request_xml: str) -> ET.Element:
        access_token = await self._get_access_token()
        if not access_token:
            raise RuntimeError(f"eBay {self.store_name} unable to obtain access token")
        headers = {
            "Content-Type": "text/xml",
            "X-EBAY-API-CALL-NAME": call_name,
            "X-EBAY-API-COMPATIBILITY-LEVEL": "1231",
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-IAF-TOKEN": access_token,
        }
        transport = httpx.AsyncHTTPTransport(retries=_TRANSPORT_RETRIES)
        async with httpx.AsyncClient(transport=transport, timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/ws/api.dll",
                headers=headers,
                content=request_xml,
            )
            response.raise_for_status()
        root = ET.fromstring(response.text)
        ack = self._xml_text(root, "./eb:Ack")
        if ack and ack.lower() in {"failure", "partialfailure"}:
            short_message = self._xml_text(root, "./eb:Errors/eb:LongMessage") or self._xml_text(
                root, "./eb:Errors/eb:ShortMessage"
            )
            raise RuntimeError(short_message or f"eBay {call_name} failed")
        return root

    async def verify_add_fixed_price_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        xml_payload = self.build_add_fixed_price_item_xml(payload).replace(
            "<AddFixedPriceItemRequest", "<VerifyAddFixedPriceItemRequest", 1
        ).replace("</AddFixedPriceItemRequest>", "</VerifyAddFixedPriceItemRequest>", 1)
        root = await self._post_trading_xml("VerifyAddFixedPriceItem", xml_payload)
        fees = []
        for fee_node in root.findall(".//eb:Fees/eb:Fee", _TRADING_NS):
            fees.append(
                {
                    "name": self._xml_text(fee_node, "./eb:Name"),
                    "fee": self._xml_text(fee_node, "./eb:Fee"),
                }
            )
        return {"fees": fees}

    async def add_fixed_price_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        xml_payload = self.build_add_fixed_price_item_xml(payload)
        root = await self._post_trading_xml("AddFixedPriceItem", xml_payload)
        item_id = self._xml_text(root, "./eb:ItemID")
        if not item_id:
            raise RuntimeError("eBay AddFixedPriceItem succeeded without ItemID")
        return {"item_id": item_id}

    def _convert_order(self, ebay_order: dict) -> ExternalOrder:
        """Convert eBay order JSON to ExternalOrder."""
        # Extract shipping address
        instructions = ebay_order.get("fulfillmentStartInstructions") or []
        shipping = (
            instructions[0].get("shippingStep", {}).get("shipTo", {})
            if instructions
            else {}
        )
        
        # Convert line items. Prefer explicit item/listing ids when present
        items = []
        for item in ebay_order.get("lineItems", []):
            items.append(ExternalOrderItem(
                platform_item_id=(item.get("legacyItemId") or item.get("itemId") or item.get("listingId") or item.get("lineItemId")),
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
            ship_address_line3=None,
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
