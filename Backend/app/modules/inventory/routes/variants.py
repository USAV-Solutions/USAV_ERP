"""
Product Variant API endpoints.
"""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import ZohoSyncStatus
from sqlalchemy import func, select

from app.models.entities import ProductFamily, ProductIdentity, ProductVariant
from app.repositories import ProductIdentityRepository, ProductVariantRepository
from app.modules.inventory.schemas import (
    PaginatedResponse,
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
    ProductVariantWithListings,
)

router = APIRouter(prefix="/variants", tags=["Product Variants"])


async def _build_unique_deleted_sku(
    repo: ProductVariantRepository,
    original_sku: str,
    variant_id: int,
) -> str:
    """Build a unique soft-delete SKU with a D- prefix."""
    base = f"D-{original_sku}"
    candidate = base
    existing = await repo.get_by_sku(candidate)
    if existing is None or existing.id == variant_id:
        return candidate

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    candidate = f"{base}-{variant_id}-{timestamp}"
    existing = await repo.get_by_sku(candidate)
    if existing is None or existing.id == variant_id:
        return candidate

    # Final fallback to keep moving even in edge-collision scenarios.
    return f"{base}-{variant_id}-{datetime.utcnow().microsecond}"


@router.get("/search", summary="Search variants by product name or SKU")
async def search_variants(
    q: Annotated[str, Query(min_length=1, description="Search term for product name or SKU")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: AsyncSession = Depends(get_db),
):
    """
    Search product variants by product family name or full SKU.

    Returns compact results suitable for autocomplete / typeahead UIs.
    """
    ts_query = func.websearch_to_tsquery("simple", q)
    family_vector = func.to_tsvector("simple", func.coalesce(ProductFamily.base_name, ""))
    sku_vector = func.to_tsvector("simple", func.coalesce(ProductVariant.full_sku, ""))
    variant_name_vector = func.to_tsvector("simple", func.coalesce(ProductVariant.variant_name, ""))
    rank = func.greatest(
        func.ts_rank_cd(family_vector, ts_query),
        func.ts_rank_cd(sku_vector, ts_query),
        func.ts_rank_cd(variant_name_vector, ts_query),
    ).label("rank")

    stmt = (
        select(
            ProductVariant.id,
            ProductVariant.full_sku,
            ProductVariant.variant_name,
            ProductVariant.color_code,
            ProductVariant.condition_code,
            ProductFamily.base_name.label("product_name"),
            rank,
        )
        .join(ProductIdentity, ProductVariant.identity_id == ProductIdentity.id)
        .join(ProductFamily, ProductIdentity.product_id == ProductFamily.product_id)
        .where(
            family_vector.op("@@")(ts_query)
            | sku_vector.op("@@")(ts_query)
            | variant_name_vector.op("@@")(ts_query)
        )
        .where(ProductVariant.is_active == True)
        .order_by(rank.desc(), ProductVariant.full_sku)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            "id": row.id,
            "full_sku": row.full_sku,
            "variant_name": row.variant_name or row.product_name or row.full_sku,
            "product_name": row.product_name or "",
            "color_code": row.color_code,
            "condition_code": row.condition_code.value if row.condition_code else None,
        }
        for row in rows
    ]


@router.get("", response_model=PaginatedResponse)
async def list_variants(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    identity_id: Annotated[int | None, Query(description="Filter by identity")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by active status")] = True,
    zoho_sync_status: Annotated[ZohoSyncStatus | None, Query(description="Filter by Zoho sync status")] = None,
    db: AsyncSession = Depends(get_db),
):
    """List product variants with optional filtering."""
    repo = ProductVariantRepository(db)
    
    filters = {}
    if identity_id is not None:
        filters["identity_id"] = identity_id
    if is_active is not None:
        filters["is_active"] = is_active
    if zoho_sync_status is not None:
        filters["zoho_sync_status"] = zoho_sync_status
    
    items = await repo.get_multi(skip=skip, limit=limit, filters=filters, order_by="id")
    total = await repo.count(filters=filters)
    
    return PaginatedResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=[ProductVariantResponse.model_validate(item) for item in items]
    )


