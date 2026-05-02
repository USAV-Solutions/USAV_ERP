"""
Platform Listing API endpoints.
Manages listings for external platforms (Zoho, Amazon, eBay, etc.).
"""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.integrations.ebay.client import EbayClient
from app.models import Platform, PlatformSyncStatus
from app.models.entities import ProductVariant, ProductIdentity, ProductFamily
from app.repositories import PlatformListingRepository, ProductVariantRepository
from app.modules.inventory.schemas import (
    EbayCategorySuggestion,
    EbayCategorySuggestionsRequest,
    EbayCategorySuggestionsResponse,
    EbayListingDraftRequest,
    EbayListingDraftResponse,
    EbayPolicyProfiles,
    EbayPublishRequest,
    EbayPublishResponse,
    PaginatedResponse,
    PlatformListingCreate,
    PlatformListingResponse,
    PlatformListingUpdate,
)

router = APIRouter(prefix="/listings", tags=["Platform Listings"])


def _build_ebay_client_for_platform(platform: Platform) -> EbayClient:
    if platform not in {Platform.EBAY_MEKONG, Platform.EBAY_USAV, Platform.EBAY_DRAGON}:
        raise HTTPException(status_code=400, detail="Only eBay platforms are supported for this endpoint")

    store_name = platform.value.replace("EBAY_", "")
    refresh_token_by_platform = {
        Platform.EBAY_MEKONG: settings.ebay_refresh_token_mekong,
        Platform.EBAY_USAV: settings.ebay_refresh_token_usav,
        Platform.EBAY_DRAGON: settings.ebay_refresh_token_dragon,
    }
    refresh_token = refresh_token_by_platform.get(platform, "")
    client = EbayClient(
        store_name=store_name,
        app_id=settings.ebay_app_id,
        cert_id=settings.ebay_cert_id,
        refresh_token=refresh_token,
        sandbox=settings.ebay_sandbox,
    )
    if not client.is_configured:
        raise HTTPException(status_code=400, detail=f"eBay {platform.value} credentials not configured")
    return client


async def _load_variant_context(db: AsyncSession, variant_id: int) -> ProductVariant:
    stmt = (
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.identity)
            .selectinload(ProductIdentity.family)
            .selectinload(ProductFamily.brand),
            selectinload(ProductVariant.listings),
        )
        .where(ProductVariant.id == variant_id)
    )
    variant = (await db.execute(stmt)).scalar_one_or_none()
    if variant is None:
        raise HTTPException(status_code=404, detail=f"Product variant {variant_id} not found")
    return variant


def _resolve_listing_defaults(
    variant: ProductVariant,
    platform: Platform,
) -> dict[str, object]:
    existing_listing = next((l for l in (variant.listings or []) if l.platform == platform), None)
    identity = variant.identity
    family = identity.family if identity else None
    brand_name = family.brand.name if family and family.brand else None
    title = (
        (existing_listing.listed_name if existing_listing else None)
        or variant.variant_name
        or (identity.identity_name if identity else None)
        or (family.base_name if family else None)
        or variant.full_sku
    )
    description = (
        (existing_listing.listed_description if existing_listing else None)
        or (family.description if family and family.description else None)
        or title
    )
    price = float(existing_listing.listing_price) if existing_listing and existing_listing.listing_price is not None else 0.0
    quantity = existing_listing.listing_quantity if existing_listing and existing_listing.listing_quantity is not None else 1
    picture_urls: list[str] = []
    if variant.thumbnail_url:
        picture_urls.append(variant.thumbnail_url)
    if existing_listing and isinstance(existing_listing.platform_metadata, dict):
        for value in existing_listing.platform_metadata.get("picture_urls", []) or []:
            if value and value not in picture_urls:
                picture_urls.append(value)

    color = variant.color_code
    upc = existing_listing.upc if existing_listing else None
    condition_text = (
        (existing_listing.listing_condition if existing_listing else None)
        or (variant.condition_code.value if getattr(variant, "condition_code", None) else None)
    )

    return {
        "existing_listing": existing_listing,
        "title": title,
        "description": description,
        "price": price,
        "quantity": quantity,
        "picture_urls": picture_urls,
        "color": color,
        "upc": upc,
        "condition_text": condition_text,
        "brand_name": brand_name,
    }


