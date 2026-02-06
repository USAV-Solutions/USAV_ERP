"""
Bundle Component API endpoints.
Manages Bill of Materials for bundles and kits.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import IdentityType
from app.repositories import BundleComponentRepository, ProductIdentityRepository
from app.modules.inventory.schemas import (
    BundleComponentCreate,
    BundleComponentResponse,
    BundleComponentUpdate,
    BundleComponentWithDetails,
    PaginatedResponse,
)

router = APIRouter(prefix="/bundles", tags=["Bundle Components"])


@router.get("", response_model=PaginatedResponse)
async def list_bundle_components(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    parent_identity_id: Annotated[int | None, Query(description="Filter by parent bundle")] = None,
    child_identity_id: Annotated[int | None, Query(description="Filter by child component")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List bundle components with optional filtering."""
    repo = BundleComponentRepository(db)
    
    filters = {}
    if parent_identity_id is not None:
        filters["parent_identity_id"] = parent_identity_id
    if child_identity_id is not None:
        filters["child_identity_id"] = child_identity_id
    
    items = await repo.get_multi(skip=skip, limit=limit, filters=filters, order_by="id")
    total = await repo.count(filters=filters)
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[BundleComponentResponse.model_validate(item) for item in items]
    )


@router.post("", response_model=BundleComponentResponse, status_code=status.HTTP_201_CREATED)
async def create_bundle_component(
    data: BundleComponentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Add a component to a bundle.
    
    The parent must be a Bundle (B) or Kit (K) type identity.
    Self-referencing is not allowed.
    """
    bundle_repo = BundleComponentRepository(db)
    identity_repo = ProductIdentityRepository(db)
    
    # Verify parent identity exists and is a bundle/kit
    parent = await identity_repo.get(data.parent_identity_id)
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Parent identity {data.parent_identity_id} not found"
        )
    
    if parent.type not in [IdentityType.B, IdentityType.K]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parent identity must be type 'B' (Bundle) or 'K' (Kit), got '{parent.type.value}'"
        )
    
    # Verify child identity exists
    child = await identity_repo.get(data.child_identity_id)
    if not child:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Child identity {data.child_identity_id} not found"
        )
    
    # Check self-reference
    if data.parent_identity_id == data.child_identity_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A bundle cannot contain itself as a component"
        )
    
    # Check for duplicate component
    exists = await bundle_repo.component_exists(
        data.parent_identity_id,
        data.child_identity_id
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This component is already part of the bundle"
        )
    
    component = await bundle_repo.create(data.model_dump())
    return BundleComponentResponse.model_validate(component)


@router.get("/{component_id}", response_model=BundleComponentWithDetails)
async def get_bundle_component(
    component_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a bundle component by ID with parent/child details."""
    repo = BundleComponentRepository(db)
    component = await repo.get(component_id)
    
    if not component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bundle component {component_id} not found"
        )
    
    return BundleComponentWithDetails.model_validate(component)


@router.get("/parent/{parent_identity_id}/components", response_model=list[BundleComponentWithDetails])
async def get_bundle_contents(
    parent_identity_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get all components of a bundle (Bill of Materials)."""
    repo = BundleComponentRepository(db)
    components = await repo.get_bundle_components(parent_identity_id)
    
    return [BundleComponentWithDetails.model_validate(c) for c in components]


@router.get("/child/{child_identity_id}/bundles", response_model=list[BundleComponentWithDetails])
async def get_containing_bundles(
    child_identity_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get all bundles that contain a specific component."""
    repo = BundleComponentRepository(db)
    components = await repo.get_bundles_containing(child_identity_id)
    
    return [BundleComponentWithDetails.model_validate(c) for c in components]


@router.patch("/{component_id}", response_model=BundleComponentResponse)
async def update_bundle_component(
    component_id: int,
    data: BundleComponentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a bundle component (quantity or role)."""
    repo = BundleComponentRepository(db)
    component = await repo.get(component_id)
    
    if not component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bundle component {component_id} not found"
        )
    
    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        component = await repo.update(component, update_data)
    
    return BundleComponentResponse.model_validate(component)


@router.delete("/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bundle_component(
    component_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Remove a component from a bundle."""
    repo = BundleComponentRepository(db)
    
    deleted = await repo.delete(component_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bundle component {component_id} not found"
        )
