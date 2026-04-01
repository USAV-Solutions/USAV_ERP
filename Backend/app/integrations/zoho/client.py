"""
Zoho Inventory API Client.

Handles sync between USAV Inventory and Zoho Inventory/Books.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Any
import asyncio
import logging
import mimetypes
import json

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Zoho rate limit / throttling error."""

    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class ZohoClient:
    """
    Zoho Inventory/Books API client.
    
    This client handles:
    - Item sync (push SKU data to Zoho)
    - Stock level sync
    - Sales order creation
    
    Note: Zoho uses OAuth2 for authentication.
    Requires: client_id, client_secret, refresh_token, organization_id
    """
    
    ZOHO_ACCOUNTS_URL = "https://accounts.zoho.com"
    ZOHO_INVENTORY_API = "https://www.zohoapis.com/inventory/v1"
    ZOHO_BOOKS_API = "https://www.zohoapis.com/books/v3"
    
    # Shared token across instances to avoid refreshing per request
    _shared_access_token: Optional[str] = None
    _shared_token_expires_at: Optional[datetime] = None
    _token_lock: asyncio.Lock = asyncio.Lock()

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        organization_id: Optional[str] = None,
    ):
        self.client_id = client_id or settings.zoho_client_id
        self.client_secret = client_secret or settings.zoho_client_secret
        self.refresh_token = refresh_token or settings.zoho_refresh_token
        self.organization_id = organization_id or settings.zoho_organization_id

        self.accounts_url = getattr(settings, "zoho_accounts_url", self.ZOHO_ACCOUNTS_URL)
        self.inventory_api_url = getattr(settings, "zoho_inventory_api_base", self.ZOHO_INVENTORY_API)
        self.books_api_url = getattr(settings, "zoho_books_api_base", self.ZOHO_BOOKS_API)
        
        self._access_token = None
        self._token_expires_at = None
    
    async def _ensure_access_token(self):
        """Refresh access token if needed, with shared cache and lock."""
        async with ZohoClient._token_lock:
            # Reuse shared token if still valid
            if (
                ZohoClient._shared_access_token
                and ZohoClient._shared_token_expires_at
                and datetime.now() < ZohoClient._shared_token_expires_at
            ):
                self._access_token = ZohoClient._shared_access_token
                self._token_expires_at = ZohoClient._shared_token_expires_at
                return

            await self._refresh_access_token()
    
    async def _refresh_access_token(self):
        """Get new access token using refresh token."""
        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise ValueError("Zoho credentials not configured")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.accounts_url}/oauth/v2/token",
                params={
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                },
            )

        retry_after = None
        if response.status_code == 429:
            retry_after_header = response.headers.get("Retry-After")
            retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else 60
            logger.error("Zoho token refresh rate-limited (429). Retry after %ss", retry_after)
            raise RateLimitError("Zoho token refresh rate-limited", retry_after)

        if response.status_code == 400 and "too many requests" in response.text.lower():
            retry_after_header = response.headers.get("Retry-After")
            retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else 60
            logger.error("Zoho token refresh throttled (400). Retry after %ss | body=%s", retry_after, response.text)
            raise RateLimitError("Zoho token refresh throttled", retry_after)

        if response.status_code != 200:
            logger.error(f"Failed to refresh Zoho token: {response.text}")
            raise Exception("Failed to refresh Zoho access token")

        data = response.json()
        self._access_token = data["access_token"]
        # Zoho tokens expire in 1 hour, refresh slightly before
        from datetime import timedelta
        self._token_expires_at = datetime.now() + timedelta(minutes=55)

        ZohoClient._shared_access_token = self._access_token
        ZohoClient._shared_token_expires_at = self._token_expires_at

        logger.info("Zoho access token refreshed")
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        api: str = "inventory",
        **kwargs
    ) -> dict:
        """Make authenticated request to Zoho API with throttling awareness."""
        await self._ensure_access_token()

        base_url = self.inventory_api_url if api == "inventory" else self.books_api_url
        url = f"{base_url}{endpoint}"

        headers = kwargs.pop("headers", {})
        params = kwargs.pop("params", {})
        params["organization_id"] = self.organization_id

        payload_mode = "none"
        payload_keys: list[str] = []
        if "files" in kwargs:
            payload_mode = "files"
            files_payload = kwargs.get("files")
            if isinstance(files_payload, dict):
                payload_keys = list(files_payload.keys())
        elif "json" in kwargs:
            payload_mode = "json"
            json_payload = kwargs.get("json")
            if isinstance(json_payload, dict):
                payload_keys = list(json_payload.keys())
        elif "data" in kwargs:
            payload_mode = "data"
            data_payload = kwargs.get("data")
            if isinstance(data_payload, dict):
                payload_keys = list(data_payload.keys())

        logger.info(
            "Zoho request | method=%s endpoint=%s api=%s params=%s payload_mode=%s payload_keys=%s",
            method,
            endpoint,
            api,
            params,
            payload_mode,
            payload_keys,
        )

        async with httpx.AsyncClient() as client:
            # Retry once on 401 after a token refresh
            for attempt in range(2):
                auth_headers = {
                    "Authorization": f"Zoho-oauthtoken {self._access_token}",
                }
                if "json" in kwargs and "files" not in kwargs:
                    headers.setdefault("Content-Type", "application/json")
                request_headers = {**auth_headers, **headers}

                response = await client.request(
                    method,
                    url,
                    headers=request_headers,
                    params=params,
                    **kwargs
                )

                if response.status_code in (429,):
                    retry_after_header = response.headers.get("Retry-After")
                    retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else 60
                    logger.error("Zoho API rate limit hit (429). Retry after %ss | endpoint=%s", retry_after, endpoint)
                    raise RateLimitError("Zoho API rate limit hit", retry_after)

                # Zoho sometimes returns 400 with an Access Denied + too many requests message
                if response.status_code == 400 and "too many requests" in response.text.lower():
                    retry_after_header = response.headers.get("Retry-After")
                    retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else 60
                    logger.error(
                        "Zoho API throttled (400 too many requests). Retry after %ss | endpoint=%s body=%s",
                        retry_after,
                        endpoint,
                        response.text,
                    )
                    raise RateLimitError("Zoho API throttled", retry_after)

                if response.status_code == 401 and attempt == 0:
                    # Token might be expired; refresh and retry once
                    await self._refresh_access_token()
                    continue

                if response.status_code not in [200, 201]:
                    logger.error(f"Zoho API error: {response.status_code} - {response.text}")
                    raise Exception(f"Zoho API error: {response.text}")

                return response.json()

        raise Exception("Zoho API request failed after retry")
    
    # =========================================================================
    # ITEM SYNC
    # =========================================================================
    
    async def create_item(self, item_data: dict) -> dict:
        """Create an item in Zoho Inventory."""
        logger.info("Zoho create_item payload | sku=%s payload=%s", item_data.get("sku"), item_data)
        result = await self._request(
            "POST", 
            "/items", 
            data={"JSONString": json.dumps(item_data)}
        )
        return result.get("item", {})
    
    async def update_item(self, zoho_item_id: str, item_data: dict) -> dict:
        """
        Update an item in Zoho Inventory.
        
        Args:
            zoho_item_id: Zoho's item ID
            item_data: Updated item data
            
        Returns:
            Updated item data from Zoho
        """
        result = await self._request(
            "PUT", 
            f"/items/{zoho_item_id}", 
            data={"JSONString": json.dumps(item_data)}
        )
        return result.get("item", {})
    
    async def get_item_by_sku(self, sku: str) -> Optional[dict]:
        """
        Find a Zoho item by SKU.
        
        Args:
            sku: Item SKU
            
        Returns:
            Item data if found, None otherwise
        """
        result = await self._request(
            "GET",
            "/items",
            params={"sku": sku}
        )
        items = result.get("items", [])
        return items[0] if items else None

    async def get_item(self, item_id: str) -> dict:
        """Fetch a single item by Zoho item ID."""
        result = await self._request("GET", f"/items/{item_id}")
        return result.get("item", {})
    
    async def sync_item(
        self,
        sku: str,
        name: str,
        rate: float,
        description: Optional[str] = None,
        image_path: Optional[Path] = None,
        preferred_item_id: Optional[str] = None,
        **extra_fields
    ) -> dict:
        """
        Create or update an item in Zoho by SKU.
        
        This is the main sync method - it will create if not exists,
        or update if the item already exists.
        """
        item_data = {
            "name": name,
            "sku": sku,
            "rate": rate,
            "description": description or "",
            **extra_fields
        }

        # Prefer updating the previously-linked Zoho item to avoid SKU-change duplicates.
        if preferred_item_id:
            try:
                zoho_item = await self.update_item(preferred_item_id, item_data)
                zoho_item_id = zoho_item.get("item_id")
                if image_path and zoho_item_id:
                    logger.info(
                        "Zoho sync_item image upload | sku=%s zoho_item_id=%s image_path=%s",
                        sku,
                        zoho_item_id,
                        image_path,
                    )
                    await self.upload_item_image(zoho_item_id, image_path)
                return zoho_item
            except Exception as exc:
                logger.warning(
                    "Zoho sync_item preferred update failed, falling back to SKU upsert | sku=%s preferred_item_id=%s error=%s",
                    sku,
                    preferred_item_id,
                    exc,
                )
        
        # Check if item exists
        existing = await self.get_item_by_sku(sku)
        
        if existing:
            zoho_item = await self.update_item(existing["item_id"], item_data)
        else:
            try:
                zoho_item = await self.create_item(item_data)
            except Exception as exc:
                # Handle duplicate item gracefully (code 1001 or "already exists")
                if "already exists" in str(exc) or "code\":1001" in str(exc):
                    logger.info("Zoho sync_item: item already exists, fetching by sku | sku=%s", sku)
                    existing = await self.get_item_by_sku(sku)
                    if existing:
                        return existing
                raise

        zoho_item_id = zoho_item.get("item_id")
        if image_path and zoho_item_id:
            logger.info("Zoho sync_item image upload | sku=%s zoho_item_id=%s image_path=%s", sku, zoho_item_id, image_path)
            await self.upload_item_image(zoho_item_id, image_path)

        return zoho_item

    async def upload_item_image(self, zoho_item_id: str, image_path: Path) -> dict:
        """Upload an image to an existing Zoho inventory item's image gallery."""
        logger.info(
            "Zoho client upload_item_image called | zoho_item_id=%s image_path=%s exists=%s size_bytes=%s",
            zoho_item_id,
            image_path,
            image_path.exists(),
            image_path.stat().st_size if image_path.exists() else None,
        )
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found for Zoho upload: {image_path}")

        mime_type, _ = mimetypes.guess_type(str(image_path))
        content_type = mime_type or "application/octet-stream"
        logger.info(
            "Zoho client upload_item_image mime | zoho_item_id=%s filename=%s content_type=%s",
            zoho_item_id,
            image_path.name,
            content_type,
        )

        with image_path.open("rb") as image_file:
            result = await self._request(
                "POST",
                f"/items/{zoho_item_id}/images",
                files={"image": (image_path.name, image_file, content_type)},
            )
        logger.info(
            "Zoho client upload_item_image response | zoho_item_id=%s response_keys=%s",
            zoho_item_id,
            list(result.keys()) if isinstance(result, dict) else None,
        )
        return result

    async def create_composite_item(self, composite_data: dict) -> dict:
        """Create a composite item in Zoho Inventory."""
        logger.info(
            "Zoho create_composite_item payload | sku=%s component_count=%s payload=%s",
            composite_data.get("sku"),
            len(composite_data.get("component_items", [])),
            composite_data,
        )
        result = await self._request(
            "POST",
            "/compositeitems",
            data={"JSONString": json.dumps(composite_data)},
        )
        return result.get("composite_item", {})

    async def update_composite_item(self, composite_item_id: str, composite_data: dict) -> dict:
        """Update a Zoho composite item."""
        result = await self._request(
            "PUT",
            f"/compositeitems/{composite_item_id}",
            data={"JSONString": json.dumps(composite_data)},
        )
        return result.get("composite_item", {})

    async def get_composite_item_by_sku(self, sku: str) -> Optional[dict]:
        """Find a Zoho composite item by SKU."""
        result = await self._request("GET", "/compositeitems", params={"sku": sku})
        items = result.get("composite_items", [])
        return items[0] if items else None

    async def sync_composite_item(
        self,
        sku: str,
        name: str,
        rate: float,
        component_items: list[dict[str, Any]],
        description: Optional[str] = None,
        preferred_item_id: Optional[str] = None,
        **extra_fields,
    ) -> dict:
        """Create or update a composite item in Zoho by SKU."""
        composite_data = {
            "name": name,
            "sku": sku,
            "rate": rate,
            "description": description or "",
            "component_items": component_items,
            **extra_fields,
        }

        # Prefer updating the previously-linked Zoho composite record first.
        if preferred_item_id:
            try:
                return await self.update_composite_item(preferred_item_id, composite_data)
            except Exception as exc:
                logger.warning(
                    "Zoho sync_composite_item preferred update failed, falling back to SKU upsert | sku=%s preferred_item_id=%s error=%s",
                    sku,
                    preferred_item_id,
                    exc,
                )

        existing = await self.get_composite_item_by_sku(sku)
        if existing:
            return await self.update_composite_item(existing["composite_item_id"], composite_data)

        # If the SKU already exists as a standard Zoho item, do not try to create
        # another record; reuse it to avoid duplicate/create loops.
        existing_standard = await self.get_item_by_sku(sku)
        if existing_standard:
            logger.info(
                "Zoho sync_composite_item: found existing standard item, reusing by sku | sku=%s item_id=%s",
                sku,
                existing_standard.get("item_id"),
            )
            return existing_standard

        try:
            return await self.create_composite_item(composite_data)
        except Exception as exc:
            message = str(exc)
            if "already exists" in message or "code\":1001" in message:
                logger.info(
                    "Zoho sync_composite_item: duplicate on create, resolving existing by sku | sku=%s",
                    sku,
                )
                existing = await self.get_composite_item_by_sku(sku)
                if existing:
                    return existing
                existing_standard = await self.get_item_by_sku(sku)
                if existing_standard:
                    return existing_standard
            raise
    
    # =========================================================================
    # STOCK SYNC
    # =========================================================================
    
    async def update_stock(
        self,
        zoho_item_id: str,
        quantity: int,
        warehouse_id: Optional[str] = None
    ) -> dict:
        """
        Update stock level for an item in Zoho.
        
        Args:
            zoho_item_id: Zoho's item ID
            quantity: New stock quantity
            warehouse_id: Warehouse ID (optional)
            
        Returns:
            Stock update result
        """
        # Zoho uses inventory adjustments for stock changes
        adjustment_data = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "reason": "Stock sync from USAV Inventory",
            "line_items": [
                {
                    "item_id": zoho_item_id,
                    "quantity_adjusted": quantity,
                    "adjustment_type": "quantity",
                }
            ]
        }
        
        if warehouse_id:
            adjustment_data["line_items"][0]["warehouse_id"] = warehouse_id
        
        result = await self._request(
            "POST",
            "/inventoryadjustments",
            data={"JSONString": json.dumps(adjustment_data)}
        )
        return result
    
    async def get_stock_level(self, zoho_item_id: str) -> int:
        """
        Get current stock level for an item.
        
        Args:
            zoho_item_id: Zoho's item ID
            
        Returns:
            Current stock quantity
        """
        result = await self._request("GET", f"/items/{zoho_item_id}")
        item = result.get("item", {})
        return item.get("stock_on_hand", 0)
    
    # =========================================================================
    # SALES ORDERS
    # =========================================================================
    
    async def create_sales_order(self, order_data: dict) -> dict:
        """
        Create a sales order in Zoho.
        
        Args:
            order_data: Sales order data
            
        Returns:
            Created sales order from Zoho
        """
        result = await self._request(
            "POST",
            "/salesorders",
            data={"JSONString": json.dumps(order_data)}
        )
        return result.get("salesorder", {})

    async def update_salesorder(self, salesorder_id: str, order_data: dict) -> dict:
        """Update an existing sales order in Zoho."""
        result = await self._request(
            "PUT",
            f"/salesorders/{salesorder_id}",
            data={"JSONString": json.dumps(order_data)},
        )
        return result.get("salesorder", {})

    async def get_salesorder(self, salesorder_id: str) -> dict:
        """Fetch a single sales order by ID."""
        result = await self._request("GET", f"/salesorders/{salesorder_id}")
        return result.get("salesorder", {})

    async def list_salesorders(
        self,
        *,
        last_modified_time: Optional[str] = None,
        page: int = 1,
        per_page: int = 200,
    ) -> List[dict]:
        """
        List sales orders, optionally filtering by last modification time.

        ``last_modified_time`` format expected by Zoho: ``YYYY-MM-DDTHH:MM:SSZ``
        """
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if last_modified_time:
            params["last_modified_time"] = last_modified_time
        result = await self._request("GET", "/salesorders", params=params)
        return result.get("salesorders", [])

    async def confirm_salesorder(self, salesorder_id: str) -> dict:
        """Mark a sales order as *confirmed* in Zoho."""
        return await self._request("POST", f"/salesorders/{salesorder_id}/status/confirmed")

    # =========================================================================
    # PACKAGES (marks a sales order as "packed" in Zoho)
    # =========================================================================

    async def create_package(self, salesorder_id: str, line_items: List[dict]) -> dict:
        """
        Create a package for a sales order in Zoho Inventory.

        This transitions the sales order status to "packed" in Zoho.

        Args:
            salesorder_id: The Zoho sales order ID.
            line_items: List of dicts with ``so_line_item_id`` and ``quantity``.
        """
        payload = {"line_items": line_items}
        result = await self._request(
            "POST",
            f"/packages",
            params={"salesorder_id": salesorder_id},
            data={"JSONString": json.dumps(payload)},
        )
        return result.get("package", {})

    async def list_packages(self, salesorder_id: str) -> List[dict]:
        """List all packages for a given sales order."""
        result = await self._request(
            "GET",
            "/packages",
            params={"salesorder_id": salesorder_id},
        )
        return result.get("packages", [])

    # =========================================================================
    # SHIPMENT ORDERS (marks a sales order as "shipped" / "delivered")
    # =========================================================================

    async def create_shipment_order(
        self,
        salesorder_id: str,
        package_ids: List[str],
        *,
        tracking_number: Optional[str] = None,
        delivery_method: Optional[str] = None,
    ) -> dict:
        """
        Create a shipment order for one or more packages.

        Args:
            salesorder_id: The Zoho sales order ID.
            package_ids: List of package IDs to include.
            tracking_number: Optional carrier tracking number.
            delivery_method: Optional delivery method name.
        """
        payload: dict[str, Any] = {
            "salesorder_id": salesorder_id,
            "package_ids": package_ids,
        }
        if tracking_number:
            payload["tracking_number"] = tracking_number
        if delivery_method:
            payload["delivery_method"] = delivery_method

        result = await self._request(
            "POST",
            "/shipmentorders",
            data={"JSONString": json.dumps(payload)},
        )
        return result.get("shipmentorder", {})

    async def mark_shipment_delivered(self, shipment_order_id: str) -> dict:
        """Mark a shipment order as delivered in Zoho."""
        return await self._request(
            "POST",
            f"/shipmentorders/{shipment_order_id}/status/delivered",
        )

    async def list_shipment_orders(self, salesorder_id: str) -> List[dict]:
        """List all shipment orders for a given sales order."""
        result = await self._request(
            "GET",
            "/shipmentorders",
            params={"salesorder_id": salesorder_id},
        )
        return result.get("shipmentorders", [])

    # =========================================================================
    # CONTACTS (Customers)
    # =========================================================================

    async def create_contact(self, contact_data: dict, contact_type: Optional[str] = None) -> dict:
        """Create a contact in Zoho Inventory (customer or vendor)."""
        payload = dict(contact_data)
        if contact_type:
            payload["contact_type"] = contact_type
        logger.info(
            "Zoho create_contact payload | type=%s email=%s name=%s",
            payload.get("contact_type", "customer"),
            payload.get("email"),
            payload.get("contact_name"),
        )
        result = await self._request(
            "POST",
            "/contacts",
            data={"JSONString": json.dumps(payload)},
        )
        return result.get("contact", {})

    # =========================================================================
    # PURCHASE ORDERS
    # =========================================================================

    async def create_purchase_order(self, purchase_order_data: dict) -> dict:
        """Create a purchase order in Zoho Inventory."""
        result = await self._request(
            "POST",
            "/purchaseorders",
            data={"JSONString": json.dumps(purchase_order_data)},
        )
        return result.get("purchaseorder", {})

    async def update_purchase_order(self, purchase_order_id: str, purchase_order_data: dict) -> dict:
        """Update an existing purchase order in Zoho Inventory."""
        result = await self._request(
            "PUT",
            f"/purchaseorders/{purchase_order_id}",
            data={"JSONString": json.dumps(purchase_order_data)},
        )
        return result.get("purchaseorder", {})

    async def get_purchase_order(self, purchase_order_id: str) -> dict:
        """Fetch a single purchase order by ID."""
        result = await self._request("GET", f"/purchaseorders/{purchase_order_id}")
        return result.get("purchaseorder", {})

    async def list_purchase_orders(
        self,
        *,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        filter_by: str = "Status.All",
        page: int = 1,
        per_page: int = 200,
    ) -> List[dict]:
        """List purchase orders with pagination."""
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "filter_by": filter_by,
        }
        if date_start:
            params["date_start"] = date_start
        if date_end:
            params["date_end"] = date_end

        result = await self._request(
            "GET",
            "/purchaseorders",
            params=params,
        )
        return result.get("purchaseorders", [])

    async def find_purchase_order_by_number(
        self,
        purchaseorder_number: str,
        *,
        max_pages: int = 50,
        per_page: int = 200,
    ) -> Optional[dict]:
        """Find an existing purchase order by its purchase-order number."""
        normalized_number = str(purchaseorder_number or "").strip()
        if not normalized_number:
            return None

        page = 1
        while page <= max_pages:
            purchase_orders = await self.list_purchase_orders(page=page, per_page=per_page)
            if not purchase_orders:
                return None

            match = next(
                (
                    po
                    for po in purchase_orders
                    if str(po.get("purchaseorder_number") or "").strip() == normalized_number
                ),
                None,
            )
            if match is not None:
                return match

            if len(purchase_orders) < per_page:
                return None
            page += 1

        return None

    # =========================================================================
    # BILLS
    # =========================================================================

    async def get_bill(self, bill_id: str) -> dict:
        """Fetch a single bill by ID."""
        result = await self._request("GET", f"/bills/{bill_id}")
        return result.get("bill", {})

    async def list_bills(
        self,
        *,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        page: int = 1,
        per_page: int = 200,
    ) -> List[dict]:
        """List bills from Zoho Books with optional date range and pagination."""
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "filter_by": "Status.All",
        }
        if date_start:
            params["date_start"] = date_start
        if date_end:
            params["date_end"] = date_end
        result = await self._request("GET", "/bills", api="books", params=params)
        return result.get("bills", [])

    async def list_bill_payments(self, bill_id: str) -> List[dict]:
        """List payments applied to a bill from Zoho Books."""
        result = await self._request("GET", f"/bills/{bill_id}/payments", api="books")
        return result.get("payments", [])

    async def delete_bill_payment(self, bill_id: str, bill_payment_id: str) -> dict:
        """Delete a bill payment in Zoho Books."""
        return await self._request(
            "DELETE",
            f"/bills/{bill_id}/payments/{bill_payment_id}",
            api="books",
        )

    async def delete_bill_payment_reference(self, payment: dict) -> dict:
        """Delete a bill payment from a payment payload object.

        Accepts payloads with keys commonly returned by Zoho (`bill_id`, `bill_payment_id`).
        """
        bill_id = str((payment or {}).get("bill_id") or "").strip()
        bill_payment_id = str((payment or {}).get("bill_payment_id") or "").strip()
        if not bill_id or not bill_payment_id:
            raise ValueError("payment payload must include bill_id and bill_payment_id")
        return await self.delete_bill_payment(bill_id=bill_id, bill_payment_id=bill_payment_id)

    async def delete_bill(self, bill_id: str) -> dict:
        """Delete a bill in Zoho Inventory."""
        return await self._request("DELETE", f"/bills/{bill_id}", api="books")

    async def create_bill(self, bill_data: dict) -> dict:
        """Create a bill in Zoho Inventory."""
        result = await self._request(
            "POST",
            "/bills",
            api="books",
            data={"JSONString": json.dumps(bill_data)},
        )
        return result.get("bill", {})

    async def list_purchase_receives(
        self,
        *,
        purchaseorder_id: Optional[str] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        page: int = 1,
        per_page: int = 200,
    ) -> List[dict]:
        """List purchase receives with optional PO/date filters."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if purchaseorder_id:
            params["purchaseorder_id"] = purchaseorder_id
        if date_start:
            params["date_start"] = date_start
        if date_end:
            params["date_end"] = date_end

        result = await self._request("GET", "/purchasereceives", params=params)
        receives = result.get("purchase_receives")
        if receives is None:
            receives = result.get("purchasereceives", [])
        return receives or []

    async def delete_purchase_receive(self, purchase_receive_id: str) -> dict:
        """Delete a purchase receive in Zoho Inventory."""
        return await self._request("DELETE", f"/purchasereceives/{purchase_receive_id}")

    async def create_purchase_receive(self, purchase_receive_data: dict) -> dict:
        """Create a purchase receive in Zoho Inventory."""
        result = await self._request(
            "POST",
            "/purchasereceives",
            data={"JSONString": json.dumps(purchase_receive_data)},
        )
        receive = result.get("purchasereceive")
        if receive is None:
            receive = result.get("purchase_receive", {})
        return receive or {}

    async def list_vendor_payments(
        self,
        *,
        page: int = 1,
        per_page: int = 200,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> List[dict]:
        """List vendor payments in Zoho Inventory."""
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
        }
        if date_start:
            params["date_start"] = date_start
        if date_end:
            params["date_end"] = date_end

        result = await self._request("GET", "/vendorpayments", params=params)
        payments = result.get("vendorpayments")
        if payments is None:
            payments = result.get("vendor_payments", [])
        return payments or []

    async def create_vendor_payment(self, vendor_payment_data: dict) -> dict:
        """Create a vendor payment in Zoho Inventory."""
        result = await self._request(
            "POST",
            "/vendorpayments",
            data={"JSONString": json.dumps(vendor_payment_data)},
        )
        payment = result.get("vendorpayment")
        if payment is None:
            payment = result.get("vendor_payment", {})
        return payment or {}

    async def ensure_item_by_sku(
        self,
        *,
        sku: str,
        name: str,
        rate: float = 0.0,
        description: str = "",
    ) -> dict:
        """Ensure an item exists for the given SKU by fetching first, then creating if needed."""
        normalized_sku = str(sku or "").strip()
        normalized_name = str(name or "").strip()
        if not normalized_sku:
            raise ValueError("sku is required")
        if not normalized_name:
            raise ValueError("name is required")

        existing = await self.get_item_by_sku(normalized_sku)
        if existing:
            return existing

        item_data = {
            "name": normalized_name,
            "sku": normalized_sku,
            "rate": float(rate or 0),
            "description": description or "",
            "item_type": "inventory",
            "product_type": "goods",
        }
        try:
            return await self.create_item(item_data)
        except Exception as exc:
            # Handle duplicate/create race by re-fetching by SKU.
            if "already exists" in str(exc) or "code\":1001" in str(exc):
                existing = await self.get_item_by_sku(normalized_sku)
                if existing:
                    return existing
            raise

    async def update_contact(self, contact_id: str, contact_data: dict) -> dict:
        """Update an existing contact in Zoho Inventory."""
        result = await self._request(
            "PUT",
            f"/contacts/{contact_id}",
            data={"JSONString": json.dumps(contact_data)},
        )
        return result.get("contact", {})

    async def get_contact(self, contact_id: str) -> dict:
        """Fetch a single contact by ID."""
        result = await self._request("GET", f"/contacts/{contact_id}")
        return result.get("contact", {})

    async def get_contact_by_email(self, email: str) -> Optional[dict]:
        """Find a Zoho contact by email address."""
        result = await self._request("GET", "/contacts", params={"email": email})
        contacts = result.get("contacts", [])
        return contacts[0] if contacts else None

    async def list_contacts(
        self,
        *,
        last_modified_time: Optional[str] = None,
        page: int = 1,
        per_page: int = 200,
    ) -> List[dict]:
        """List contacts, optionally filtering by last modification time."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if last_modified_time:
            params["last_modified_time"] = last_modified_time
        result = await self._request("GET", "/contacts", params=params)
        return result.get("contacts", [])

    # =========================================================================
    # STATUS TOGGLES (soft-delete / reactivate)
    # =========================================================================

    async def mark_item_inactive(self, zoho_item_id: str) -> dict:
        """Mark an item as *inactive* in Zoho (soft-delete)."""
        return await self._request("POST", f"/items/{zoho_item_id}/inactive")

    async def mark_item_active(self, zoho_item_id: str) -> dict:
        """Mark an item as *active* in Zoho (restore)."""
        return await self._request("POST", f"/items/{zoho_item_id}/active")

    async def mark_contact_inactive(self, contact_id: str) -> dict:
        """Mark a contact as *inactive* in Zoho (soft-delete)."""
        return await self._request("POST", f"/contacts/{contact_id}/inactive")

    async def mark_contact_active(self, contact_id: str) -> dict:
        """Mark a contact as *active* in Zoho (restore)."""
        return await self._request("POST", f"/contacts/{contact_id}/active")

    # =========================================================================
    # ITEMS – LISTING HELPERS (for reconciliation)
    # =========================================================================

    async def list_items(
        self,
        *,
        last_modified_time: Optional[str] = None,
        page: int = 1,
        per_page: int = 200,
    ) -> List[dict]:
        """List items, optionally since *last_modified_time*."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if last_modified_time:
            params["last_modified_time"] = last_modified_time
        result = await self._request("GET", "/items", params=params)
        return result.get("items", [])
    
    async def health_check(self) -> bool:
        """Check if Zoho API is accessible."""
        try:
            await self._ensure_access_token()
            # Try to list items with limit 1
            await self._request("GET", "/items", params={"per_page": 1})
            return True
        except Exception as e:
            logger.error(f"Zoho health check failed: {e}")
            return False