def _build_category_query(
    *,
    title: str | None,
    brand: str | None,
    color: str | None,
    condition_text: str | None,
    fallback_sku: str,
) -> str:
    pieces = [title, brand, color, condition_text, fallback_sku]
    tokens = [str(piece).strip() for piece in pieces if piece and str(piece).strip()]
    query = " ".join(tokens).strip()
    return query[:350]


def _parse_float_or_none(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


@router.post("/ebay/draft", response_model=EbayListingDraftResponse)
async def get_ebay_listing_draft(
    data: EbayListingDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    client = _build_ebay_client_for_platform(data.platform)
    variant = await _load_variant_context(db, data.variant_id)
    defaults = _resolve_listing_defaults(variant, data.platform)
    identity = variant.identity
    store_defaults = client.get_store_listing_defaults()
    payment_profile_id = str(store_defaults["payment_profile_id"]).strip()
    return_profile_id = str(store_defaults["return_profile_id"]).strip()
    shipping_profile_id = str(store_defaults["shipping_profile_id"]).strip()
    if not payment_profile_id or not return_profile_id or not shipping_profile_id:
        raise HTTPException(
            status_code=400,
            detail=f"Missing eBay business policy IDs for {data.platform.value}",
        )
    condition_text = defaults["condition_text"]
    condition_id = client.to_condition_id(condition_text)
    shipping_package_details = client.to_shipping_package_details(
        weight_lbs=_parse_float_or_none(getattr(identity, "weight", None)),
        length_in=_parse_float_or_none(getattr(identity, "dimension_length", None)),
        width_in=_parse_float_or_none(getattr(identity, "dimension_width", None)),
        height_in=_parse_float_or_none(getattr(identity, "dimension_height", None)),
    )
    return EbayListingDraftResponse(
        platform=data.platform,
        variant_id=variant.id,
        title=str(defaults["title"]),
        description=str(defaults["description"]),
        sku=variant.full_sku,
        quantity=int(defaults["quantity"]),
        price=float(defaults["price"]),
        condition_text=condition_text,
        condition_id=condition_id,
        upc=defaults["upc"],
        brand=defaults["brand_name"],
        color=defaults["color"],
        marketplace_id=str(store_defaults["marketplace_id"]),
        country=str(store_defaults["country"]),
        currency=str(store_defaults["currency"]),
        location=str(store_defaults["location"]),
        postal_code=str(store_defaults["postal_code"]),
        dispatch_time_max=int(store_defaults["dispatch_time_max"]),
        category_id=(
            defaults["existing_listing"].platform_metadata.get("category_id")
            if defaults["existing_listing"] and isinstance(defaults["existing_listing"].platform_metadata, dict)
            else None
        ),
        picture_urls=list(defaults["picture_urls"]),
        dimensions={
            "length": _parse_float_or_none(getattr(identity, "dimension_length", None)),
            "width": _parse_float_or_none(getattr(identity, "dimension_width", None)),
            "height": _parse_float_or_none(getattr(identity, "dimension_height", None)),
            "weight": _parse_float_or_none(getattr(identity, "weight", None)),
        },
        shipping_package_details=shipping_package_details,
        seller_profiles=EbayPolicyProfiles(
            payment_profile_id=payment_profile_id,
            return_profile_id=return_profile_id,
            shipping_profile_id=shipping_profile_id,
        ),
    )


@router.post("/ebay/category-suggestions", response_model=EbayCategorySuggestionsResponse)
async def get_ebay_category_suggestions(
    data: EbayCategorySuggestionsRequest,
    db: AsyncSession = Depends(get_db),
):
    client = _build_ebay_client_for_platform(data.platform)
    variant = await _load_variant_context(db, data.variant_id)
    defaults = _resolve_listing_defaults(variant, data.platform)
    store_defaults = client.get_store_listing_defaults()
    query_text = (
        data.query_override
        or _build_category_query(
            title=data.title or str(defaults["title"]),
            brand=data.brand or defaults["brand_name"],
            color=data.color or defaults["color"],
            condition_text=data.condition_text or defaults["condition_text"],
            fallback_sku=variant.full_sku,
        )
    )
    if not query_text:
        raise HTTPException(status_code=400, detail="Unable to build category suggestion query")
    marketplace_id = str(store_defaults["marketplace_id"])
    category_tree_id = await client.get_default_category_tree_id(marketplace_id)
    suggestions = await client.get_category_suggestions(category_tree_id, query_text)
    parsed: list[EbayCategorySuggestion] = []
    for entry in suggestions:
        category = entry.get("category") or {}
        ancestors = entry.get("categoryTreeNodeAncestors") or []
        category_tokens = [
            ancestor.get("category", {}).get("categoryName")
            for ancestor in ancestors
            if ancestor.get("category", {}).get("categoryName")
        ]
        if category.get("categoryName"):
            category_tokens.append(category.get("categoryName"))
        category_id = category.get("categoryId")
        if not category_id:
            continue
        parsed.append(
            EbayCategorySuggestion(
                category_id=str(category_id),
                category_name=str(category.get("categoryName") or ""),
                category_tree_node_level=entry.get("categoryTreeNodeLevel"),
                category_tree_tokens=category_tokens,
            )
        )
    return EbayCategorySuggestionsResponse(
        marketplace_id=marketplace_id,
        category_tree_id=category_tree_id,
        query=query_text,
        suggestions=parsed,
    )


@router.post("/ebay/publish", response_model=EbayPublishResponse)
async def publish_ebay_listing(
    data: EbayPublishRequest,
    db: AsyncSession = Depends(get_db),
):
    client = _build_ebay_client_for_platform(data.platform)
    variant = await _load_variant_context(db, data.variant_id)
    identity = variant.identity
    listing_repo = PlatformListingRepository(db)
    existing = await listing_repo.get_by_variant_platform(variant.id, data.platform)
    if existing and existing.external_ref_id:
        raise HTTPException(
            status_code=409,
            detail=f"Variant {variant.id} already has an eBay listing on {data.platform.value}",
        )

    picture_urls = [url.strip() for url in data.picture_urls if url and url.strip()]
    if not picture_urls:
        raise HTTPException(status_code=400, detail="At least one picture URL is required")

    store_defaults = client.get_store_listing_defaults()
    payment_profile_id = str(store_defaults["payment_profile_id"]).strip()
    return_profile_id = str(store_defaults["return_profile_id"]).strip()
    shipping_profile_id = str(store_defaults["shipping_profile_id"]).strip()
    if not payment_profile_id or not return_profile_id or not shipping_profile_id:
        raise HTTPException(status_code=400, detail=f"Missing eBay business policy IDs for {data.platform.value}")

    country = str(store_defaults["country"]).strip()
    currency = str(store_defaults["currency"]).strip()
    location = str(store_defaults["location"]).strip()
    postal_code = str(store_defaults["postal_code"]).strip()
    if not country or not currency or (not location and not postal_code):
        raise HTTPException(status_code=400, detail=f"Missing country/currency/location defaults for {data.platform.value}")

    dispatch_time_max = int(store_defaults["dispatch_time_max"])
    if dispatch_time_max < 0:
        raise HTTPException(status_code=400, detail="DispatchTimeMax must be zero or greater")

    condition_id = client.to_condition_id(data.condition_text)
    if condition_id is None:
        raise HTTPException(status_code=400, detail=f"Unsupported condition '{data.condition_text}'")

    length = _parse_float_or_none(data.dimensions.get("length"))
    width = _parse_float_or_none(data.dimensions.get("width"))
    height = _parse_float_or_none(data.dimensions.get("height"))
    weight = _parse_float_or_none(data.dimensions.get("weight"))

    if identity is not None:
        updates: dict[str, object] = {}
        if identity.dimension_length is None and length is not None:
            updates["dimension_length"] = round(length, 2)
        if identity.dimension_width is None and width is not None:
            updates["dimension_width"] = round(width, 2)
        if identity.dimension_height is None and height is not None:
            updates["dimension_height"] = round(height, 2)
        if identity.weight is None and weight is not None:
            updates["weight"] = round(weight, 2)
        if updates:
            for key, value in updates.items():
                setattr(identity, key, value)
            db.add(identity)
            await db.flush()
            await db.refresh(identity)

    length = length if length is not None else _parse_float_or_none(getattr(identity, "dimension_length", None))
    width = width if width is not None else _parse_float_or_none(getattr(identity, "dimension_width", None))
    height = height if height is not None else _parse_float_or_none(getattr(identity, "dimension_height", None))
    weight = weight if weight is not None else _parse_float_or_none(getattr(identity, "weight", None))
    shipping_package_details = client.to_shipping_package_details(
        weight_lbs=weight,
        length_in=length,
        width_in=width,
        height_in=height,
    )
    if shipping_package_details is None:
        raise HTTPException(
            status_code=400,
            detail="Dimensions and weight are required to build ShippingPackageDetails",
        )

    specifics = client.to_item_specifics(
        brand=data.brand,
        mpn=data.mpn or variant.full_sku,
        color=data.color,
        upc=data.upc,
        extra_specifics=[{"name": s.name, "value": s.value} for s in data.extra_specifics],
    )
    if not specifics:
        raise HTTPException(status_code=400, detail="At least one item specific is required")

    payload = {
        "title": data.title,
        "description": data.description,
        "category_id": data.category_id,
        "price": data.price,
        "quantity": data.quantity,
        "condition_id": condition_id,
        "country": country,
        "currency": currency,
        "dispatch_time_max": dispatch_time_max,
        "location": location or postal_code,
        "postal_code": postal_code or location,
        "sku": variant.full_sku,
        "picture_urls": picture_urls,
        "item_specifics": specifics,
        "shipping_package_details": shipping_package_details,
        "payment_profile_id": payment_profile_id,
        "return_profile_id": return_profile_id,
        "shipping_profile_id": shipping_profile_id,
    }
    publish_result = await client.add_fixed_price_item(payload)
    item_id = str(publish_result["item_id"])
    platform_metadata = {
        "category_id": data.category_id,
        "picture_urls": picture_urls,
        "item_specifics": specifics,
        "seller_profiles": {
            "payment_profile_id": payment_profile_id,
            "return_profile_id": return_profile_id,
            "shipping_profile_id": shipping_profile_id,
        },
        "dispatch_time_max": dispatch_time_max,
        "shipping_package_details": shipping_package_details,
    }

    listing_data = {
        "variant_id": variant.id,
        "platform": data.platform,
        "external_ref_id": item_id,
        "merchant_sku": variant.full_sku,
        "listed_name": data.title,
        "listed_description": data.description,
        "listing_price": data.price,
        "listing_quantity": data.quantity,
        "listing_condition": data.condition_text,
        "upc": data.upc,
        "platform_metadata": platform_metadata,
        "sync_status": PlatformSyncStatus.SYNCED,
        "last_synced_at": datetime.now(),
        "sync_error_message": None,
    }
    if existing:
        listing = await listing_repo.update(existing, listing_data)
    else:
        listing = await listing_repo.create(listing_data)

    return EbayPublishResponse(
        listing_id=listing.id,
        platform=data.platform,
        variant_id=variant.id,
        item_id=item_id,
        sync_status=listing.sync_status,
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
