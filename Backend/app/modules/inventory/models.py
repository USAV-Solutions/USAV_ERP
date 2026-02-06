"""
Inventory Module Models.

Re-exports all inventory-related models from the central entities module.
This allows the modules to have their own model namespace while maintaining
backward compatibility with existing imports.
"""
from app.models.entities import (
    # Enums
    IdentityType,
    PhysicalClass,
    ConditionCode,
    ZohoSyncStatus,
    PlatformSyncStatus,
    InventoryStatus,
    BundleRole,
    Platform,
    # Lookup Tables
    Brand,
    Color,
    Condition,
    LCIDefinition,
    # Core Models
    ProductFamily,
    ProductIdentity,
    ProductVariant,
    BundleComponent,
    PlatformListing,
    InventoryItem,
    # Mixins
    TimestampMixin,
)

__all__ = [
    # Enums
    "IdentityType",
    "PhysicalClass",
    "ConditionCode",
    "ZohoSyncStatus",
    "PlatformSyncStatus",
    "InventoryStatus",
    "BundleRole",
    "Platform",
    # Lookup Tables
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
    # Mixins
    "TimestampMixin",
]

