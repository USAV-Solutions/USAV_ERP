"""
Zoho Inventory API Client.

Handles sync between USAV Inventory and Zoho Inventory/Books.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Any
import logging
import mimetypes
import json

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


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
        """Refresh access token if needed."""
        if self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at:
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
            
            if response.status_code != 200:
                logger.error(f"Failed to refresh Zoho token: {response.text}")
                raise Exception("Failed to refresh Zoho access token")
            
            data = response.json()
            self._access_token = data["access_token"]
            # Zoho tokens expire in 1 hour, refresh slightly before
            from datetime import timedelta
            self._token_expires_at = datetime.now() + timedelta(minutes=55)
            
            logger.info("Zoho access token refreshed")
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        api: str = "inventory",
        **kwargs
    ) -> dict:
        """Make authenticated request to Zoho API."""
        await self._ensure_access_token()
        
        base_url = self.inventory_api_url if api == "inventory" else self.books_api_url
        url = f"{base_url}{endpoint}"
        
        headers = kwargs.pop("headers", {})
        auth_headers = {
            "Authorization": f"Zoho-oauthtoken {self._access_token}",
        }
        for key, value in auth_headers.items():
            headers.setdefault(key, value)

        if "json" in kwargs and "files" not in kwargs:
            headers.setdefault("Content-Type", "application/json")
        
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
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                **kwargs
            )
            
            if response.status_code not in [200, 201]:
                logger.error(f"Zoho API error: {response.status_code} - {response.text}")
                raise Exception(f"Zoho API error: {response.text}")
            
            return response.json()
    
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
    
    async def sync_item(
        self,
        sku: str,
        name: str,
        rate: float,
        description: Optional[str] = None,
        image_path: Optional[Path] = None,
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
        
        # Check if item exists
        existing = await self.get_item_by_sku(sku)
        
        if existing:
            zoho_item = await self.update_item(existing["item_id"], item_data)
        else:
            zoho_item = await self.create_item(item_data)

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

        existing = await self.get_composite_item_by_sku(sku)
        if existing:
            return await self.update_composite_item(existing["composite_item_id"], composite_data)
        return await self.create_composite_item(composite_data)
    
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

