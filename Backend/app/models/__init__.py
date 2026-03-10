"""Models module - Export all SQLAlchemy models."""
try:
    from app.models.entities import (
        Base,
        Brand,
        BundleComponent,
        BundleRole,
        Color,
        Condition,
        ConditionCode,
        Customer,
        IdentityType,
        InventoryItem,
        InventoryStatus,
        LCIDefinition,
        PhysicalClass,
        Platform,
        PlatformListing,
        PlatformSyncStatus,
        ProductFamily,
        ProductIdentity,
        ProductVariant,
        ZohoSyncMixin,
        ZohoSyncStatus,
    )
except ImportError as e:
    print(f"Failed to import from entities: {e}")
    raise

try:
    from app.models.user import User, UserRole
except ImportError as e:
    print(f"Failed to import from user: {e}")
    raise

try:
    from app.modules.orders.models import (
        IntegrationState,
        IntegrationSyncStatus,
        Order,
        OrderItem,
        OrderPlatform,
        OrderStatus,
        OrderItemStatus,
    )
except ImportError as e:
    print(f"Failed to import from orders: {e}")
    raise

try:
    from app.models.purchasing import (
        PurchaseDeliverStatus,
        PurchaseOrder,
        PurchaseOrderItem,
        PurchaseOrderItemStatus,
        Vendor,
    )
except ImportError as e:
    print(f"Failed to import from purchasing: {e}")
    raise

__all__ = [
    # Base
    "Base",
    # Enums
    "IdentityType",
    "PhysicalClass",
    "ConditionCode",
    "ZohoSyncStatus",
    "PlatformSyncStatus",
    "InventoryStatus",
    "BundleRole",
    "Platform",
    "UserRole",
    # Mixins
    "ZohoSyncMixin",
    # Lookup Models
    "Brand",
    "Color",
    "Condition",
    "LCIDefinition",
    # Core Models
    "ProductFamily",
    "ProductIdentity",
    "ProductVariant",
    "BundleComponent",
    "PlatformListing",
    "InventoryItem",
    "Customer",
    "User",
    # Order Models
    "IntegrationState",
    "IntegrationSyncStatus",
    "Order",
    "OrderItem",
    "OrderPlatform",
    "OrderStatus",
    "OrderItemStatus",
    # Purchasing Models
    "PurchaseDeliverStatus",
    "PurchaseOrderItemStatus",
    "Vendor",
    "PurchaseOrder",
    "PurchaseOrderItem",
]
