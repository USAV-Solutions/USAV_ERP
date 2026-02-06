"""
Product Identity API endpoints.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import IdentityType
from app.repositories import ProductFamilyRepository, ProductIdentityRepository
from app.modules.inventory.schemas import (
    PaginatedResponse,
    ProductIdentityCreate,
    ProductIdentityResponse,
    ProductIdentityUpdate,
    ProductIdentityWithVariants,
)

router = APIRouter(prefix="/identities", tags=["Product Identities"])


@router.get("", response_model=PaginatedResponse)
async def list_identities(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    product_id: Annotated[int | None, Query(description="Filter by product family")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List product identities with optional filtering."""
    repo = ProductIdentityRepository(db)
    
    filters = {}
    if product_id is not None:
        filters["product_id"] = product_id
    
    items = await repo.get_multi(skip=skip, limit=limit, filters=filters, order_by="id")
    total = await repo.count(filters=filters)
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[ProductIdentityResponse.model_validate(item) for item in items]
    )


@router.post("", response_model=ProductIdentityResponse, status_code=status.HTTP_201_CREATED)
async def create_identity(
    data: ProductIdentityCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new product identity.
    
    The UPIS-H string and hex signature are auto-generated.
    For type 'P' (Part), LCI is required.
    For other types, LCI must be NULL.
    """
    identity_repo = ProductIdentityRepository(db)
    family_repo = ProductFamilyRepository(db)
    
    # Verify product family exists
    family = await family_repo.get(data.product_id)
    if not family:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product family {data.product_id} not found"
        )
    
    # Validate LCI based on type
    if data.type == IdentityType.P:
        if data.lci is None:
            # Auto-assign next LCI
            data.lci = await identity_repo.get_next_lci(data.product_id)
    else:
        if data.lci is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"LCI must be NULL for type '{data.type.value}'"
            )
    
    # Check for duplicate UPIS-H
    upis_h = identity_repo.generate_upis_h(data.product_id, data.type, data.lci)
    existing = await identity_repo.get_by_upis_h(upis_h)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Identity '{upis_h}' already exists"
        )
    
    identity = await identity_repo.create_identity(data.model_dump())
    return ProductIdentityResponse.model_validate(identity)


@router.get("/{identity_id}", response_model=ProductIdentityWithVariants)
async def get_identity(
    identity_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a product identity by ID with its variants."""
    repo = ProductIdentityRepository(db)
    identity = await repo.get_with_variants(identity_id)
    
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product identity {identity_id} not found"
        )
    
    return ProductIdentityWithVariants.model_validate(identity)


@router.get("/upis/{upis_h}", response_model=ProductIdentityResponse)
async def get_identity_by_upis(
    upis_h: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a product identity by UPIS-H string."""
    repo = ProductIdentityRepository(db)
    identity = await repo.get_by_upis_h(upis_h)
    
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product identity '{upis_h}' not found"
        )
    
    return ProductIdentityResponse.model_validate(identity)


@router.put("/{identity_id}", response_model=ProductIdentityResponse)
@router.patch("/{identity_id}", response_model=ProductIdentityResponse)
async def update_identity(
    identity_id: int,
    data: ProductIdentityUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update a product identity (supports both PUT and PATCH).
    
    Note: Only physical_class can be updated. The UPIS-H and hex signature
    are immutable after creation.
    """
    repo = ProductIdentityRepository(db)
    identity = await repo.get(identity_id)
    
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product identity {identity_id} not found"
        )
    
    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        identity = await repo.update(identity, update_data)
    
    return ProductIdentityResponse.model_validate(identity)


@router.delete("/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_identity(
    identity_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a product identity and all related data."""
    repo = ProductIdentityRepository(db)
    
    deleted = await repo.delete(identity_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product identity {identity_id} not found"
        )
