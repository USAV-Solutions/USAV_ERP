"""
Inventory Module Routes.

All inventory-related routes.
These routes are included in the main API router.
"""
from fastapi import APIRouter

# Import from local module files
from app.modules.inventory.routes.bundles import router as bundles_router
from app.modules.inventory.routes.families import router as families_router
from app.modules.inventory.routes.identities import router as identities_router
from app.modules.inventory.routes.inventory import router as inventory_router
from app.modules.inventory.routes.listings import router as listings_router
from app.modules.inventory.routes.lookups import (
    brand_router,
    color_router,
    condition_router,
    lci_router,
)
from app.modules.inventory.routes.variants import router as variants_router

# Create a combined router for the inventory module
inventory_module_router = APIRouter()

# Include all inventory-related routes
inventory_module_router.include_router(families_router)
inventory_module_router.include_router(identities_router)
inventory_module_router.include_router(variants_router)
inventory_module_router.include_router(bundles_router)
inventory_module_router.include_router(listings_router)
inventory_module_router.include_router(inventory_router)
inventory_module_router.include_router(brand_router)
inventory_module_router.include_router(color_router)
inventory_module_router.include_router(condition_router)
inventory_module_router.include_router(lci_router)

__all__ = [
    "inventory_module_router",
    # Individual routers for backward compatibility
    "bundles_router",
    "families_router",
    "identities_router",
    "inventory_router",
    "listings_router",
    "variants_router",
    "brand_router",
    "color_router",
    "condition_router",
    "lci_router",
]

