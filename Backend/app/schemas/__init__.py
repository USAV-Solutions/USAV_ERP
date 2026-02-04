"""
Pydantic schemas for all API endpoints.
"""
from app.schemas.auth import (
    PasswordChange,
    SeaTalkAppTokenResponse,
    SeaTalkCallbackRequest,
    SeaTalkCodeResponse,
    SeaTalkEmployee,
    Token,
    TokenData,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.schemas.bundles import (
    BundleComponentCreate,
    BundleComponentResponse,
    BundleComponentUpdate,
    BundleComponentWithDetails,
)
from app.schemas.families import (
    ProductFamilyCreate,
    ProductFamilyResponse,
    ProductFamilyUpdate,
    ProductFamilyWithIdentities,
)
from app.schemas.identities import (
    ProductIdentityCreate,
    ProductIdentityResponse,
    ProductIdentityUpdate,
    ProductIdentityWithVariants,
)
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    InventoryItemWithVariant,
    InventorySummary,
    InventoryReceiveRequest,
    InventoryReceiveResponse,
    InventoryMoveRequest,
    InventoryMoveResponse,
    InventoryAuditItem,
    InventoryAuditResponse,
)
from app.schemas.listings import (
    PlatformListingCreate,
    PlatformListingResponse,
    PlatformListingUpdate,
)
from app.schemas.lookups import (
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
from app.schemas.pagination import PaginatedResponse
from app.schemas.variants import (
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
    ProductVariantWithListings,
)

__all__ = [
    # Auth
    "PasswordChange",
    "Token",
    "TokenData",
    "UserCreate",
    "UserResponse",
    "UserUpdate",
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
    "InventoryItemCreate",
    "InventoryItemResponse",
    "InventoryItemUpdate",
    "InventoryItemWithVariant",
    "InventorySummary",
    "InventoryReceiveRequest",
    "InventoryReceiveResponse",
    "InventoryMoveRequest",
    "InventoryMoveResponse",
    "InventoryAuditItem",
    "InventoryAuditResponse",
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
]
