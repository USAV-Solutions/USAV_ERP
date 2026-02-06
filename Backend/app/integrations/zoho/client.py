"""
Zoho Inventory API Client.

Handles sync between USAV Inventory and Zoho Inventory/Books.
"""
from datetime import datetime
from typing import List, Optional, Any
import logging

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
        client_id: str = None,
        client_secret: str = None,
        refresh_token: str = None,
        organization_id: str = None,
    ):
        self.client_id = client_id or settings.zoho_client_id
        self.client_secret = client_secret or settings.zoho_client_secret
        self.refresh_token = refresh_token or settings.zoho_refresh_token
        self.organization_id = organization_id or settings.zoho_organization_id
        
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
                f"{self.ZOHO_ACCOUNTS_URL}/oauth/v2/token",
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
        
        base_url = self.ZOHO_INVENTORY_API if api == "inventory" else self.ZOHO_BOOKS_API
        url = f"{base_url}{endpoint}"
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {self._access_token}",
            "Content-Type": "application/json",
        }
        
        params = kwargs.pop("params", {})
        params["organization_id"] = self.organization_id
        
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
        """
        Create an item in Zoho Inventory.
        
        Args:
            item_data: Item data including name, sku, rate, etc.
            
        Returns:
            Created item data from Zoho
        """
        result = await self._request("POST", "/items", json={"item": item_data})
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
            json={"item": item_data}
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
        description: str = None,
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
            return await self.update_item(existing["item_id"], item_data)
        else:
            return await self.create_item(item_data)
    
    # =========================================================================
    # STOCK SYNC
    # =========================================================================
    
    async def update_stock(
        self,
        zoho_item_id: str,
        quantity: int,
        warehouse_id: str = None
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
            json={"inventory_adjustment": adjustment_data}
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
            json={"salesorder": order_data}
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

