"""
Product Variant API endpoints.
"""
import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse

from app.api.deps import AdminOrSalesUser
from app.core.database import get_db
from app.models import IdentityType, ZohoSyncStatus
from sqlalchemy import func, select, update
from sqlalchemy import inspect
from sqlalchemy.orm import selectinload

from app.models.entities import (
    Brand,
    InventoryItem,
    PlatformListing,
    ProductFamily,
    ProductIdentity,
    ProductVariant,
)
from app.models.purchasing import PurchaseOrderItem
from app.modules.orders.models import OrderItem
from app.repositories import (
    BundleComponentRepository,
    ProductIdentityRepository,
    ProductVariantRepository,
)
from app.modules.inventory.schemas import (
    PaginatedResponse,
    ProductVariantConvertToKitRequest,
    ProductVariantConvertToKitResponse,
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
    ProductVariantWithListings,
)

router = APIRouter(prefix="/variants", tags=["Product Variants"])


ZOHO_IMPORT_HEADERS = [
    "Item Name",
    "SKU",
    "Sales Description",
    "Selling Price",
    "Is Returnable Item",
    "Brand",
    "Manufacturer",
    "UPC",
    "EAN",
    "ISBN",
    "Part Number",
    "Product Type",
    "Sales Account",
    "Unit",
    "Purchase Description",
    "Purchase Price",
    "Item Type",
    "Purchase Account",
    "Inventory Account",
    "Reorder Level",
    "Preferred Vendor",
    "Opening Stock",
    "Opening Stock Value",
    "Package Weight",
    "Package Length",
    "Package Width",
    "Package Height",
    "Weight unit",
    "Dimension unit",
    "Warehouse Name",
    "Image",
]


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


def _condition_code_value(condition_code: object) -> str | None:
    if condition_code is None:
        return None
    return condition_code.value if hasattr(condition_code, "value") else str(condition_code)


def _validate_convert_to_kit_children(
    *,
    source_variant_id: int,
    source_identity_id: int,
    children: list,
    child_variants_by_id: dict[int, ProductVariant],
) -> list[tuple[ProductVariant, int, object]]:
    """
    Validate requested kit child lines and resolve them to loaded variants.

    Returns tuples of (child_variant, quantity_required, role) in request order.
    """
    if not children:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one child item is required.",
        )

    seen_child_identity_ids: set[int] = set()
    resolved_rows: list[tuple[ProductVariant, int, object]] = []

    for index, child in enumerate(children, start=1):
        child_variant = child_variants_by_id.get(child.child_variant_id)
        if child_variant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Child variant {child.child_variant_id} not found or inactive (line {index}).",
            )

        child_identity = child_variant.identity
        if child_identity is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Child variant {child_variant.id} has no linked identity (line {index}).",
            )

        if child_variant.id == source_variant_id or child_variant.identity_id == source_identity_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Child variant {child_variant.id} cannot reference the source product itself (line {index}).",
            )

        if child_identity.type in {IdentityType.B, IdentityType.K}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Child variant {child_variant.id} uses identity type '{child_identity.type.value}' "
                    f"which is not allowed for kit children (line {index})."
                ),
            )

        if child_identity.id in seen_child_identity_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Duplicate child identity {child_identity.generated_upis_h} is not allowed "
                    f"(line {index})."
                ),
            )

        seen_child_identity_ids.add(child_identity.id)
        resolved_rows.append((child_variant, int(child.quantity_required), child.role))

    return resolved_rows


async def _migrate_variant_links(
    db: AsyncSession,
    *,
    source_variant_id: int,
    target_variant_id: int,
) -> dict[str, int]:
    """Move FK links from one variant to another and return per-table moved counts."""
    migrated_counts: dict[str, int] = {}

    platform_result = await db.execute(
        update(PlatformListing)
        .where(PlatformListing.variant_id == source_variant_id)
        .values(variant_id=target_variant_id)
    )
    migrated_counts["platform_listing"] = int(platform_result.rowcount or 0)

    inventory_result = await db.execute(
        update(InventoryItem)
        .where(InventoryItem.variant_id == source_variant_id)
        .values(variant_id=target_variant_id)
    )
    migrated_counts["inventory_item"] = int(inventory_result.rowcount or 0)

    order_item_result = await db.execute(
        update(OrderItem)
        .where(OrderItem.variant_id == source_variant_id)
        .values(variant_id=target_variant_id)
    )
    migrated_counts["order_item"] = int(order_item_result.rowcount or 0)

    purchase_item_result = await db.execute(
        update(PurchaseOrderItem)
        .where(PurchaseOrderItem.variant_id == source_variant_id)
        .values(variant_id=target_variant_id)
    )
    migrated_counts["purchase_order_item"] = int(purchase_item_result.rowcount or 0)

    return migrated_counts