@router.post("", response_model=ProductVariantResponse, status_code=status.HTTP_201_CREATED)
async def create_variant(
    data: ProductVariantCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new product variant.
    
    The full SKU is auto-generated from identity UPIS-H, color code, and condition.
    """
    variant_repo = ProductVariantRepository(db)
    identity_repo = ProductIdentityRepository(db)
    
    # Verify identity exists
    identity = await identity_repo.get(data.identity_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product identity {data.identity_id} not found"
        )
    
    # Check for duplicate variant
    existing_variants = await variant_repo.get_by_identity(data.identity_id, include_inactive=True)
    for v in existing_variants:
        if v.color_code == data.color_code and v.condition_code == data.condition_code:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Variant with color '{data.color_code}' and condition '{data.condition_code}' already exists for this identity"
            )
    
    variant = await variant_repo.create_variant(data.model_dump(), identity)
    return ProductVariantResponse.model_validate(variant)


@router.get("/{variant_id}", response_model=ProductVariantWithListings)
async def get_variant(
    variant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a product variant by ID with its platform listings."""
    repo = ProductVariantRepository(db)
    identity_repo = ProductIdentityRepository(db)
    variant = await repo.get_with_listings(variant_id)
    
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {variant_id} not found"
        )
    
    return ProductVariantWithListings.model_validate(variant)


@router.get("/sku/{full_sku}", response_model=ProductVariantResponse)
async def get_variant_by_sku(
    full_sku: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a product variant by full SKU."""
    repo = ProductVariantRepository(db)
    variant = await repo.get_by_sku(full_sku.upper())
    
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant '{full_sku}' not found"
        )
    
    return ProductVariantResponse.model_validate(variant)


@router.put("/{variant_id}", response_model=ProductVariantResponse)
@router.patch("/{variant_id}", response_model=ProductVariantResponse)
async def update_variant(
    variant_id: int,
    data: ProductVariantUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a product variant (supports both PUT and PATCH)."""
    repo = ProductVariantRepository(db)
    identity_repo = ProductIdentityRepository(db)
    variant = await repo.get(variant_id)
    
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {variant_id} not found"
        )
    
    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        target_color = update_data.get("color_code", variant.color_code)
        target_condition = update_data.get("condition_code", variant.condition_code)

        # If variant combination changes, enforce uniqueness and recompute full SKU.
        if "color_code" in update_data or "condition_code" in update_data:
            existing_variants = await repo.get_by_identity(variant.identity_id, include_inactive=True)
            for other in existing_variants:
                if other.id == variant.id:
                    continue
                if other.color_code == target_color and other.condition_code == target_condition:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Variant with color "
                            f"'{target_color}' and condition '{target_condition}' already exists for this identity"
                        ),
                    )

            identity = await identity_repo.get(variant.identity_id)
            if identity is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Product identity {variant.identity_id} not found",
                )

            update_data["full_sku"] = repo.generate_full_sku(
                identity.generated_upis_h,
                target_color,
                target_condition.value if hasattr(target_condition, "value") else target_condition,
            )

        # Any local edit means Zoho copy is stale unless this is still a first-time pending item.
        keep_pending = (
            variant.zoho_sync_status == ZohoSyncStatus.PENDING
            and not variant.zoho_item_id
        )
        if not keep_pending:
            update_data["zoho_sync_status"] = ZohoSyncStatus.DIRTY
            update_data["zoho_sync_error"] = None

        variant = await repo.update(variant, update_data)
    
    return ProductVariantResponse.model_validate(variant)


@router.delete("/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_variant(
    variant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a variant and free reusable SKU/color-condition space."""
    repo = ProductVariantRepository(db)

    variant = await repo.get(variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {variant_id} not found"
        )

    if not variant.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Product variant {variant_id} is already deleted",
        )

    deleted_sku = await _build_unique_deleted_sku(repo, variant.full_sku, variant.id)

    await repo.update(
        variant,
        {
            "is_active": False,
            "full_sku": deleted_sku,
            # Clear these to free identity+color+condition uniqueness for replacement variants.
            "color_code": None,
            "condition_code": None,
        },
    )


@router.post("/{variant_id}/deactivate", response_model=ProductVariantResponse)
async def deactivate_variant(
    variant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a variant by setting is_active to false."""
    repo = ProductVariantRepository(db)
    variant = await repo.get(variant_id)
    
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {variant_id} not found"
        )
    
    variant = await repo.update(variant, {"is_active": False})
    return ProductVariantResponse.model_validate(variant)


@router.get("/pending-sync/zoho", response_model=list[ProductVariantResponse])
async def get_pending_zoho_sync(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    db: AsyncSession = Depends(get_db),
):
    """Get variants pending Zoho synchronization."""
    repo = ProductVariantRepository(db)
    variants = await repo.get_pending_zoho_sync(limit=limit)
    return [ProductVariantResponse.model_validate(v) for v in variants]
