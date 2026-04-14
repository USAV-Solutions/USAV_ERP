"""
External Integrations Module.

This package contains adapters for external platforms:
- Amazon (SP-API)
- eBay (Trading API)
- Ecwid (Ecwid REST API)
- Zoho (Inventory/Books API)

Each adapter implements ``BasePlatformClient`` and normalises external data
into the shared ``ExternalOrder`` / ``ExternalOrderItem`` dataclasses defined
in ``base.py``.
"""
from app.integrations.base import (
    BasePlatformClient,
    ExternalOrder,
    ExternalOrderItem,
    PlatformClientFactory,
    StockUpdate,
    StockUpdateResult,
)
from app.integrations.amazon.client import AmazonClient
from app.integrations.ebay.client import EbayClient
from app.integrations.ecwid.client import EcwidClient
from app.integrations.walmart.client import WalmartClient

# Register all known adapters with the factory
PlatformClientFactory.register("AMAZON", AmazonClient)
PlatformClientFactory.register("EBAY_MEKONG", EbayClient)
PlatformClientFactory.register("EBAY_USAV", EbayClient)
PlatformClientFactory.register("EBAY_DRAGON", EbayClient)
PlatformClientFactory.register("ECWID", EcwidClient)
PlatformClientFactory.register("WALMART", WalmartClient)

__all__ = [
    "BasePlatformClient",
    "ExternalOrder",
    "ExternalOrderItem",
    "PlatformClientFactory",
    "StockUpdate",
    "StockUpdateResult",
    "AmazonClient",
    "EbayClient",
    "EcwidClient",
    "WalmartClient",
]
