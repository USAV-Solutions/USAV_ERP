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
from app.modules.inventory.schemas.graph import (
    AISuggestRequest,
    AISuggestResponse,
    AISuggestion,
    CompareField,
    CompareRequest,
    CompareResponse,
    GraphEdge,
    GraphTopologyResponse,
    ListingNode,
    LockRelationshipRequest,
    LockRelationshipResponse,
    ProductNode,
    RelationshipType,
    StockWarningStatus,
    PriceMismatchAlert,
    ChannelSalesMetric,
    OrbitAnalyticsResponse,
    BundleComponentInput,
    OrbitCreateBundleKitRequest,
    OrbitCreateVariantRequest,
    OrbitUpdateRelationshipRequest,
    OrbitUnlinkRequest,
    OrbitConvertTypeRequest,
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
    EbaySpecificInput,
    PlatformListingMatchRequest,
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
    ProductVariantConvertToKitRequest,
    ProductVariantConvertToKitResponse,
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
    ProductVariantWithListings,
)
from app.modules.inventory.schemas.zoho import (
    ZohoBulkSyncItemResult,
    ZohoBulkSyncRequest,
    ZohoBulkSyncResponse,
    ZohoRelinkBySkuItemResult,
    ZohoRelinkBySkuRequest,
    ZohoRelinkBySkuResponse,
    ZohoReadinessItem,
    ZohoReadinessRequest,
    ZohoReadinessResponse,
    ZohoSingleSyncRequest,
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
    # Graph & AI
    "ProductNode",
    "ListingNode",
    "GraphEdge",
    "GraphTopologyResponse",
    "RelationshipType",
    "AISuggestRequest",
    "AISuggestion",
    "AISuggestResponse",
    "LockRelationshipRequest",
    "LockRelationshipResponse",
    "CompareRequest",
    "CompareField",
    "CompareResponse",
    # Listings
    "PlatformListingCreate",
    "PlatformListingResponse",
    "PlatformListingUpdate",
    "PlatformListingMatchRequest",
    "EbaySpecificInput",
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
    "ProductVariantConvertToKitRequest",
    "ProductVariantConvertToKitResponse",
    "ProductVariantCreate",
    "ProductVariantResponse",
    "ProductVariantUpdate",
    "ProductVariantWithListings",
    # Zoho sync
    "ZohoBulkSyncItemResult",
    "ZohoBulkSyncRequest",
    "ZohoBulkSyncResponse",
    "ZohoRelinkBySkuItemResult",
    "ZohoRelinkBySkuRequest",
    "ZohoRelinkBySkuResponse",
    "ZohoReadinessItem",
    "ZohoReadinessRequest",
    "ZohoReadinessResponse",
    "ZohoSingleSyncRequest",
    "ZohoSyncProgressResponse",
]
