"""
Platform Listing API endpoints.
Manages listings for external platforms (Zoho, Amazon, eBay, etc.).
"""
import logging
import json
import shutil
import csv
import ast
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminOrSalesUser
from app.core.config import settings
from app.core.database import get_db
from app.integrations.ebay.client import EbayClient
from app.models import Platform, PlatformSyncStatus
from app.models.entities import ProductVariant, ProductIdentity, ProductFamily
from app.repositories import PlatformListingRepository, ProductVariantRepository
from app.modules.inventory.schemas import (
    PlatformListingMatchRequest,
    PaginatedResponse,
    PlatformListingCreate,
    PlatformListingResponse,
    PlatformListingUpdate,
)
from app.modules.inventory.schemas.ebay_listing import (
    EbayAccountResponse,
    EbayCategorySuggestion,
    EbayCategoryAspect,
    EbayCategoryAspectValue,
    EbayCategoryCondition,
    EbayPublishRequest,
    EbayPublishResponse,
    EbayShortenTitleRequest,
    EbayShortenTitleResponse,
    EbayGenerateDescriptionRequest,
    EbayGenerateDescriptionResponse,
    EbaySuggestDetailsRequest,
    EbaySuggestDetailsResponse,
    EbayAspectValue,
)
from google import genai

router = APIRouter(prefix="/listings", tags=["Platform Listings"])
logger = logging.getLogger(__name__)


_CSV_PLATFORM_MAP: dict[str, Platform] = {
    "amazon": Platform.AMAZON,
    "ebay_mekong": Platform.EBAY_MEKONG,
    "ebay_usav": Platform.EBAY_USAV,
    "ebay_dragon": Platform.EBAY_DRAGON,
    "ecwid": Platform.ECWID,
    "walmart": Platform.WALMART,
}


def _normalize_csv_token(value: str | None) -> str:
    token = (value or "").strip().strip("'").strip('"').strip()
    return token.lower()


def _extract_first_listish_value(raw_value: str | None) -> str | None:
    raw = (raw_value or "").strip()
    if not raw:
        return None
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list) and parsed:
                first = str(parsed[0]).strip()
                return first or None
        except Exception:
            return None
    return raw






































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