@router.get("/search", summary="Search variants by product name or SKU")
async def search_variants(
    q: Annotated[str, Query(min_length=1, description="Search term for product name or SKU")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    include_identity_types: Annotated[
        str | None,
        Query(description="Comma-separated identity types to include, e.g. 'Product,P'"),
    ] = None,
    exclude_identity_types: Annotated[
        str | None,
        Query(description="Comma-separated identity types to exclude, e.g. 'B,K'"),
    ] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Search product variants by product family name or full SKU.

    Returns compact results suitable for autocomplete / typeahead UIs.
    """
    included = _parse_identity_types(include_identity_types, "include_identity_types")
    excluded = _parse_identity_types(exclude_identity_types, "exclude_identity_types")

    if included and excluded and set(included).intersection(set(excluded)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="include_identity_types and exclude_identity_types cannot overlap.",
        )

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
            ProductVariant.identity_id,
            ProductVariant.full_sku,
            ProductVariant.variant_name,
            ProductVariant.color_code,
            ProductVariant.condition_code,
            ProductIdentity.type.label("identity_type"),
            ProductIdentity.generated_upis_h,
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
    )

    if included:
        stmt = stmt.where(ProductIdentity.type.in_(included))
    if excluded:
        stmt = stmt.where(~ProductIdentity.type.in_(excluded))

    stmt = stmt.order_by(rank.desc(), ProductVariant.full_sku).limit(limit)

    rows = (await db.execute(stmt)).all()

    return [
        {
            "id": row.id,
            "identity_id": row.identity_id,
            "identity_type": row.identity_type.value if hasattr(row.identity_type, "value") else row.identity_type,
            "generated_upis_h": row.generated_upis_h,
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
    if identity.is_stationery and existing_variants:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stationery identities are single-SKU only and already have a generated variant",
        )

    for v in existing_variants:
        if v.color_code == data.color_code and v.condition_code == data.condition_code:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Variant with color '{data.color_code}' and condition '{data.condition_code}' already exists for this identity"
            )
    
    variant = await variant_repo.create_variant(data.model_dump(), identity)
    return ProductVariantResponse.model_validate(variant)


@router.get("/export/zoho-import.csv")
async def export_variants_for_zoho_import_csv(
    include_inactive: Annotated[bool, Query(description="Include inactive variants")] = True,
    exclude_bundles: Annotated[bool, Query(description="Exclude bundle/kit identities (type B/K)")] = True,
    db: AsyncSession = Depends(get_db),
):
    """Export variants to Zoho item-import CSV format."""
    # Some environments may lag model migrations; probe columns to avoid hard failures.
    def _get_variant_columns(sync_session):
        inspector = inspect(sync_session.connection())
        return {column["name"] for column in inspector.get_columns("product_variant")}

    variant_columns = await db.run_sync(_get_variant_columns)
    has_variant_name = "variant_name" in variant_columns
    has_thumbnail_url = "thumbnail_url" in variant_columns

    select_columns = [
        ProductVariant.id.label("variant_id"),
        ProductVariant.full_sku.label("full_sku"),
        ProductIdentity.weight.label("weight"),
        ProductIdentity.dimension_length.label("dimension_length"),
        ProductIdentity.dimension_width.label("dimension_width"),
        ProductIdentity.dimension_height.label("dimension_height"),
        ProductFamily.base_name.label("base_name"),
        ProductFamily.description.label("family_description"),
        Brand.name.label("brand_name"),
        func.max(PlatformListing.listing_price).label("selling_price"),
    ]
    group_by_columns = [
        ProductVariant.id,
        ProductVariant.full_sku,
        ProductIdentity.weight,
        ProductIdentity.dimension_length,
        ProductIdentity.dimension_width,
        ProductIdentity.dimension_height,
        ProductFamily.base_name,
        ProductFamily.description,
        Brand.name,
    ]

    if has_variant_name:
        select_columns.append(ProductVariant.variant_name.label("variant_name"))
        group_by_columns.append(ProductVariant.variant_name)
    if has_thumbnail_url:
        select_columns.append(ProductVariant.thumbnail_url.label("thumbnail_url"))
        group_by_columns.append(ProductVariant.thumbnail_url)

    stmt = (
        select(*select_columns)
        .join(ProductIdentity, ProductVariant.identity_id == ProductIdentity.id)
        .join(ProductFamily, ProductIdentity.product_id == ProductFamily.product_id)
        .outerjoin(Brand, ProductFamily.brand_id == Brand.id)
        .outerjoin(PlatformListing, PlatformListing.variant_id == ProductVariant.id)
        .group_by(*group_by_columns)
        .order_by(ProductVariant.id)
    )

    if exclude_bundles:
        stmt = stmt.where(~ProductIdentity.type.in_([IdentityType.B, IdentityType.K]))
    if not include_inactive:
        stmt = stmt.where(ProductVariant.is_active == True)

    variants = (await db.execute(stmt)).all()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=ZOHO_IMPORT_HEADERS)
    writer.writeheader()

    for variant in variants:
        row_data = variant._mapping
        variant_name = (row_data.get("variant_name") or "").strip()
        base_name = (variant_name or (row_data.get("base_name") or "") or row_data["full_sku"]).strip()
        description = ((row_data.get("family_description") or "") or base_name).strip()
        brand_name = (row_data.get("brand_name") or "").strip()
        selling_price = row_data.get("selling_price")

        row = {
            "Item Name": base_name,
            "SKU": row_data["full_sku"],
            "Sales Description": description,
            "Selling Price": str(selling_price) if selling_price is not None else "",
            "Is Returnable Item": "FALSE",
            "Brand": brand_name,
            "Manufacturer": brand_name,
            "UPC": "",
            "EAN": "",
            "ISBN": "",
            "Part Number": "",
            "Product Type": "goods",
            "Sales Account": "Sales",
            "Unit": "pcs",
            "Purchase Description": description,
            "Purchase Price": "",
            "Item Type": "Inventory",
            "Purchase Account": "Cost of Goods Sold",
            "Inventory Account": "Inventory Asset",
            "Reorder Level": "",
            "Preferred Vendor": "",
            "Opening Stock": "",
            "Opening Stock Value": "",
            "Package Weight": str(row_data["weight"]) if row_data["weight"] is not None else "",
            "Package Length": str(row_data["dimension_length"]) if row_data["dimension_length"] is not None else "",
            "Package Width": str(row_data["dimension_width"]) if row_data["dimension_width"] is not None else "",
            "Package Height": str(row_data["dimension_height"]) if row_data["dimension_height"] is not None else "",
            "Weight unit": "kg",
            "Dimension unit": "cm",
            "Warehouse Name": "",
            "Image": (row_data.get("thumbnail_url") or "") if has_thumbnail_url else "",
        }
        writer.writerow(row)

    filename = f"zoho_items_import_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        identity = await identity_repo.get(variant.identity_id)
        if identity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product identity {variant.identity_id} not found",
            )

        if identity.is_stationery and ("color_code" in update_data or "condition_code" in update_data):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stationery variants cannot change color or condition",
            )

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

            update_data["full_sku"] = repo.generate_full_sku(
                identity.generated_upis_h,
                target_color,
                target_condition.value if hasattr(target_condition, "value") else target_condition,
            )

            # Thumbnail URLs are SKU-path based; once SKU changes, any existing
            # cached thumbnail_url may point to a different folder.
            if update_data["full_sku"] != variant.full_sku:
                update_data["thumbnail_url"] = None

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


@router.post("/{variant_id}/convert-to-kit", response_model=ProductVariantConvertToKitResponse)
async def convert_variant_to_kit(
    variant_id: int,
    data: ProductVariantConvertToKitRequest,
    _editor: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Convert one Product variant into a Kit variant.

    Conversion is transactional:
    - Create a new Kit identity + variant
    - Add bundle-component rows from provided child variants
    - Move dependent FK links to the new variant
    - Retire (deactivate) the source variant

    Zoho sync is not triggered here; the new kit variant remains pending.
    """
    variant_repo = ProductVariantRepository(db)
    identity_repo = ProductIdentityRepository(db)
    bundle_repo = BundleComponentRepository(db)

    source_variant_stmt = (
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.identity).selectinload(ProductIdentity.family),
        )
        .where(ProductVariant.id == variant_id)
        .limit(1)
    )
    source_variant = (await db.execute(source_variant_stmt)).scalar_one_or_none()
    if source_variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {variant_id} not found",
        )
    if not source_variant.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product variant {variant_id} is inactive and cannot be converted to kit.",
        )

    source_identity = source_variant.identity
    if source_identity is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product variant {variant_id} has no linked identity.",
        )
    if source_identity.type != IdentityType.PRODUCT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Only Product variants can be converted to kit. "
                f"Current type is '{source_identity.type.value}'."
            ),
        )

    child_variant_ids = [child.child_variant_id for child in data.children]
    child_variants_stmt = (
        select(ProductVariant)
        .options(selectinload(ProductVariant.identity))
        .where(ProductVariant.id.in_(child_variant_ids))
        .where(ProductVariant.is_active == True)
    )
    child_variants = (await db.execute(child_variants_stmt)).scalars().all()
    child_variants_by_id = {child_variant.id: child_variant for child_variant in child_variants}

    resolved_children = _validate_convert_to_kit_children(
        source_variant_id=source_variant.id,
        source_identity_id=source_identity.id,
        children=data.children,
        child_variants_by_id=child_variants_by_id,
    )

    kit_upis_h = identity_repo.generate_upis_h(source_identity.product_id, IdentityType.K, None)
    existing_kit_identity = await identity_repo.get_by_upis_h(kit_upis_h)
    if existing_kit_identity is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Kit identity '{kit_upis_h}' already exists for product family "
                f"{source_identity.product_id}."
            ),
        )

    target_kit_sku = variant_repo.generate_full_sku(
        kit_upis_h,
        source_variant.color_code,
        _condition_code_value(source_variant.condition_code),
    )
    existing_target_sku = await variant_repo.get_by_sku(target_kit_sku)
    if existing_target_sku is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Target kit SKU '{target_kit_sku}' already exists.",
        )

    kit_identity = await identity_repo.create_identity(
        {
            "product_id": source_identity.product_id,
            "type": IdentityType.K,
            "identity_name": source_identity.identity_name,
            "physical_class": source_identity.physical_class,
            "dimension_length": source_identity.dimension_length,
            "dimension_width": source_identity.dimension_width,
            "dimension_height": source_identity.dimension_height,
            "weight": source_identity.weight,
            "is_stationery": False,
        }
    )

    kit_variant = await variant_repo.create_variant(
        {
            "identity_id": kit_identity.id,
            "variant_name": source_variant.variant_name,
            "color_code": source_variant.color_code,
            "condition_code": source_variant.condition_code,
            "is_active": True,
            # New composite identity should be manually synced later.
            "zoho_sync_status": ZohoSyncStatus.PENDING,
            "zoho_item_id": None,
            "zoho_sync_error": None,
            # Source thumbnail path is SKU-scoped; clear until kit SKU images are prepared.
            "thumbnail_url": None,
        },
        kit_identity,
    )

    for child_variant, quantity_required, role in resolved_children:
        await bundle_repo.create(
            {
                "parent_identity_id": kit_identity.id,
                "child_identity_id": child_variant.identity_id,
                "quantity_required": quantity_required,
                "role": role,
            }
        )

    migrated_counts = await _migrate_variant_links(
        db,
        source_variant_id=source_variant.id,
        target_variant_id=kit_variant.id,
    )

    source_variant.is_active = False
    source_variant.zoho_sync_error = None
    if not (
        source_variant.zoho_sync_status == ZohoSyncStatus.PENDING
        and not source_variant.zoho_item_id
    ):
        source_variant.zoho_sync_status = ZohoSyncStatus.DIRTY

    kit_variant.zoho_sync_status = ZohoSyncStatus.PENDING
    kit_variant.zoho_item_id = None
    kit_variant.zoho_sync_error = None

    return ProductVariantConvertToKitResponse(
        source_variant_id=source_variant.id,
        source_sku=source_variant.full_sku,
        new_identity_id=kit_identity.id,
        new_variant_id=kit_variant.id,
        new_sku=kit_variant.full_sku,
        bundle_components_created=len(resolved_children),
        migrated_counts=migrated_counts,
    )


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
