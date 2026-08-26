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
from sqlalchemy import select, or_, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminOrSalesUser
from app.core.config import settings
from app.core.database import get_db
from app.integrations.ebay.client import EbayClient
from app.integrations.shopify.client import ShopifyClient
from app.models import Platform, PlatformSyncStatus
from app.models.entities import ProductVariant, ProductIdentity, ProductFamily, PlatformListing, BundleComponent
from app.repositories import PlatformListingRepository, ProductVariantRepository
from app.modules.inventory.schemas import (
    AISuggestRequest,
    AISuggestResponse,
    AISuggestion,
    CompareField,
    CompareRequest,
    CompareResponse,
    GraphEdge,
    GraphTopologyResponse,
    GroupHub,
    ListingNode,
    LockRelationshipRequest,
    LockRelationshipResponse,
    PaginatedResponse,
    PlatformListingCreate,
    PlatformListingMatchRequest,
    PlatformListingResponse,
    PlatformListingUpdate,
    ProductNode,
    RelationshipType,
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
    "shopify": Platform.SHOPIFY,
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


@router.post("/import/shopify", response_model=dict[str, Any])
async def import_shopify_listings(
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Import all products and variants from Shopify into PlatformListing.
    
    Auto-links each variant to existing ERP ProductVariant by matching SKU
    against ProductVariant.full_sku or matching Ecwid PlatformListing.
    """
    shopify = ShopifyClient(
        shop_url=settings.shopify_shop_url,
        access_token=settings.shopify_access_token,
        api_version=settings.shopify_api_version,
    )
    
    # Test connection first
    conn = await shopify.test_connection()
    if not conn.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Shopify connection failed: {conn.get('error')}",
        )
    
    products = await shopify.get_all_products()
    listing_repo = PlatformListingRepository(db)
    variant_repo = ProductVariantRepository(db)
    
    created = 0
    updated = 0
    matched = 0
    unmatched = 0
    errors: list[str] = []
    
    for item in products:
        variant_gid = item.get("variant_id")
        if not variant_gid:
            continue
        
        sku = (item.get("sku") or "").strip()
        price_val = float(item["price"]) if item.get("price") else None
        qty_val = item.get("inventory_quantity")
        listed_title = f"{item.get('product_title', '')} - {item.get('variant_title', '')}".strip(" -")
        
        # 1. Attempt to match ERP variant by SKU
        matched_variant_id: int | None = None
        if sku:
            variant = await variant_repo.get_by_sku(sku)
            if variant:
                matched_variant_id = variant.id
            else:
                # Fallback: check if an Ecwid listing has this merchant_sku with a variant_id
                ecwid_listing = await listing_repo.get_by_external_ref(Platform.ECWID, sku)
                if ecwid_listing and ecwid_listing.variant_id:
                    matched_variant_id = ecwid_listing.variant_id
        
        if matched_variant_id:
            matched += 1
        else:
            unmatched += 1
            
        listing_data = {
            "variant_id": matched_variant_id,
            "platform": Platform.SHOPIFY,
            "external_ref_id": variant_gid,
            "merchant_sku": sku or None,
            "listed_name": listed_title or None,
            "listing_price": price_val,
            "listing_quantity": qty_val,
            "sync_status": PlatformSyncStatus.SYNCED if matched_variant_id else PlatformSyncStatus.PENDING,
        }
        
        try:
            existing = await listing_repo.get_by_external_ref(Platform.SHOPIFY, variant_gid)
            if existing:
                update_fields = {}
                if price_val is not None:
                    update_fields["listing_price"] = price_val
                if qty_val is not None:
                    update_fields["listing_quantity"] = qty_val
                if listed_title:
                    update_fields["listed_name"] = listed_title
                if sku:
                    update_fields["merchant_sku"] = sku
                if existing.variant_id is None and matched_variant_id is not None:
                    update_fields["variant_id"] = matched_variant_id
                    update_fields["sync_status"] = PlatformSyncStatus.SYNCED
                
                if update_fields:
                    await listing_repo.update(existing, update_fields)
                updated += 1
            else:
                await listing_repo.create(listing_data)
                created += 1
        except Exception as e:
            msg = f"Failed to save Shopify variant {variant_gid} ({sku}): {e}"
            logger.error(msg)
            errors.append(msg)
            
    return {
        "created": created,
        "updated": updated,
        "matched": matched,
        "unmatched": unmatched,
        "total": len(products),
        "errors": errors[:100],
    }


# ============================================================================
# GRAPH & AI RELATIONSHIP MANAGEMENT
# ============================================================================

@router.get("/graph/{variant_id}", response_model=GraphTopologyResponse)
async def get_variant_graph_topology(
    variant_id: int,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Get knowledge graph topology for a product variant and its linked platform listings.
    """
    stmt = (
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.identity).selectinload(ProductIdentity.family),
        )
        .where(ProductVariant.id == variant_id)
    )
    result = await db.execute(stmt)
    variant = result.scalar_one_or_none()

    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {variant_id} not found"
        )

    product_node = ProductNode(
        variant_id=variant.id,
        full_sku=variant.full_sku,
        variant_name=variant.variant_name,
        thumbnail_url=variant.thumbnail_url,
        identity_name=variant.identity.identity_name if variant.identity else None,
        family_name=variant.identity.family.base_name if variant.identity and variant.identity.family else None,
        family_code=variant.identity.family.family_code if variant.identity and variant.identity.family else None,
        condition_code=variant.condition_code.value if variant.condition_code else None,
        color_code=variant.color_code,
    )

    listings_stmt = select(PlatformListing).where(PlatformListing.variant_id == variant.id)
    listings_result = await db.execute(listings_stmt)
    listings = listings_result.scalars().all()

    listing_nodes = []
    edges = []
    for listing in listings:
        meta_rel = None
        if listing.platform_metadata and isinstance(listing.platform_metadata, dict):
            meta_rel = listing.platform_metadata.get("relationship_type")
        
        if meta_rel and meta_rel in RelationshipType.__members__:
            rel_type = RelationshipType(meta_rel)
        else:
            lname = (listing.listed_name or "").lower()
            vname = (variant.variant_name or "").lower()
            if "bundle" in lname or "package" in lname:
                rel_type = RelationshipType.BUNDLE
            elif any(kw in lname for kw in ["bracket", "adapter", "cable", "remote", "antenna", "dock", "mount", "stand"]) and not any(kw in vname for kw in ["bracket", "adapter", "cable", "remote", "antenna", "dock", "mount", "stand"]):
                rel_type = RelationshipType.ACCESSORY
            else:
                rel_type = RelationshipType.EXACT

        listing_nodes.append(ListingNode(
            listing_id=listing.id,
            variant_id=listing.variant_id,
            platform=listing.platform,
            external_ref_id=listing.external_ref_id,
            merchant_sku=listing.merchant_sku,
            listed_name=listing.listed_name,
            listing_price=float(listing.listing_price) if listing.listing_price is not None else None,
            listing_quantity=listing.listing_quantity,
            sync_status=listing.sync_status,
            relationship_type=rel_type,
            last_synced_at=listing.last_synced_at,
            sync_error_message=listing.sync_error_message,
        ))
        edges.append(GraphEdge(
            source="product",
            target=f"listing-{listing.id}",
            relationship=rel_type.value.lower(),
            relationship_type=rel_type,
        ))

    # Query related products within same family (accessories, parts, bundles, sibling variants)
    related_products_nodes = []
    hubs: list[GroupHub] = []

    # Track hub membership
    variant_hub_children: list[str] = []
    accessory_hub_children: list[str] = []
    component_hub_children: list[str] = []

    if variant.identity and variant.identity.product_id:
        family_id = variant.identity.product_id

        # 1. Fetch sibling variants (same family, different identity or color/condition)
        rel_stmt = (
            select(ProductVariant)
            .join(ProductIdentity, ProductVariant.identity_id == ProductIdentity.id)
            .options(selectinload(ProductVariant.identity).selectinload(ProductIdentity.family))
            .where(
                ProductIdentity.product_id == family_id,
                ProductVariant.id != variant.id,
            )
            .limit(15)
        )
        rel_res = await db.execute(rel_stmt)
        rel_variants = rel_res.scalars().all()

        for rv in rel_variants:
            rv_type = rv.identity.type.value if rv.identity and rv.identity.type else "Product"
            node_id = f"related-product-{rv.id}"

            node = ProductNode(
                variant_id=rv.id,
                full_sku=rv.full_sku,
                variant_name=rv.variant_name,
                thumbnail_url=rv.thumbnail_url,
                identity_name=rv.identity.identity_name if rv.identity else None,
                family_name=rv.identity.family.base_name if rv.identity and rv.identity.family else None,
                family_code=rv.identity.family.family_code if rv.identity and rv.identity.family else None,
                condition_code=rv.condition_code.value if rv.condition_code else None,
                color_code=rv.color_code,
                identity_type=rv_type,
            )
            related_products_nodes.append(node)

            # Classify into hub groups
            if rv_type in ["P"]:
                accessory_hub_children.append(node_id)
                rv_rel = RelationshipType.ACCESSORY
            elif rv_type in ["B", "K"]:
                # Bundles/Kits in same family → they are sibling products
                variant_hub_children.append(node_id)
                rv_rel = RelationshipType.SIBLING_VARIANT
            else:
                # Standard sibling variants (same product, different color/condition)
                variant_hub_children.append(node_id)
                rv_rel = RelationshipType.SIBLING_VARIANT

            edges.append(GraphEdge(
                source="product",
                target=node_id,
                relationship=rv_rel.value.lower(),
                relationship_type=rv_rel,
            ))

        # 2. Fetch Kit/Bundle components (children of this product's identity)
        if variant.identity_id:
            comp_stmt = (
                select(BundleComponent)
                .options(
                    selectinload(BundleComponent.child).selectinload(ProductIdentity.variants),
                    selectinload(BundleComponent.child).selectinload(ProductIdentity.family),
                )
                .where(BundleComponent.parent_identity_id == variant.identity_id)
            )
            comp_res = await db.execute(comp_stmt)
            components = comp_res.scalars().all()

            seen_ids = {rv.id for rv in rel_variants}
            for comp in components:
                child_identity = comp.child
                if not child_identity or not child_identity.variants:
                    continue
                cv = child_identity.variants[0]
                if cv.id in seen_ids or cv.id == variant.id:
                    continue
                seen_ids.add(cv.id)

                node_id = f"related-product-{cv.id}"
                cv_type = child_identity.type.value if child_identity.type else "Product"

                related_products_nodes.append(ProductNode(
                    variant_id=cv.id,
                    full_sku=cv.full_sku,
                    variant_name=cv.variant_name,
                    identity_name=child_identity.identity_name,
                    family_name=child_identity.family.base_name if child_identity.family else None,
                    family_code=child_identity.family.family_code if child_identity.family else None,
                    identity_type=cv_type,
                ))
                component_hub_children.append(node_id)
                edges.append(GraphEdge(
                    source="product",
                    target=node_id,
                    relationship="kit_component" if variant.identity.type and variant.identity.type.value == "K" else "bundle_component",
                    relationship_type=RelationshipType.KIT_COMPONENT if variant.identity.type and variant.identity.type.value == "K" else RelationshipType.BUNDLE_COMPONENT,
                ))

    # Build hub nodes (only if they have children)
    if variant_hub_children:
        hubs.append(GroupHub(
            hub_id="hub-variants",
            hub_label="Variants",
            hub_type="variants",
            children_ids=variant_hub_children,
        ))
    if accessory_hub_children:
        hubs.append(GroupHub(
            hub_id="hub-accessory",
            hub_label="Accessory",
            hub_type="accessory",
            children_ids=accessory_hub_children,
        ))
    if component_hub_children:
        hubs.append(GroupHub(
            hub_id="hub-component",
            hub_label="Component",
            hub_type="component",
            children_ids=component_hub_children,
        ))

    return GraphTopologyResponse(
        product=product_node,
        listings=listing_nodes,
        related_products=related_products_nodes,
        edges=edges,
        hubs=hubs,
    )