@router.post("/import/csv", response_model=dict[str, Any])
async def import_platform_listings_csv(
    _user: AdminOrSalesUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk import platform listings from CSV.

    Expected columns:
    - item_id -> external_ref_id
    - item_name or listing_name -> listed_name
    - inventory_db_sku_primary -> ProductVariant.full_sku
    - platform
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(text.splitlines())
    required = {"item_id", "platform", "inventory_db_sku_primary"}
    headers = set(reader.fieldnames or [])
    missing = [col for col in sorted(required) if col not in headers]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required CSV columns: {', '.join(missing)}")

    listing_repo = PlatformListingRepository(db)
    variant_repo = ProductVariantRepository(db)

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    created_logs: list[str] = []
    updated_logs: list[str] = []

    for row_number, row in enumerate(reader, start=2):
        external_ref_id = (row.get("item_id") or "").strip()
        if not external_ref_id:
            skipped += 1
            message = f"row {row_number}: missing item_id"
            errors.append(message)
            logger.warning("Listings CSV import skipped: %s", message)
            continue

        platform_raw = _extract_first_listish_value(row.get("platform"))
        platform_key = _normalize_csv_token(platform_raw)
        platform = _CSV_PLATFORM_MAP.get(platform_key)
        if not platform:
            skipped += 1
            message = f"row {row_number}: unsupported platform '{row.get('platform')}'"
            errors.append(message)
            logger.warning("Listings CSV import skipped: %s", message)
            continue

        sku = (row.get("inventory_db_sku_primary") or "").strip()
        if not sku:
            skipped += 1
            message = f"row {row_number}: missing inventory_db_sku_primary"
            errors.append(message)
            logger.warning("Listings CSV import skipped: %s", message)
            continue

        variant = await variant_repo.get_by_sku(sku)
        if not variant:
            skipped += 1
            message = f"row {row_number}: variant not found for SKU '{sku}'"
            errors.append(message)
            logger.warning("Listings CSV import skipped: %s", message)
            continue

        listed_name = _extract_first_listish_value(row.get("listing_name")) or _extract_first_listish_value(row.get("item_name"))
        listing_data = {
            "variant_id": variant.id,
            "platform": platform,
            "external_ref_id": external_ref_id,
            "merchant_sku": variant.full_sku,
            "listed_name": (listed_name or "").strip() or None,
            "sync_status": PlatformSyncStatus.PENDING,
        }

        existing = await listing_repo.get_by_external_ref(platform, external_ref_id)
        if existing:
            changed_fields: list[str] = []
            if existing.variant_id != listing_data["variant_id"]:
                changed_fields.append("variant_id")
            if existing.merchant_sku != listing_data["merchant_sku"]:
                changed_fields.append("merchant_sku")
            if existing.listed_name != listing_data["listed_name"]:
                changed_fields.append("listed_name")
            if existing.sync_status != listing_data["sync_status"]:
                changed_fields.append("sync_status")
            await listing_repo.update(existing, listing_data)
            updated += 1
            summary = ", ".join(changed_fields) if changed_fields else "no field changes"
            log_line = (
                f"row {row_number}: updated listing_id={existing.id}, platform={platform.value}, "
                f"external_ref_id={external_ref_id}, sku={variant.full_sku}, changed={summary}"
            )
            updated_logs.append(log_line)
            logger.info("Listings CSV import update: %s", log_line)
        else:
            created_listing = await listing_repo.create(listing_data)
            created += 1
            log_line = (
                f"row {row_number}: created listing_id={created_listing.id}, platform={platform.value}, "
                f"external_ref_id={external_ref_id}, sku={variant.full_sku}"
            )
            created_logs.append(log_line)
            logger.info("Listings CSV import create: %s", log_line)

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total_rows": created + updated + skipped,
        "created_logs": created_logs[:200],
        "updated_logs": updated_logs[:200],
        "errors": errors[:200],
    }


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


@router.post("/{listing_id}/match", response_model=PlatformListingResponse)
async def match_listing_to_variant(
    listing_id: int,
    data: PlatformListingMatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Attach a listing to a variant SKU."""
    listing_repo = PlatformListingRepository(db)
    variant_repo = ProductVariantRepository(db)
    listing = await listing_repo.get(listing_id)
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {listing_id} not found",
        )

    variant = await variant_repo.get(data.variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {data.variant_id} not found",
        )

    existing = await listing_repo.get_by_variant_platform(data.variant_id, listing.platform)
    if existing and existing.id != listing.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Listing for variant {data.variant_id} on {listing.platform.value} already exists",
        )

    listing = await listing_repo.update(
        listing,
        {
            "variant_id": data.variant_id,
            "sync_status": PlatformSyncStatus.PENDING,
            "sync_error_message": None,
        },
    )
    return PlatformListingResponse.model_validate(listing)


@router.post("/{listing_id}/unmatch", response_model=PlatformListingResponse)
async def unmatch_listing_from_variant(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Detach a listing from any variant SKU."""
    repo = PlatformListingRepository(db)
    listing = await repo.get(listing_id)
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {listing_id} not found",
        )

    listing = await repo.update(
        listing,
        {
            "variant_id": None,
            "sync_status": PlatformSyncStatus.PENDING,
            "sync_error_message": None,
        },
    )
    return PlatformListingResponse.model_validate(listing)


