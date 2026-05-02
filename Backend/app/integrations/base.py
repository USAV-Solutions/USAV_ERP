"""
Base Platform Integration Interface.

Defines the abstract base class that all platform integrations must implement.
This ensures consistent interfaces across different external platforms.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional, List
from dataclasses import dataclass


@dataclass
class ExternalOrder:
    """
    Normalized order data from external platforms.
    
    All platform-specific adapters convert their order format to this common structure.
    """
    platform_order_id: str
    platform_order_number: Optional[str]
    
    # Customer
    customer_name: Optional[str]
    customer_email: Optional[str]
    
    # Shipping
    ship_address_line1: Optional[str]
    ship_address_line2: Optional[str]
    ship_address_line3: Optional[str]
    ship_city: Optional[str]
    ship_state: Optional[str]
    ship_postal_code: Optional[str]
    ship_country: Optional[str]
    
    # Financial
    subtotal: float
    tax: float
    shipping: float
    total: float
    currency: str
    
    # Timestamps
    ordered_at: Optional[datetime]
    
    # Items
    items: List["ExternalOrderItem"]
    
    # Raw data
    raw_data: Optional[dict] = None
    customer_phone: Optional[str] = None
    customer_company: Optional[str] = None
    customer_source: Optional[str] = None
    tracking_number: Optional[str] = None


@dataclass 
class ExternalOrderItem:
    """
    Normalized order item from external platforms.
    """
    platform_item_id: Optional[str]
    platform_sku: Optional[str]
    asin: Optional[str]  # Amazon-specific
    
    title: str
    quantity: int
    unit_price: float
    total_price: float
    
    # Raw item data
    raw_data: Optional[dict] = None


@dataclass
class StockUpdate:
    """
    Stock level update to push to external platforms.
    """
    sku: str
    quantity: int
    external_ref_id: Optional[str] = None  # Platform's item ID


@dataclass
class StockUpdateResult:
    """
    Result of a stock update operation.
    """
    sku: str
    success: bool
    message: Optional[str] = None
    external_ref_id: Optional[str] = None


class BasePlatformClient(ABC):
    """
    Abstract base class for all platform integrations.
    
    Each platform (Amazon, eBay, Zoho) must implement this interface
    to ensure consistent behavior across the system.
    """
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier (AMAZON, EBAY_MEKONG, etc.)."""
        pass
    
    @abstractmethod
    async def authenticate(self) -> bool:
        """
        Authenticate with the platform.
        
        Returns:
            True if authentication successful, False otherwise.
        """
        pass
    
    @abstractmethod
    async def fetch_orders(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> List[ExternalOrder]:
        """
        Fetch orders from the platform.
        
        Args:
            since: Fetch orders created after this time
            until: Fetch orders created before this time
            status: Filter by order status (platform-specific)
            
        Returns:
            List of normalized ExternalOrder objects
        """
        pass
    
    @abstractmethod
    async def get_order(self, order_id: str) -> Optional[ExternalOrder]:
        """
        Get a specific order by ID.
        
        Args:
            order_id: Platform's order ID
            
        Returns:
            ExternalOrder if found, None otherwise
        """
        pass
    
    @abstractmethod
    async def update_stock(self, updates: List[StockUpdate]) -> List[StockUpdateResult]:
        """
        Push stock level updates to the platform.
        
        Args:
            updates: List of SKUs and quantities to update
            
        Returns:
            List of results for each update
        """
        pass
    
    @abstractmethod
    async def update_tracking(
        self,
        order_id: str,
        tracking_number: str,
        carrier: str
    ) -> bool:
        """
        Update shipment tracking information on the platform.
        
        Args:
            order_id: Platform's order ID
            tracking_number: Shipment tracking number
            carrier: Shipping carrier name
            
        Returns:
            True if update successful, False otherwise
        """
        pass
    
    async def health_check(self) -> bool:
        """
        Check if the platform API is accessible.
        
        Returns:
            True if API is healthy, False otherwise
        """
        try:
            return await self.authenticate()
        except Exception:
            return False


class PlatformClientFactory:
    """
    Factory for creating platform client instances.
    
    Usage:
        factory = PlatformClientFactory()
        factory.register("AMAZON", AmazonClient)
        
        client = factory.create("AMAZON", config)
    """
    
    _clients: dict[str, type[BasePlatformClient]] = {}
    
    @classmethod
    def register(cls, platform: str, client_class: type[BasePlatformClient]):
        """Register a client class for a platform."""
        cls._clients[platform] = client_class
    
    @classmethod
    def create(cls, platform: str, **config) -> BasePlatformClient:
        """Create a client instance for a platform."""
        if platform not in cls._clients:
            raise ValueError(f"Unknown platform: {platform}")
        
        return cls._clients[platform](**config)
    
    @classmethod
    def get_registered_platforms(cls) -> List[str]:
        """Get list of registered platforms."""
        return list(cls._clients.keys())
