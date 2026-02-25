"""
Inventory Module Schemas.

All inventory-related Pydantic schemas.
"""
from app.modules.inventory.schemas.bundles import (
    BundleComponentCreate,
    BundleComponentResponse,
    BundleComponentUpdate,
    BundleComponentWithDetails,
)
from app.modules.inventory.schemas.families import (
    ProductFamilyCreate,
    ProductFamilyResponse,
    ProductFamilyUpdate,
    ProductFamilyWithIdentities,
)
from app.modules.inventory.schemas.identities import (
    ProductIdentityCreate,
    ProductIdentityResponse,
    ProductIdentityUpdate,
    ProductIdentityWithVariants,
)
from app.modules.inventory.schemas.inventory import (
    InventoryAuditItem,
    InventoryAuditResponse,
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    InventoryItemWithVariant,
    InventoryMoveRequest,
    InventoryMoveResponse,
    InventoryReceiveRequest,
    InventoryReceiveResponse,
    InventorySummary,
)
from app.modules.inventory.schemas.listings import (
    PlatformListingCreate,
    PlatformListingResponse,
    PlatformListingUpdate,
)
from app.modules.inventory.schemas.lookups import (
    BrandCreate,
    BrandResponse,
    BrandUpdate,
    ColorCreate,
    ColorResponse,
    ColorUpdate,
    ConditionCreate,
    ConditionResponse,
    ConditionUpdate,
    LCIDefinitionCreate,
    LCIDefinitionResponse,
    LCIDefinitionUpdate,
)
from app.modules.inventory.schemas.pagination import PaginatedResponse
from app.modules.inventory.schemas.variants import (
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
    ProductVariantWithListings,
)
from app.modules.inventory.schemas.zoho import (
    ZohoBulkSyncItemResult,
    ZohoBulkSyncRequest,
    ZohoBulkSyncResponse,
    ZohoReadinessItem,
    ZohoReadinessRequest,
    ZohoReadinessResponse,
    ZohoSyncProgressResponse,
)

__all__ = [
    # Bundles
    "BundleComponentCreate",
    "BundleComponentResponse",
    "BundleComponentUpdate",
    "BundleComponentWithDetails",
    # Families
    "ProductFamilyCreate",
    "ProductFamilyResponse",
    "ProductFamilyUpdate",
    "ProductFamilyWithIdentities",
    # Identities
    "ProductIdentityCreate",
    "ProductIdentityResponse",
    "ProductIdentityUpdate",
    "ProductIdentityWithVariants",
    # Inventory
    "InventoryAuditItem",
    "InventoryAuditResponse",
    "InventoryItemCreate",
    "InventoryItemResponse",
    "InventoryItemUpdate",
    "InventoryItemWithVariant",
    "InventoryMoveRequest",
    "InventoryMoveResponse",
    "InventoryReceiveRequest",
    "InventoryReceiveResponse",
    "InventorySummary",
    # Listings
    "PlatformListingCreate",
    "PlatformListingResponse",
    "PlatformListingUpdate",
    # Lookups
    "BrandCreate",
    "BrandResponse",
    "BrandUpdate",
    "ColorCreate",
    "ColorResponse",
    "ColorUpdate",
    "ConditionCreate",
    "ConditionResponse",
    "ConditionUpdate",
    "LCIDefinitionCreate",
    "LCIDefinitionResponse",
    "LCIDefinitionUpdate",
    # Pagination
    "PaginatedResponse",
    # Variants
    "ProductVariantCreate",
    "ProductVariantResponse",
    "ProductVariantUpdate",
    "ProductVariantWithListings",
    # Zoho sync
    "ZohoBulkSyncItemResult",
    "ZohoBulkSyncRequest",
    "ZohoBulkSyncResponse",
    "ZohoReadinessItem",
    "ZohoReadinessRequest",
    "ZohoReadinessResponse",
    "ZohoSyncProgressResponse",
]

