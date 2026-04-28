"""
Walmart Marketplace API Client.

Implements BasePlatformClient so Walmart orders can flow through
the shared OrderSyncService pipeline.
"""
import base64
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import logging
from uuid import uuid4

import httpx

from app.integrations.base import (
    BasePlatformClient,
    ExternalOrder,
    ExternalOrderItem,
    StockUpdate,
    StockUpdateResult,
)

logger = logging.getLogger(__name__)

_TOKEN_PATH = "/v3/token"
_ORDERS_PATH = "/v3/orders"
_TOKEN_EXPIRY_BUFFER_SECONDS = 30


class WalmartClient(BasePlatformClient):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        api_base_url: str = "https://marketplace.walmartapis.com",
        **kwargs,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_base_url = api_base_url.rstrip("/")
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    @property
    def platform_name(self) -> str:
        return "WALMART"

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @staticmethod
    def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    def _format_walmart_datetime(cls, dt: datetime) -> str:
        normalized = cls._to_utc(dt)
        if normalized is None:
            raise ValueError("Datetime cannot be None")
        return normalized.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    @staticmethod
    def _parse_datetime(value) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
            except (ValueError, OverflowError, OSError):
                return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _safe_float(value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value, default: int = 1) -> int:
        try:
            parsed = int(float(value))
            return parsed if parsed > 0 else default
        except (TypeError, ValueError):
            return default

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "WM_SEC.ACCESS_TOKEN": access_token,
            "WM_SVC.NAME": "Walmart Marketplace",
            "WM_QOS.CORRELATION_ID": str(uuid4()),
        }

    async def _refresh_access_token(self) -> bool:
        credentials = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        basic_token = base64.b64encode(credentials).decode("ascii")
        headers = {
            "Authorization": f"Basic {basic_token}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "WM_SVC.NAME": "Walmart Marketplace",
        }
        payload = {"grant_type": "client_credentials"}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.api_base_url}{_TOKEN_PATH}",
                    headers=headers,
                    data=payload,
                )
                response.raise_for_status()
                data = response.json()

            token_container = data.get("tokenAPIRes", {}).get("value")
            if not token_container:
                token_container = data.get("clientCredentialsRes", {}).get("value")
            if not token_container:
                token_container = data

            access_token = token_container.get("access_token")
            expires_in = int(token_container.get("expires_in", 900))
            if not access_token:
                logger.error("Walmart token response did not include access_token")
                return False

            self._access_token = access_token
            self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            return True
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.error("Walmart token request failed: %s", exc)
            self._access_token = None
            self._token_expires_at = None
            return False

    async def _get_access_token(self) -> Optional[str]:
        now = datetime.now(timezone.utc)
        if (
            self._access_token
            and self._token_expires_at
            and now < (self._token_expires_at - timedelta(seconds=_TOKEN_EXPIRY_BUFFER_SECONDS))
        ):
            return self._access_token

        if not await self._refresh_access_token():
            return None
        return self._access_token

    def _parse_order_line(self, line: dict) -> ExternalOrderItem:
        item_data = line.get("item", {})
        qty = self._safe_int(line.get("orderLineQuantity", {}).get("amount"), default=1)

        line_total = 0.0
        for charge in line.get("charges", {}).get("charge", []) or []:
            line_total += self._safe_float(
                charge.get("chargeAmount", {}).get("amount"),
            )
        unit_price = line_total / qty if qty > 0 else line_total

        return ExternalOrderItem(
            platform_item_id=str(line.get("lineNumber") or "") or None,
            platform_sku=item_data.get("sku"),
            asin=None,
            title=item_data.get("productName") or "Unknown Item",
            quantity=qty,
            unit_price=unit_price,
            total_price=line_total,
            raw_data=line,
        )

    def _parse_walmart_order(self, order_data: dict) -> ExternalOrder:
        shipping_info = order_data.get("shippingInfo", {})
        shipping_address = shipping_info.get("postalAddress", {})
        lines = order_data.get("orderLines", {}).get("orderLine", []) or []

        items = [self._parse_order_line(line) for line in lines]

        subtotal = sum(item.total_price for item in items)
        tax = 0.0
        shipping = 0.0
        currency = "USD"
        for line in lines:
            for charge in line.get("charges", {}).get("charge", []) or []:
                charge_type = str(charge.get("chargeType") or "").upper()
                tax += self._safe_float(charge.get("tax", {}).get("taxAmount", {}).get("amount"))
                currency = charge.get("chargeAmount", {}).get("currency") or currency
                if charge_type == "SHIPPING":
                    shipping += self._safe_float(charge.get("chargeAmount", {}).get("amount"))

        total = subtotal + tax
        if shipping:
            total += shipping

        purchase_order_id = order_data.get("purchaseOrderId")
        customer_order_id = order_data.get("customerOrderId")

        return ExternalOrder(
            platform_order_id=str(purchase_order_id or customer_order_id or ""),
            platform_order_number=str(customer_order_id or purchase_order_id or ""),
            customer_name=shipping_address.get("name"),
            customer_email=order_data.get("customerEmailId"),
            customer_phone=shipping_info.get("phone"),
            customer_company=shipping_address.get("companyName") or shipping_address.get("company"),
            customer_source="WALMART_API",
            ship_address_line1=shipping_address.get("address1"),
            ship_address_line2=shipping_address.get("address2"),
            ship_city=shipping_address.get("city"),
            ship_state=shipping_address.get("state"),
            ship_postal_code=shipping_address.get("postalCode"),
            ship_country=shipping_address.get("country") or "US",
            subtotal=subtotal,
            tax=tax,
            shipping=shipping,
            total=total,
            currency=currency,
            ordered_at=self._parse_datetime(order_data.get("orderDate")),
            items=items,
            raw_data=order_data,
        )

    async def authenticate(self) -> bool:
        if not self.is_configured:
            logger.warning("Walmart credentials are not configured")
            return False
        return await self._refresh_access_token()

    async def fetch_orders(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> List[ExternalOrder]:
        """Fetch orders from Walmart Marketplace Orders API."""
        if not self.is_configured:
            message = "Walmart credentials are not configured"
            logger.error(message)
            raise RuntimeError(message)

        access_token = await self._get_access_token()
        if not access_token:
            raise RuntimeError("Walmart unable to obtain access token")

        params: dict[str, str | int] = {
            "limit": 100,
            "productInfo": "false",
            "incentiveInfo": "false",
            "replacementInfo": "false",
        }
        if since:
            params["createdStartDate"] = self._format_walmart_datetime(since)
        if until:
            params["createdEndDate"] = self._format_walmart_datetime(until)
        if status:
            params["status"] = status

        logger.debug(
            "[DEBUG.EXTERNAL_API] Walmart fetch_orders called | since=%s until=%s status=%s",
            since,
            until,
            status,
        )

        orders: list[ExternalOrder] = []
        next_path: Optional[str] = _ORDERS_PATH
        request_params: Optional[dict[str, str | int]] = params
        page_count = 0

        async with httpx.AsyncClient(base_url=self.api_base_url, timeout=30.0) as client:
            while next_path and page_count < 100:
                page_count += 1
                response = await client.get(
                    next_path,
                    headers=self._auth_headers(access_token),
                    params=request_params,
                )
                response.raise_for_status()
                payload = response.json()

                page_orders = payload.get("list", {}).get("elements", {}).get("order", []) or []
                orders.extend(self._parse_walmart_order(order_data) for order_data in page_orders)

                next_cursor = payload.get("list", {}).get("meta", {}).get("nextCursor")
                if not next_cursor:
                    break
                next_path = f"{_ORDERS_PATH}{next_cursor}" if str(next_cursor).startswith("?") else str(next_cursor)
                request_params = None

        logger.info("Fetched %d orders from Walmart", len(orders))
        return orders

    async def get_order(self, order_id: str) -> Optional[ExternalOrder]:
        if not self.is_configured:
            return None

        access_token = await self._get_access_token()
        if not access_token:
            logger.error("Walmart get_order failed: unable to obtain access token")
            return None

        logger.debug("[DEBUG.EXTERNAL_API] Walmart get_order called | order_id=%s", order_id)
        try:
            async with httpx.AsyncClient(base_url=self.api_base_url, timeout=20.0) as client:
                response = await client.get(
                    f"{_ORDERS_PATH}/{order_id}",
                    headers=self._auth_headers(access_token),
                )
                response.raise_for_status()
                payload = response.json()

            order_payload = payload.get("order")
            if order_payload is None:
                list_orders = payload.get("list", {}).get("elements", {}).get("order", []) or []
                order_payload = list_orders[0] if list_orders else None
            if order_payload is None:
                return None

            return self._parse_walmart_order(order_payload)
        except httpx.HTTPError as exc:
            logger.error("Walmart get_order failed for %s: %s", order_id, exc)
            return None

    async def update_stock(self, updates: List[StockUpdate]) -> List[StockUpdateResult]:
        _ = updates
        return []

    async def update_tracking(
        self,
        order_id: str,
        tracking_number: str,
        carrier: str,
    ) -> bool:
        _ = (order_id, tracking_number, carrier)
        return False
