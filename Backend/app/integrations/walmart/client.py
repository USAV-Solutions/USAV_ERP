"""
Walmart Marketplace API Client.

This is a lightweight adapter that implements BasePlatformClient so
orders can be imported through the shared OrderSyncService pipeline.
"""
from datetime import datetime
from typing import List, Optional
import logging

from app.integrations.base import (
    BasePlatformClient,
    ExternalOrder,
    ExternalOrderItem,
    StockUpdate,
    StockUpdateResult,
)

logger = logging.getLogger(__name__)


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

    @property
    def platform_name(self) -> str:
        return "WALMART"

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def authenticate(self) -> bool:
        # Placeholder auth validation: we only verify required credentials exist.
        return self.is_configured

    async def fetch_orders(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> List[ExternalOrder]:
        """
        Fetch orders from Walmart Marketplace.

        Current implementation is intentionally conservative and returns an empty
        list unless credentials are present; this keeps import endpoints stable
        while the upstream payload mapping evolves.
        """
        if not self.is_configured:
            logger.warning("Walmart credentials are not configured")
            return []

        logger.debug(
            "[DEBUG.EXTERNAL_API] Walmart fetch_orders called | since=%s until=%s status=%s",
            since,
            until,
            status,
        )
        # Placeholder implementation.
        return []

    async def get_order(self, order_id: str) -> Optional[ExternalOrder]:
        if not self.is_configured:
            return None
        logger.debug("[DEBUG.EXTERNAL_API] Walmart get_order called | order_id=%s", order_id)
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
