"""
Inventory and listing repositories.
Handles database operations for BundleComponent, PlatformListing, and InventoryItem.
"""
from typing import Any, Optional, Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BundleComponent,
    InventoryItem,
    InventoryStatus,
    Platform,
    PlatformListing,
    PlatformSyncStatus,
    ProductVariant,
)
from app.repositories.base import BaseRepository


class BundleComponentRepository(BaseRepository[BundleComponent]):
    """Repository for BundleComponent (Bill of Materials) operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(BundleComponent, session)
    
    async def get_bundle_components(
        self,
        parent_identity_id: int
    ) -> Sequence[BundleComponent]:
        """Get all components of a bundle."""
        stmt = (
            select(BundleComponent)
            .options(
                selectinload(BundleComponent.child),
                selectinload(BundleComponent.parent)
            )
            .where(BundleComponent.parent_identity_id == parent_identity_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_bundles_containing(
        self,
        child_identity_id: int
    ) -> Sequence[BundleComponent]:
        """Get all bundles that contain a specific component."""
        stmt = (
            select(BundleComponent)
            .options(
                selectinload(BundleComponent.parent),
                selectinload(BundleComponent.child)
            )
            .where(BundleComponent.child_identity_id == child_identity_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def component_exists(
        self,
        parent_identity_id: int,
        child_identity_id: int
    ) -> bool:
        """Check if a component relationship already exists."""
        stmt = (
            select(func.count())
            .select_from(BundleComponent)
            .where(BundleComponent.parent_identity_id == parent_identity_id)
            .where(BundleComponent.child_identity_id == child_identity_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() > 0


class PlatformListingRepository(BaseRepository[PlatformListing]):
    """Repository for PlatformListing operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(PlatformListing, session)
    
    async def get_by_variant_platform(
        self,
        variant_id: int,
        platform: Platform
    ) -> Optional[PlatformListing]:
        """Get listing for a specific variant on a platform."""
        stmt = (
            select(PlatformListing)
            .where(PlatformListing.variant_id == variant_id)
            .where(PlatformListing.platform == platform)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_external_ref(
        self,
        platform: Platform,
        external_ref_id: str
    ) -> Optional[PlatformListing]:
        """Get listing by external reference ID (ASIN, eBay Item ID, etc.)."""
        stmt = (
            select(PlatformListing)
            .where(PlatformListing.platform == platform)
            .where(PlatformListing.external_ref_id == external_ref_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_external_ref(
        self,
        platform: Platform,
        external_ref_id: str,
    ) -> Optional[PlatformListing]:
        """Get listing by external ref, restricted to active variants.

        This is intended for order auto-match flows so archived variants are not
        re-matched from legacy listing rows.
        """
        stmt = (
            select(PlatformListing)
            .join(ProductVariant, ProductVariant.id == PlatformListing.variant_id)
            .where(PlatformListing.platform == platform)
            .where(PlatformListing.external_ref_id == external_ref_id)
            .where(ProductVariant.is_active == True)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_pending_sync(
        self,
        platform: Optional[Platform] = None,
        limit: int = 100
    ) -> Sequence[PlatformListing]:
        """Get listings pending synchronization."""
        stmt = (
            select(PlatformListing)
            .where(PlatformListing.sync_status == PlatformSyncStatus.PENDING)
        )
        
        if platform:
            stmt = stmt.where(PlatformListing.platform == platform)
        
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_failed_sync(
        self,
        platform: Optional[Platform] = None,
        limit: int = 100
    ) -> Sequence[PlatformListing]:
        """Get listings with sync errors."""
        stmt = (
            select(PlatformListing)
            .where(PlatformListing.sync_status == PlatformSyncStatus.ERROR)
        )
        
        if platform:
            stmt = stmt.where(PlatformListing.platform == platform)
        
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_variant_listings(
        self,
        variant_id: int
    ) -> Sequence[PlatformListing]:
        """Get all platform listings for a variant."""
        stmt = (
            select(PlatformListing)
            .where(PlatformListing.variant_id == variant_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def search_by_listed_name(
        self,
        platform: Platform,
        name: str,
    ) -> Optional[PlatformListing]:
        """Fuzzy-match a listing by its listed_name on a given platform.

        Used as a fallback in the auto-match algorithm when external_ref_id
        and platform_sku lookups fail.  Performs a case-insensitive ILIKE
        search and returns the first match (or None).
        """
        pattern = f"%{name}%"
        stmt = (
            select(PlatformListing)
            .where(PlatformListing.platform == platform)
            .where(PlatformListing.listed_name.ilike(pattern))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search_active_by_listed_name(
        self,
        platform: Platform,
        name: str,
    ) -> Optional[PlatformListing]:
        """Fuzzy-match listing name, restricted to active variants."""
        pattern = f"%{name}%"
        stmt = (
            select(PlatformListing)
            .join(ProductVariant, ProductVariant.id == PlatformListing.variant_id)
            .where(PlatformListing.platform == platform)
            .where(PlatformListing.listed_name.ilike(pattern))
            .where(ProductVariant.is_active == True)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class InventoryItemRepository(BaseRepository[InventoryItem]):
    """Repository for InventoryItem operations."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(InventoryItem, session)
    
    async def get_by_serial(self, serial_number: str) -> Optional[InventoryItem]:
        """Get inventory item by serial number."""
        return await self.get_by_field("serial_number", serial_number)
    
    async def get_by_variant(
        self,
        variant_id: int,
        status: Optional[InventoryStatus] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[InventoryItem]:
        """Get inventory items for a variant, optionally filtered by status."""
        stmt = (
            select(InventoryItem)
            .where(InventoryItem.variant_id == variant_id)
        )
        
        if status:
            stmt = stmt.where(InventoryItem.status == status)
        
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_available(
        self,
        variant_id: int,
        limit: int = 100
    ) -> Sequence[InventoryItem]:
        """Get available inventory items for a variant."""
        return await self.get_by_variant(
            variant_id,
            status=InventoryStatus.AVAILABLE,
            limit=limit
        )
    
    async def count_by_status(
        self,
        variant_id: int
    ) -> dict[str, int]:
        """Get inventory counts grouped by status for a variant."""
        stmt = (
            select(
                InventoryItem.status,
                func.count(InventoryItem.id).label("count")
            )
            .where(InventoryItem.variant_id == variant_id)
            .group_by(InventoryItem.status)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        
        # Initialize all statuses to 0
        counts = {status.value: 0 for status in InventoryStatus}
        
        # Update with actual counts
        for row in rows:
            counts[row.status.value] = row.count
        
        # Add total
        counts["total"] = sum(counts.values())
        
        return counts
    
    async def get_by_location(
        self,
        location_code: str,
        status: Optional[InventoryStatus] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[InventoryItem]:
        """Get inventory items at a specific location."""
        stmt = (
            select(InventoryItem)
            .where(InventoryItem.location_code == location_code)
        )
        
        if status:
            stmt = stmt.where(InventoryItem.status == status)
        
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def reserve_item(self, item_id: int) -> Optional[InventoryItem]:
        """Reserve an available item (atomic operation)."""
        item = await self.get(item_id)
        
        if item and item.status == InventoryStatus.AVAILABLE:
            item.status = InventoryStatus.RESERVED
            await self.session.flush()
            await self.session.refresh(item)
            return item
        
        return None
    
    async def sell_item(
        self,
        item_id: int,
        sold_at: Optional[Any] = None
    ) -> Optional[InventoryItem]:
        """Mark an item as sold."""
        from datetime import datetime
        
        item = await self.get(item_id)
        
        if item and item.status in [InventoryStatus.AVAILABLE, InventoryStatus.RESERVED]:
            item.status = InventoryStatus.SOLD
            item.sold_at = sold_at or datetime.now()
            await self.session.flush()
            await self.session.refresh(item)
            return item
        
        return None
    
    async def get_total_value(
        self,
        variant_id: Optional[int] = None,
        status: Optional[InventoryStatus] = None
    ) -> float:
        """Calculate total cost basis of inventory."""
        stmt = select(func.sum(InventoryItem.cost_basis))
        
        if variant_id:
            stmt = stmt.where(InventoryItem.variant_id == variant_id)
        
        if status:
            stmt = stmt.where(InventoryItem.status == status)
        
        result = await self.session.execute(stmt)
        total = result.scalar_one_or_none()
        return float(total) if total else 0.0


__all__ = [
    "BundleComponentRepository",
    "PlatformListingRepository",
    "InventoryItemRepository",
]