@router.post("/suggest", response_model=AISuggestResponse)
async def suggest_listing_matches(
    request: AISuggestRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    AI-powered listing match suggestions for a product variant.
    Computes match confidence (0.0 - 1.0) and reasoning using Gemini AI with fallback.
    """
    # 1. Fetch target variant
    stmt = (
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.identity).selectinload(ProductIdentity.family)
        )
        .where(ProductVariant.id == request.variant_id)
    )
    res = await db.execute(stmt)
    variant = res.scalar_one_or_none()
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {request.variant_id} not found"
        )

    target_sku = variant.full_sku.strip()
    target_sku_prefix = target_sku.split("-")[0] if "-" in target_sku else target_sku
    target_name = (variant.variant_name or "").strip()
    identity_name = (variant.identity.identity_name or "") if variant.identity else ""
    family_name = (variant.identity.family.base_name or "") if variant.identity and variant.identity.family else ""

    # 2. Query candidate listings
    query = select(PlatformListing)
    if not request.include_linked:
        query = query.where(PlatformListing.variant_id.is_(None))
    else:
        query = query.where(
            or_(PlatformListing.variant_id.is_(None), PlatformListing.variant_id != request.variant_id)
        )

    if request.platforms:
        query = query.where(PlatformListing.platform.in_(request.platforms))

    candidates_result = await db.execute(query.limit(200))
    candidate_listings = candidates_result.scalars().all()

    if not candidate_listings:
        return AISuggestResponse(
            variant_id=variant.id,
            variant_sku=variant.full_sku,
            variant_name=variant.variant_name,
            suggestions=[],
        )

    # Pre-score candidates using string overlap heuristics
    target_tokens = set(f"{target_sku} {target_name} {identity_name} {family_name}".lower().split())
    target_tokens.discard("")

    scored_candidates = []
    for cand in candidate_listings:
        cand_text = f"{cand.merchant_sku or ''} {cand.listed_name or ''}".lower()
        cand_tokens = set(cand_text.split())

        overlap = len(target_tokens & cand_tokens)
        sku_match = target_sku_prefix.lower() in cand_text

        base_score = 0.1
        if sku_match:
            base_score += 0.4
        if overlap > 0:
            base_score += min(0.4, overlap * 0.1)

        scored_candidates.append((base_score, cand))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = [c for _, c in scored_candidates[:min(15, len(scored_candidates))]]

    # 3. Use Gemini AI for deep semantic scoring if API key is available
    suggestions: list[AISuggestion] = []
    ai_used = False

    if settings.gemini_api_key:
        try:
            client = genai.Client(api_key=settings.gemini_api_key)
            candidates_prompt_data = [
                {
                    "listing_id": c.id,
                    "platform": c.platform.value,
                    "sku": c.merchant_sku,
                    "title": c.listed_name,
                    "price": float(c.listing_price) if c.listing_price else None,
                }
                for c in top_candidates
            ]

            prompt = f"""
            You are an AI product matching engine for an ERP catalog system adhering to the USAV Product Identification Specification (UPIS).
            We need to match an internal ERP Product Variant against candidate marketplace listings and classify their semantic relationship.

            TARGET ERP PRODUCT:
            - Full SKU: "{target_sku}"
            - Variant Name: "{target_name}"
            - Identity Component: "{identity_name}"
            - Family / Brand: "{family_name}"

            CANDIDATE LISTINGS:
            {json.dumps(candidates_prompt_data, indent=2)}

            Evaluate how each candidate listing relates to the Target ERP Product:
            - EXACT: The candidate is the exact same standalone physical product.
            - ACCESSORY: The candidate is a compatible accessory or attachment (e.g. bluetooth adapter, wall bracket, remote, link cable, stand).
            - BUNDLE_COMPONENT: The candidate is a dynamic USAV bundle (Type B) containing this product plus other items.
            - KIT_COMPONENT: The candidate is a component of a predefined manufacturer kit (Type K) (e.g. satellite speaker, subwoofer, media center).
            - PART_LCI: The candidate is an internal replacement part or LCI component (Type P) (e.g. motherboard, laser lens, display board, power supply).

            For each candidate, output a JSON object with:
            - listing_id: integer
            - relationship_type: "EXACT" | "ACCESSORY" | "BUNDLE_COMPONENT" | "KIT_COMPONENT" | "PART_LCI"
            - confidence: float between 0.00 and 1.00 (e.g. 0.95 for exact/high match, 0.50 for probable, 0.10 for unlikely)
            - reasons: list of short strings explaining the match factors (e.g. "Includes Bluetooth adapter accessory", "SKU prefix match", "Laser lens replacement part")

            Output ONLY a valid JSON array of objects, with no markdown code fences or backticks.
            """

            response = client.models.generate_content(
                model=settings.gemini_model_name,
                contents=prompt
            )
            raw_text = (response.text or "").strip()
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                raw_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

            parsed_ai = json.loads(raw_text)
            ai_scores = {item["listing_id"]: item for item in parsed_ai if "listing_id" in item}

            cand_map = {c.id: c for c in top_candidates}
            for lid, ai_item in ai_scores.items():
                if lid in cand_map:
                    c = cand_map[lid]
                    conf = float(ai_item.get("confidence", 0.0))
                    conf = max(0.0, min(1.0, conf))
                    rel_raw = str(ai_item.get("relationship_type", "EXACT")).upper()
                    # Map legacy names if returned by LLM
                    if rel_raw == "BUNDLE":
                        rel_raw = "BUNDLE_COMPONENT"
                    elif rel_raw == "PART":
                        rel_raw = "PART_LCI"
                    rel_type = RelationshipType(rel_raw) if rel_raw in RelationshipType.__members__ else RelationshipType.EXACT
                    reasons = ai_item.get("reasons", [])
                    if not isinstance(reasons, list):
                        reasons = [str(reasons)]
                    suggestions.append(AISuggestion(
                        listing_id=c.id,
                        platform=c.platform,
                        external_ref_id=c.external_ref_id,
                        merchant_sku=c.merchant_sku,
                        listed_name=c.listed_name,
                        listing_price=float(c.listing_price) if c.listing_price is not None else None,
                        relationship_type=rel_type,
                        confidence=round(conf, 2),
                        reasons=reasons,
                    ))
            ai_used = True
        except Exception as e:
            logger.warning("Gemini AI matching fallback triggered: %s", e)
            ai_used = False

    # Fallback to rule-based scoring if AI wasn't used or returned empty
    if not ai_used or not suggestions:
        suggestions = []
        for score, c in scored_candidates[:request.limit]:
            reasons = []
            lname = (c.listed_name or "").lower()
            if "bundle" in lname or "package" in lname or "with" in lname:
                rel_type = RelationshipType.BUNDLE_COMPONENT
                reasons.append("Multi-item bundle detected in title")
            elif any(kw in lname for kw in ["lens", "laser", "board", "motor", "pcb", "drive", "supply", "chassis"]):
                rel_type = RelationshipType.PART_LCI
                reasons.append("Replacement part / LCI component detected")
            elif any(kw in lname for kw in ["bracket", "adapter", "cable", "remote", "antenna", "dock", "mount", "stand"]):
                rel_type = RelationshipType.ACCESSORY
                reasons.append("Compatible accessory / attachment keyword detected")
            else:
                rel_type = RelationshipType.EXACT

            if target_sku_prefix and c.merchant_sku and target_sku_prefix.lower() in c.merchant_sku.lower():
                reasons.append(f"SKU prefix '{target_sku_prefix}' matches")
            if family_name and c.listed_name and family_name.lower() in c.listed_name.lower():
                reasons.append(f"Product family '{family_name}' found in title")
            if not reasons:
                reasons.append("Keyword / token similarity")
            suggestions.append(AISuggestion(
                listing_id=c.id,
                platform=c.platform,
                external_ref_id=c.external_ref_id,
                merchant_sku=c.merchant_sku,
                listed_name=c.listed_name,
                listing_price=float(c.listing_price) if c.listing_price is not None else None,
                relationship_type=rel_type,
                confidence=round(min(1.0, score), 2),
                reasons=reasons,
            ))

    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    suggestions = suggestions[:request.limit]

    return AISuggestResponse(
        variant_id=variant.id,
        variant_sku=variant.full_sku,
        variant_name=variant.variant_name,
        suggestions=suggestions,
    )


@router.post("/lock-relationship", response_model=LockRelationshipResponse)
async def lock_listing_relationship(
    request: LockRelationshipRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Lock a platform listing to an internal product variant.
    Permanently establishes the graph relationship and optionally enriches variant metadata.
    """
    listing_repo = PlatformListingRepository(db)
    variant_repo = ProductVariantRepository(db)

    listing = await listing_repo.get(request.listing_id)
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform listing {request.listing_id} not found"
        )

    variant = await variant_repo.get(request.variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {request.variant_id} not found"
        )

    listing.variant_id = variant.id
    listing.sync_status = PlatformSyncStatus.SYNCED
    listing.last_synced_at = datetime.now()
    listing.sync_error_message = None

    current_meta = dict(listing.platform_metadata or {})
    current_meta["relationship_type"] = request.relationship_type.value
    listing.platform_metadata = current_meta

    enriched_fields: list[str] = []
    if request.enrich_metadata:
        if not variant.variant_name and listing.listed_name:
            variant.variant_name = listing.listed_name
            enriched_fields.append("variant_name")

        if listing.upc:
            current_meta["locked_upc"] = listing.upc
            listing.platform_metadata = current_meta
            enriched_fields.append("upc")

    await db.commit()

    return LockRelationshipResponse(
        success=True,
        listing_id=listing.id,
        variant_id=variant.id,
        platform=listing.platform,
        relationship_type=request.relationship_type,
        enriched_fields=enriched_fields,
        message=f"Listing {listing.id} successfully locked to variant {variant.full_sku} as {request.relationship_type.value}",
    )


