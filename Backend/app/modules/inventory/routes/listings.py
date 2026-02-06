"""
Platform Listing API endpoints.
Manages listings for external platforms (Zoho, Amazon, eBay, etc.).
"""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Platform, PlatformSyncStatus
from app.repositories import PlatformListingRepository, ProductVariantRepository
from app.modules.inventory.schemas import (
    PaginatedResponse,
    PlatformListingCreate,
    PlatformListingResponse,
    PlatformListingUpdate,
)

router = APIRouter(prefix="/listings", tags=["Platform Listings"])


@router.get("", response_model=PaginatedResponse)
async def list_platform_listings(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    variant_id: Annotated[int | None, Query(description="Filter by variant")] = None,
    platform: Annotated[Platform | None, Query(description="Filter by platform")] = None,
    sync_status: Annotated[PlatformSyncStatus | None, Query(description="Filter by sync status")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List platform listings with optional filtering."""
    repo = PlatformListingRepository(db)
    
    filters = {}
    if variant_id is not None:
        filters["variant_id"] = variant_id
    if platform is not None:
        filters["platform"] = platform
    if sync_status is not None:
        filters["sync_status"] = sync_status
    
    items = await repo.get_multi(skip=skip, limit=limit, filters=filters, order_by="id")
    total = await repo.count(filters=filters)
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[PlatformListingResponse.model_validate(item) for item in items]
    )


@router.post("", response_model=PlatformListingResponse, status_code=status.HTTP_201_CREATED)
async def create_platform_listing(
    data: PlatformListingCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new platform listing.
    
    Only one listing per variant per platform is allowed.
    """
    listing_repo = PlatformListingRepository(db)
    variant_repo = ProductVariantRepository(db)
    
    # Verify variant exists
    variant = await variant_repo.get(data.variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {data.variant_id} not found"
        )
    
    # Check for existing listing
    existing = await listing_repo.get_by_variant_platform(data.variant_id, data.platform)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Listing for variant {data.variant_id} on {data.platform.value} already exists"
        )
    
    listing_data = data.model_dump()
    listing_data["sync_status"] = PlatformSyncStatus.PENDING
    
    listing = await listing_repo.create(listing_data)
    return PlatformListingResponse.model_validate(listing)


@router.get("/{listing_id}", response_model=PlatformListingResponse)
async def get_platform_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a platform listing by ID."""
    repo = PlatformListingRepository(db)
    listing = await repo.get(listing_id)
    
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {listing_id} not found"
        )
    
    return PlatformListingResponse.model_validate(listing)


@router.get("/platform/{platform}/ref/{external_ref_id}", response_model=PlatformListingResponse)
async def get_listing_by_external_ref(
    platform: Platform,
    external_ref_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a listing by platform and external reference ID (ASIN, eBay ID, etc.)."""
    repo = PlatformListingRepository(db)
    listing = await repo.get_by_external_ref(platform, external_ref_id)
    
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Listing with external ref '{external_ref_id}' on {platform.value} not found"
        )
    
    return PlatformListingResponse.model_validate(listing)


@router.put("/{listing_id}", response_model=PlatformListingResponse)
@router.patch("/{listing_id}", response_model=PlatformListingResponse)
async def update_platform_listing(
    listing_id: int,
    data: PlatformListingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a platform listing (supports both PUT and PATCH)."""
    repo = PlatformListingRepository(db)
    listing = await repo.get(listing_id)
    
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {listing_id} not found"
        )
    
    update_data = data.model_dump(exclude_unset=True)
    
    # If sync_status is being updated to SYNCED, update last_synced_at
    if update_data.get("sync_status") == PlatformSyncStatus.SYNCED:
        update_data["last_synced_at"] = datetime.now()
        update_data["sync_error_message"] = None
    
    if update_data:
        listing = await repo.update(listing, update_data)
    
    return PlatformListingResponse.model_validate(listing)


@router.delete("/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_platform_listing(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a platform listing."""
    repo = PlatformListingRepository(db)
    
    deleted = await repo.delete(listing_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {listing_id} not found"
        )


@router.get("/pending", response_model=list[PlatformListingResponse])
async def get_pending_sync(
    platform: Annotated[Platform | None, Query(description="Filter by platform")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    db: AsyncSession = Depends(get_db),
):
    """Get listings pending synchronization."""
    repo = PlatformListingRepository(db)
    listings = await repo.get_pending_sync(platform=platform, limit=limit)
    
    return [PlatformListingResponse.model_validate(l) for l in listings]


@router.get("/errors", response_model=list[PlatformListingResponse])
async def get_failed_sync(
    platform: Annotated[Platform | None, Query(description="Filter by platform")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    db: AsyncSession = Depends(get_db),
):
    """Get listings with sync errors."""
    repo = PlatformListingRepository(db)
    listings = await repo.get_failed_sync(platform=platform, limit=limit)
    
    return [PlatformListingResponse.model_validate(l) for l in listings]


@router.post("/{listing_id}/mark-synced", response_model=PlatformListingResponse)
async def mark_listing_synced(
    listing_id: int,
    external_ref_id: Annotated[str | None, Query(description="External reference ID from platform")] = None,
    db: AsyncSession = Depends(get_db),
):
    """Mark a listing as successfully synced."""
    repo = PlatformListingRepository(db)
    listing = await repo.get(listing_id)
    
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {listing_id} not found"
        )
    
    update_data = {
        "sync_status": PlatformSyncStatus.SYNCED,
        "last_synced_at": datetime.now(),
        "sync_error_message": None,
    }
    
    if external_ref_id:
        update_data["external_ref_id"] = external_ref_id
    
    listing = await repo.update(listing, update_data)
    return PlatformListingResponse.model_validate(listing)


@router.post("/{listing_id}/mark-error", response_model=PlatformListingResponse)
async def mark_listing_error(
    listing_id: int,
    error_message: Annotated[str, Query(description="Error message from sync attempt")],
    db: AsyncSession = Depends(get_db),
):
    """Mark a listing sync as failed with an error message."""
    repo = PlatformListingRepository(db)
    listing = await repo.get(listing_id)
    
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {listing_id} not found"
        )
    
    listing = await repo.update(listing, {
        "sync_status": PlatformSyncStatus.ERROR,
        "sync_error_message": error_message,
    })
    
    return PlatformListingResponse.model_validate(listing)
