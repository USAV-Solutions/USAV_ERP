"""
Product Family API endpoints.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories import ProductFamilyRepository
from app.modules.inventory.schemas import (
    PaginatedResponse,
    ProductFamilyCreate,
    ProductFamilyResponse,
    ProductFamilyUpdate,
    ProductFamilyWithIdentities,
)

router = APIRouter(prefix="/families", tags=["Product Families"])


@router.get("", response_model=PaginatedResponse)
async def list_families(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    search: Annotated[str | None, Query(description="Search by name")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all product families with optional search."""
    repo = ProductFamilyRepository(db)
    
    if search:
        items = await repo.search_by_name(search, skip=skip, limit=limit)
        # For search, we'd need a separate count query
        total = len(items)
    else:
        items = await repo.get_multi(skip=skip, limit=limit, order_by="product_id")
        total = await repo.count()
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[ProductFamilyResponse.model_validate(item) for item in items]
    )


@router.post("", response_model=ProductFamilyResponse, status_code=status.HTTP_201_CREATED)
async def create_family(
    data: ProductFamilyCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new product family."""
    repo = ProductFamilyRepository(db)
    
    # Auto-generate product_id if not provided
    product_id = data.product_id
    if product_id is None:
        # Find the next available product_id
        max_id = await repo.get_max_product_id()
        product_id = (max_id or 0) + 1
    
    # Check if product_id already exists
    existing = await repo.get(product_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product family with ID {product_id} already exists"
        )
    
    # Create with the determined product_id
    create_data = data.model_dump()
    create_data['product_id'] = product_id
    create_data['family_code'] = f"{product_id:05d}"
    family = await repo.create(create_data)
    return ProductFamilyResponse.model_validate(family)


@router.get("/{product_id}", response_model=ProductFamilyWithIdentities)
async def get_family(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a product family by ID with its identities."""
    repo = ProductFamilyRepository(db)
    family = await repo.get_with_identities(product_id)
    
    if not family:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product family {product_id} not found"
        )
    
    return ProductFamilyWithIdentities.model_validate(family)


@router.put("/{product_id}", response_model=ProductFamilyResponse)
@router.patch("/{product_id}", response_model=ProductFamilyResponse)
async def update_family(
    product_id: int,
    data: ProductFamilyUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a product family (supports both PUT and PATCH)."""
    repo = ProductFamilyRepository(db)
    family = await repo.get(product_id)
    
    if not family:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product family {product_id} not found"
        )
    
    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        family = await repo.update(family, update_data)
    
    return ProductFamilyResponse.model_validate(family)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_family(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a product family and all related data."""
    repo = ProductFamilyRepository(db)
    
    deleted = await repo.delete(product_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product family {product_id} not found"
        )
