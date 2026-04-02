"""
Product Identity API endpoints.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import IdentityType
from app.models.entities import ProductFamily, ProductIdentity
from app.repositories import ProductFamilyRepository, ProductIdentityRepository, ProductVariantRepository
from app.modules.inventory.schemas import (
    PaginatedResponse,
    ProductIdentityCreate,
    ProductIdentityResponse,
    ProductIdentityUpdate,
    ProductIdentityWithVariants,
)

router = APIRouter(prefix="/identities", tags=["Product Identities"])


def _parse_identity_types(raw_value: str | None, field_name: str) -> list[IdentityType] | None:
    """Parse comma-separated identity types into enum values."""
    if not raw_value:
        return None

    allowed_values = {identity_type.value for identity_type in IdentityType}
    parsed: list[IdentityType] = []
    seen: set[IdentityType] = set()

    for token in raw_value.split(","):
        value = token.strip()
        if not value:
            continue
        if value not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {field_name} value '{value}'. Allowed values: {', '.join(sorted(allowed_values))}.",
            )
        enum_value = IdentityType(value)
        if enum_value not in seen:
            parsed.append(enum_value)
            seen.add(enum_value)

    return parsed or None


@router.get("/search", summary="Search identities by UPIS-H, name, or family")
async def search_identities(
    q: Annotated[str, Query(min_length=1, description="Search term for UPIS-H, identity name, or family name")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    include_types: Annotated[
        str | None,
        Query(description="Comma-separated identity types to include, e.g. 'Product,P'"),
    ] = None,
    exclude_types: Annotated[
        str | None,
        Query(description="Comma-separated identity types to exclude, e.g. 'B,K'"),
    ] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return compact identity search rows for autocomplete UIs."""
    included = _parse_identity_types(include_types, "include_types")
    excluded = _parse_identity_types(exclude_types, "exclude_types")

    if included and excluded and set(included).intersection(set(excluded)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="include_types and exclude_types cannot overlap.",
        )

    ts_query = func.websearch_to_tsquery("simple", q)
    family_vector = func.to_tsvector("simple", func.coalesce(ProductFamily.base_name, ""))
    upis_vector = func.to_tsvector("simple", func.coalesce(ProductIdentity.generated_upis_h, ""))
    identity_name_vector = func.to_tsvector("simple", func.coalesce(ProductIdentity.identity_name, ""))
    product_id_vector = func.to_tsvector("simple", cast(ProductIdentity.product_id, String))
    rank = func.greatest(
        func.ts_rank_cd(family_vector, ts_query),
        func.ts_rank_cd(upis_vector, ts_query),
        func.ts_rank_cd(identity_name_vector, ts_query),
        func.ts_rank_cd(product_id_vector, ts_query),
    ).label("rank")

    stmt = (
        select(
            ProductIdentity.id,
            ProductIdentity.product_id,
            ProductIdentity.type,
            ProductIdentity.is_stationery,
            ProductIdentity.lci,
            ProductIdentity.generated_upis_h,
            ProductIdentity.identity_name,
            ProductFamily.base_name.label("family_name"),
            rank,
        )
        .join(ProductFamily, ProductIdentity.product_id == ProductFamily.product_id)
        .where(
            family_vector.op("@@")(ts_query)
            | upis_vector.op("@@")(ts_query)
            | identity_name_vector.op("@@")(ts_query)
            | product_id_vector.op("@@")(ts_query)
        )
    )

    if included:
        stmt = stmt.where(ProductIdentity.type.in_(included))
    if excluded:
        stmt = stmt.where(~ProductIdentity.type.in_(excluded))

    rows = (
        await db.execute(
            stmt.order_by(rank.desc(), ProductIdentity.generated_upis_h).limit(limit)
        )
    ).all()

    return [
        {
            "id": row.id,
            "product_id": row.product_id,
            "type": row.type.value if hasattr(row.type, "value") else row.type,
            "is_stationery": row.is_stationery,
            "lci": row.lci,
            "generated_upis_h": row.generated_upis_h,
            "identity_name": row.identity_name,
            "family_name": row.family_name or "",
        }
        for row in rows
    ]


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

    if data.is_stationery and data.type != IdentityType.PRODUCT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stationery identities must use type 'Product'",
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

    # Ensure newly created Product/Part/Bundle identities are immediately sellable/searchable.
    if identity.type in {IdentityType.PRODUCT, IdentityType.P, IdentityType.B}:
        variant_repo = ProductVariantRepository(db)
        await variant_repo.create_variant(
            {
                "identity_id": identity.id,
                "variant_name": identity.identity_name or family.base_name,
            },
            identity,
        )

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
    
    Note: `identity_name` and `physical_class` can be updated.
    The UPIS-H and hex signature are immutable after creation.
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