@router.post("/{listing_id}/sync", response_model=PlatformListingResponse)
async def queue_listing_sync(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Queue listing for sync (status-only scaffold)."""
    repo = PlatformListingRepository(db)
    listing = await repo.get(listing_id)
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {listing_id} not found",
        )

    listing = await repo.update(
        listing,
        {
            "sync_status": PlatformSyncStatus.PENDING,
            "sync_error_message": None,
        },
    )
    return PlatformListingResponse.model_validate(listing)


# --- eBay Specific Endpoints ---

@router.get("/ebay/accounts", response_model=list[EbayAccountResponse])
async def get_ebay_accounts():
    """Get available eBay store configurations from ebay-accounts.json."""
    import json
    accounts_file = Path("/app/ebay-accounts.json")
    if not accounts_file.is_file():
        raise HTTPException(status_code=404, detail="ebay-accounts.json not found")
    try:
        with open(accounts_file, "r") as f:
            data = json.load(f)
            # rename camelCase to snake_case mapping
            return [
                EbayAccountResponse(
                    id=acc.get("id"),
                    name=acc.get("name"),
                    merchant_location_key=acc.get("merchantLocationKey"),
                    payment_policy_id=acc.get("paymentPolicyId"),
                    return_policy_id=acc.get("returnPolicyId"),
                    return_policy_id_no_returns=acc.get("returnPolicyIdNoReturns"),
                    fulfillment_policy_id_light=acc.get("fulfillmentPolicyIdLight"),
                    fulfillment_policy_id_heavy=acc.get("fulfillmentPolicyIdHeavy"),
                    fulfillment_policy_id_free=acc.get("fulfillmentPolicyIdFree"),
                    heavy_item_threshold_lbs=str(acc.get("heavyItemThresholdLbs", "2"))
                )
                for acc in data
            ]
    except Exception as e:
        logger.exception("Failed to parse ebay-accounts.json")
        raise HTTPException(status_code=500, detail="Failed to parse accounts config")


@router.get("/ebay/categories", response_model=list[EbayCategorySuggestion])
async def get_ebay_category_suggestions(q: str = Query(...), store: str = Query("usav")):
    """Get eBay category suggestions for a search query."""
    client = EbayClient(store)
    try:
        marketplace_id = "EBAY_US"
        tree_id = await client.get_default_category_tree_id(marketplace_id)
        suggestions = await client.get_category_suggestions(tree_id, q)
        # Parse the eBay response to our schema
        results = []
        for sg in suggestions:
            cat = sg.get("category", {})
            results.append(
                EbayCategorySuggestion(
                    categoryId=cat.get("categoryId"),
                    categoryName=cat.get("categoryName"),
                    categoryTreeNodeLevel=cat.get("categoryTreeNodeLevel", 0),
                    categoryTreeNodeAncestors=cat.get("categoryTreeNodeAncestors", [])
                )
            )
        return results
    except Exception as e:
        logger.exception("Failed to get eBay category suggestions")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ebay/categories/{category_id}/aspects", response_model=list[EbayCategoryAspect])
async def get_ebay_category_aspects(category_id: str, store: str = Query("usav")):
    """Get item specifics/aspects required for a category."""
    client = EbayClient(store)
    try:
        marketplace_id = "EBAY_US"
        tree_id = await client.get_default_category_tree_id(marketplace_id)
        aspects = await client.get_item_aspects_for_category(
            category_tree_id=tree_id, category_id=category_id
        )
        results = []
        for asp in aspects:
            constraint = asp.get("aspectConstraint", {})
            values = [{"value": val.get("localizedValue", "")} for val in asp.get("aspectValues", [])]
            results.append(
                EbayCategoryAspect(
                    localizedAspectName=asp.get("localizedAspectName"),
                    aspectConstraint=constraint,
                    aspectValues=values
                )
            )
        return results
    except Exception as e:
        logger.exception("Failed to get eBay category aspects")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ebay/categories/{category_id}/conditions", response_model=list[EbayCategoryCondition])
async def get_ebay_valid_conditions(category_id: str, store: str = Query("usav")):
    """Get valid condition IDs for a category."""
    client = EbayClient(store)
    try:
        marketplace_id = "EBAY_US"
        conditions = await client.get_valid_conditions_for_category(
            marketplace_id=marketplace_id, category_id=category_id
        )
        return [
            EbayCategoryCondition(
                conditionId=cond.get("conditionId"),
                conditionDescription=cond.get("conditionDescription")
            )
            for cond in conditions
        ]
    except Exception as e:
        logger.exception("Failed to get valid conditions")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ebay/ai/shorten-title", response_model=EbayShortenTitleResponse)
async def shorten_title(request: EbayShortenTitleRequest):
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            f"Please shorten the following product title to be under 80 characters, "
            f"optimizing for eBay search. Keep the most important keywords. Do not add any extra text or quotes.\n\n"
            f"Title: {request.title}"
        )
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        new_title = response.text.strip().replace('"', '')
        if len(new_title) > 80:
            new_title = new_title[:80]
        return EbayShortenTitleResponse(title=new_title)
    except Exception as e:
        logger.exception("Failed to shorten title")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ebay/ai/generate-description", response_model=EbayGenerateDescriptionResponse)
async def generate_description(request: EbayGenerateDescriptionRequest):
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    try:
        client = genai.Client(api_key=api_key)
        aspects_text = "\\n".join([f"- {a.name}: {', '.join(a.values)}" for a in request.aspects])
        
        prompt = f"""
        You are an expert eBay seller. Write a professional, concise HTML description for this item.
        Title: {request.title}
        Condition: {request.condition}
        Brand: {request.brand or "Unknown"}
        
        Item Specifics:
        {aspects_text}
        
        Requirements:
        - Output ONLY raw HTML. No markdown code blocks, no ```html wrappers.
        - Start with a <h2> that has the product title.
        - Include a section for Condition.
        - Include a section for Features/Specifications.
        - Keep it clean, use standard HTML tags (p, ul, li, strong).
        - Add a short disclaimer that photos are representative of the condition.
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        html_content = response.text.strip()
        # Clean up any potential markdown wrappers the model might add despite instructions
        if html_content.startswith("```html"):
            html_content = html_content[7:]
        if html_content.startswith("```"):
            html_content = html_content[3:]
        if html_content.endswith("```"):
            html_content = html_content[:-3]
            
        return EbayGenerateDescriptionResponse(description=html_content.strip())
    except Exception as e:
        logger.exception("Failed to generate description")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ebay/ai/suggest-details", response_model=EbaySuggestDetailsResponse)
async def suggest_details(request: EbaySuggestDetailsRequest):
    try:
        # Currently we just use the first available store (usav) for suggesting details
        # because the catalog preview API is marketplace-wide, not store-specific
        client = EbayClient("usav")
        
        # Prepare the external product payload
        external_product = {
            "title": request.title,
            "sku": "temp_sku", # dummy SKU for preview
        }
        if request.description:
            external_product["description"] = request.description
        if request.image_url:
            external_product["imageUrls"] = [request.image_url]
            
        task_id = await client.start_listing_previews_creation(external_product)
        result = await client.poll_listing_previews_task_by_id(task_id)
        
        previews = result.get("listingPreviews", [])
        if not previews:
            return EbaySuggestDetailsResponse()
            
        preview = previews[0]
        cat_info = preview.get("category") or {}
        
        # Format aspects
        ebay_aspects = preview.get("aspects") or []
        formatted_aspects = []
        for aspect in ebay_aspects:
            name = aspect.get("name")
            values = aspect.get("values") or aspect.get("aspectValues") or []
            if name and values:
                formatted_aspects.append(EbayAspectValue(name=name, values=values, required=False))
                
        # Also try to estimate weight if we have gemini
        weight_lbs, weight_oz = None, None
        length, width, height = None, None, None
        
        if settings.GEMINI_API_KEY:
            try:
                gen_client = genai.Client(api_key=settings.GEMINI_API_KEY)
                prompt = (
                    f"Estimate the shipping weight and package dimensions for this item: {request.title}\n"
                    f"Return ONLY a JSON object with these exact keys: weight_lbs, weight_oz, length_inches, width_inches, height_inches. "
                    f"Make reasonable estimates for standard cardboard box shipping. Do not use markdown wrappers."
                )
                res = gen_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                text = res.text.strip()
                if text.startswith("```json"): text = text[7:]
                if text.startswith("```"): text = text[3:]
                if text.endswith("```"): text = text[:-3]
                
                est = json.loads(text.strip())
                weight_lbs = est.get("weight_lbs")
                weight_oz = est.get("weight_oz")
                length = est.get("length_inches")
                width = est.get("width_inches")
                height = est.get("height_inches")
            except Exception as gem_e:
                logger.warning(f"Failed to estimate dimensions via Gemini: {gem_e}")
                
        return EbaySuggestDetailsResponse(
            category_id=cat_info.get("categoryId"),
            category_name=cat_info.get("categoryName"),
            title=preview.get("title"),
            aspects=formatted_aspects,
            weight_lbs=weight_lbs,
            weight_oz=weight_oz,
            package_length=length,
            package_width=width,
            package_height=height
        )
    except Exception as e:
        logger.exception("Failed to suggest details")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ebay/publish", response_model=EbayPublishResponse)
async def publish_ebay_listing(
    request: EbayPublishRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(AdminOrSalesUser),
):
    """Publish a new listing to eBay using the Inventory API."""
    # 1. Validate Variant
    variant_repo = ProductVariantRepository(db)
    variant = await variant_repo.get(request.variant_id)
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")
        
    client = EbayClient(request.store_id)
    
    try:
        # Load accounts config to get policy IDs
        accounts_file = Path("/home/las/USAV/ebay-listing-helper/ebay-accounts.json")
        with open(accounts_file, "r") as f:
            accounts_data = json.load(f)
        
        acc_config = next((a for a in accounts_data if a["id"] == request.store_id), None)
        if not acc_config:
            raise HTTPException(status_code=400, detail="Invalid store_id configuration")
            
        # 2. Upload Images to eBay if they are local
        # For simplicity in this implementation, we will assume image_urls are accessible URLs
        # or we could implement the create_media_image_from_file flow. 
        # In this iteration, we just pass the URLs directly to eBay.
        # If they are local NGINX urls, they must be publicly accessible for eBay to pull them.
        image_urls = request.selected_image_urls
        if not image_urls and variant.thumbnail_url:
            image_urls = [variant.thumbnail_url]
            
        # 3. Create Inventory Item
        # Format aspects into eBay expected format
        aspects_dict = {}
        for asp in request.aspects:
            aspects_dict[asp.name] = asp.values
            
        inventory_payload = {
            "product": {
                "title": request.title[:80],
                "description": request.description,
                "imageUrls": image_urls,
                "aspects": aspects_dict
            },
            "condition": request.condition_id,
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": request.quantity
                }
            },
            "packageWeightAndSize": {
                "weight": {
                    "value": request.weight_lbs + (request.weight_oz / 16.0),
                    "unit": "POUND"
                },
                "dimensions": {
                    "length": request.package_length,
                    "width": request.package_width,
                    "height": request.package_height,
                    "unit": "INCH"
                }
            }
        }
        
        if request.upc:
            inventory_payload["product"]["upc"] = [request.upc]
            
        await client.put_inventory_item(variant.full_sku, inventory_payload)
        
        # 4. Determine Fulfillment Policy
        weight_lbs_total = request.weight_lbs + (request.weight_oz / 16.0)
        heavy_threshold = float(acc_config.get("heavyItemThresholdLbs", 2))
        
        if request.is_free_shipping:
            fulfillment_policy = acc_config.get("fulfillmentPolicyIdFree")
        elif weight_lbs_total > heavy_threshold:
            fulfillment_policy = acc_config.get("fulfillmentPolicyIdHeavy")
        else:
            fulfillment_policy = acc_config.get("fulfillmentPolicyIdLight")
            
        # Determine Return Policy
        return_policy = acc_config.get("returnPolicyIdNoReturns") if request.use_no_returns_policy else acc_config.get("returnPolicyId")

        # 5. Create Offer
        marketplace_id = "EBAY_US"
        offer_payload = {
            "sku": variant.full_sku,
            "marketplaceId": marketplace_id,
            "format": "FIXED_PRICE",
            "availableQuantity": request.quantity,
            "categoryId": request.category_id,
            "listingPolicies": {
                "fulfillmentPolicyId": fulfillment_policy,
                "paymentPolicyId": acc_config.get("paymentPolicyId"),
                "returnPolicyId": return_policy
            },
            "pricingSummary": {
                "price": {
                    "value": str(request.price),
                    "currency": "USD"
                }
            },
            "merchantLocationKey": acc_config.get("merchantLocationKey")
        }
        
        # Check if offer exists
        existing_offer = await client.get_offer_by_sku(variant.full_sku, marketplace_id)
        if existing_offer and existing_offer.get("offerId"):
            offer_id = existing_offer["offerId"]
            await client.update_offer(offer_id, offer_payload)
        else:
            created_offer = await client.create_offer(offer_payload)
            offer_id = created_offer.get("offerId")
            
        if not offer_id:
            raise RuntimeError("Failed to obtain offer ID from eBay")
            
        # 6. Publish Offer
        publish_response = await client.publish_offer(offer_id)
        listing_id = publish_response.get("listingId")
        
        if not listing_id:
            raise RuntimeError(f"Published offer but no listingId returned. Response: {publish_response}")
            
        # 7. Save to DB
        platform_mapping = {
            "usav": Platform.EBAY_USAV,
            "mekong": Platform.EBAY_MEKONG,
            "dragon": Platform.EBAY_DRAGON,
        }
        platform = platform_mapping.get(request.store_id, Platform.EBAY_USAV)
        
        # Check if platform listing already exists
        listing_repo = PlatformListingRepository(db)
        # Assuming we check by variant_id and platform
        stmt = select(listing_repo.model).where(
            listing_repo.model.variant_id == variant.id,
            listing_repo.model.platform == platform
        )
        existing_db_listing_result = await db.execute(stmt)
        existing_db_listing = existing_db_listing_result.scalars().first()
        
        platform_metadata = {
            "ebay_category_id": request.category_id,
            "aspects": [asp.model_dump() for asp in request.aspects],
            "package_weight_lbs": request.weight_lbs,
            "package_weight_oz": request.weight_oz,
            "package_length": request.package_length,
            "package_width": request.package_width,
            "package_height": request.package_height,
            "is_free_shipping": request.is_free_shipping,
            "use_no_returns_policy": request.use_no_returns_policy,
            "offer_id": offer_id,
            "store_id": request.store_id
        }
        
        if existing_db_listing:
            await listing_repo.update(
                existing_db_listing,
                {
                    "external_ref_id": listing_id,
                    "merchant_sku": variant.full_sku,
                    "listed_name": request.title[:500],
                    "listed_description": request.description,
                    "listing_price": request.price,
                    "listing_quantity": request.quantity,
                    "listing_condition": request.condition_id,
                    "upc": request.upc,
                    "sync_status": PlatformSyncStatus.SYNCED,
                    "last_synced_at": datetime.utcnow(),
                    "sync_error_message": None,
                    "platform_metadata": platform_metadata
                }
            )
        else:
            await listing_repo.create(
                {
                    "variant_id": variant.id,
                    "platform": platform,
                    "external_ref_id": listing_id,
                    "merchant_sku": variant.full_sku,
                    "listed_name": request.title[:500],
                    "listed_description": request.description,
                    "listing_price": request.price,
                    "listing_quantity": request.quantity,
                    "listing_condition": request.condition_id,
                    "upc": request.upc,
                    "sync_status": PlatformSyncStatus.SYNCED,
                    "last_synced_at": datetime.utcnow(),
                    "sync_error_message": None,
                    "platform_metadata": platform_metadata
                }
            )
            
        return EbayPublishResponse(listing_id=listing_id, success=True, message="Successfully published to eBay")
        
    except Exception as e:
        logger.exception("Failed to publish eBay listing")
        raise HTTPException(status_code=500, detail=str(e))