@router.post("/compare", response_model=CompareResponse)
async def compare_listing_nodes(
    request: CompareRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Compare 2 to 10 platform listing nodes side-by-side.
    """
    stmt = (
        select(PlatformListing)
        .where(PlatformListing.id.in_(request.listing_ids))
    )
    result = await db.execute(stmt)
    listings = result.scalars().all()

    found_ids = {l.id for l in listings}
    missing_ids = set(request.listing_ids) - found_ids
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Listings not found for IDs: {list(missing_ids)}"
        )

    listing_map = {l.id: l for l in listings}
    ordered_listings = [listing_map[lid] for lid in request.listing_ids]

    listing_nodes = [
        ListingNode(
            listing_id=l.id,
            variant_id=l.variant_id,
            platform=l.platform,
            external_ref_id=l.external_ref_id,
            merchant_sku=l.merchant_sku,
            listed_name=l.listed_name,
            listing_price=float(l.listing_price) if l.listing_price is not None else None,
            listing_quantity=l.listing_quantity,
            sync_status=l.sync_status,
            last_synced_at=l.last_synced_at,
            sync_error_message=l.sync_error_message,
        )
        for l in ordered_listings
    ]

    comparison_fields = [
        CompareField(
            key="platform",
            label="Platform",
            values={str(l.id): l.platform.value for l in ordered_listings},
        ),
        CompareField(
            key="listed_name",
            label="Listed Title",
            values={str(l.id): l.listed_name for l in ordered_listings},
        ),
        CompareField(
            key="merchant_sku",
            label="Merchant SKU",
            values={str(l.id): l.merchant_sku for l in ordered_listings},
        ),
        CompareField(
            key="listing_price",
            label="Price ($)",
            values={str(l.id): float(l.listing_price) if l.listing_price is not None else None for l in ordered_listings},
        ),
        CompareField(
            key="listing_quantity",
            label="Stock Quantity",
            values={str(l.id): l.listing_quantity for l in ordered_listings},
        ),
        CompareField(
            key="listing_condition",
            label="Condition",
            values={str(l.id): l.listing_condition for l in ordered_listings},
        ),
        CompareField(
            key="listing_type",
            label="Listing Type",
            values={str(l.id): l.listing_type for l in ordered_listings},
        ),
        CompareField(
            key="sync_status",
            label="Sync Status",
            values={str(l.id): l.sync_status.value for l in ordered_listings},
        ),
        CompareField(
            key="last_synced_at",
            label="Last Synced",
            values={str(l.id): l.last_synced_at.isoformat() if l.last_synced_at else None for l in ordered_listings},
        ),
        CompareField(
            key="external_ref_id",
            label="External Ref ID",
            values={str(l.id): l.external_ref_id for l in ordered_listings},
        ),
    ]

    return CompareResponse(
        listing_ids=request.listing_ids,
        listings=listing_nodes,
        comparison_fields=comparison_fields,
    )


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
