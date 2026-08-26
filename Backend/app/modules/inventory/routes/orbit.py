"""
Orbit View API Endpoints.
Provides interactive catalog management, dual Bundle (B) & Kit (K) creation per USAV UPIS spec,
rapid variant generation (UML Layer 2), sales velocity metrics, and automated Ecwid-Shopify price mismatch alerting.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, case, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminOrSalesUser
from app.core.config import settings
from app.core.database import get_db
from app.models import Platform, PlatformSyncStatus, ConditionCode, IdentityType, InventoryStatus, BundleRole
from app.models.entities import (
    ProductVariant,
    ProductIdentity,
    ProductFamily,
    PlatformListing,
    BundleComponent,
    InventoryItem,
)
from app.modules.orders.models import Order, OrderItem
from app.modules.inventory.schemas.graph import (
    OrbitAnalyticsResponse,
    StockWarningStatus,
    PriceMismatchAlert,
    ChannelSalesMetric,
    SalesTransactionItem,
    OrbitCreateBundleKitRequest,
    OrbitCreateVariantRequest,
    OrbitUpdateRelationshipRequest,
    OrbitUnlinkRequest,
    OrbitConvertTypeRequest,
    ProductNode,
    RelationshipType,
    AIDeepClassifyRequest,
    AIDeepClassifyResponse,
    AIClassifiedComponent,
    AIClassifiedParent,
    BundleDiscoveryResponse,
    BundleParticipation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orbit", tags=["Orbit View & Catalog Operations"])


@router.get("/analytics/{variant_id}", response_model=OrbitAnalyticsResponse)
async def get_orbit_variant_analytics(
    variant_id: int,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Compute real-time sales order velocity, 30d/90d revenue, warehouse available inventory,
    stock runway days, and automated Ecwid ↔ Shopify price mismatch detection.
    """
    variant = await db.get(ProductVariant, variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {variant_id} not found"
        )

    # 1. Order Sales Aggregation (30-day and 90-day windows)
    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=30)
    since_90d = now - timedelta(days=90)

    # Query order items linked to this variant or with matching external SKU
    orders_stmt = (
        select(
            Order.platform,
            func.count(OrderItem.id).label("total_items"),
            func.sum(OrderItem.quantity).label("units_sold"),
            func.sum(OrderItem.total_price).label("gross_revenue"),
            func.sum(
                case((Order.ordered_at >= since_30d, OrderItem.quantity), else_=0)
            ).label("units_30d"),
            func.sum(
                case((Order.ordered_at >= since_30d, OrderItem.total_price), else_=Decimal(0))
            ).label("revenue_30d"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            or_(
                OrderItem.variant_id == variant.id,
                OrderItem.external_sku == variant.full_sku,
            ),
            Order.ordered_at >= since_90d,
        )
        .group_by(Order.platform)
    )
    orders_res = await db.execute(orders_stmt)
    order_rows = orders_res.all()

    total_units_30d = 0
    total_rev_30d = 0.0
    total_units_90d = 0
    total_rev_90d = 0.0
    channel_metrics: list[ChannelSalesMetric] = []

    for row in order_rows:
        p_name = row[0].value if hasattr(row[0], "value") else str(row[0])
        u_90 = int(row[2] or 0)
        r_90 = float(row[3] or 0.0)
        u_30 = int(row[4] or 0)
        r_30 = float(row[5] or 0.0)

        total_units_30d += u_30
        total_rev_30d += r_30
        total_units_90d += u_90
        total_rev_90d += r_90

        channel_metrics.append(ChannelSalesMetric(
            platform=p_name,
            units_sold_30d=u_30,
            revenue_30d=round(r_30, 2),
            units_sold_90d=u_90,
            revenue_90d=round(r_90, 2),
        ))

    monthly_velocity = float(total_units_30d)

    # 2. Available Warehouse Inventory
    inv_stmt = select(func.count(InventoryItem.id)).where(
        InventoryItem.variant_id == variant.id,
        InventoryItem.status == InventoryStatus.AVAILABLE,
    )
    inv_res = await db.execute(inv_stmt)
    available_stock = int(inv_res.scalar() or 0)

    # 3. Runway Days Calculation
    runway_days: Optional[float] = None
    if monthly_velocity > 0:
        daily_burn = monthly_velocity / 30.0
        runway_days = round(available_stock / daily_burn, 1)

    # Determine Stock Warning Status
    if available_stock == 0 and monthly_velocity > 0:
        stock_warning = StockWarningStatus.OUT_OF_STOCK
    elif runway_days is not None and runway_days < 14:
        stock_warning = StockWarningStatus.LOW_STOCK
    else:
        stock_warning = StockWarningStatus.HEALTHY

    # 4. Automated Ecwid vs. Shopify Price Mismatch Detection
    price_alert = PriceMismatchAlert()
    ecwid_price: Optional[float] = None
    shopify_price: Optional[float] = None

    listings_stmt = select(PlatformListing).where(PlatformListing.variant_id == variant.id)
    listings_res = await db.execute(listings_stmt)
    variant_listings = listings_res.scalars().all()

    for l in variant_listings:
        if l.platform == Platform.ECWID and l.listing_price is not None:
            ecwid_price = float(l.listing_price)
        elif l.platform == Platform.SHOPIFY and l.listing_price is not None:
            shopify_price = float(l.listing_price)

    if ecwid_price is not None and shopify_price is not None:
        diff = round(shopify_price - ecwid_price, 2)
        if abs(diff) > 0.01:
            price_alert = PriceMismatchAlert(
                has_mismatch=True,
                ecwid_price=ecwid_price,
                shopify_price=shopify_price,
                price_diff=diff,
                message=f"Price divergence detected: Ecwid (${ecwid_price:.2f}) vs Shopify (${shopify_price:.2f}). Difference: ${abs(diff):.2f}",
            )

    # 5. Fetch Recent Sales Transactions (Last 10 Orders)
    recent_stmt = (
        select(
            Order.id,
            Order.external_order_id,
            Order.external_order_number,
            Order.platform,
            OrderItem.quantity,
            OrderItem.unit_price,
            OrderItem.total_price,
            Order.currency,
            Order.ordered_at,
            Order.status,
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            or_(
                OrderItem.variant_id == variant.id,
                OrderItem.external_sku == variant.full_sku,
            )
        )
        .order_by(Order.ordered_at.desc().nullslast(), Order.id.desc())
        .limit(10)
    )
    recent_res = await db.execute(recent_stmt)
    recent_rows = recent_res.all()

    recent_transactions = [
        SalesTransactionItem(
            order_id=r[0],
            external_order_id=r[1],
            external_order_number=r[2],
            platform=r[3].value if hasattr(r[3], "value") else str(r[3]),
            quantity=int(r[4] or 1),
            unit_price=float(r[5]) if r[5] is not None else None,
            total_price=float(r[6]) if r[6] is not None else None,
            currency=str(r[7] or "USD"),
            ordered_at=r[8],
            status=r[9].value if hasattr(r[9], "value") else str(r[9]) if r[9] else None,
        )
        for r in recent_rows
    ]

    return OrbitAnalyticsResponse(
        variant_id=variant.id,
        full_sku=variant.full_sku,
        units_sold_30d=total_units_30d,
        revenue_30d=round(total_rev_30d, 2),
        units_sold_90d=total_units_90d,
        revenue_90d=round(total_rev_90d, 2),
        monthly_velocity=monthly_velocity,
        available_stock=available_stock,
        runway_days=runway_days,
        stock_warning=stock_warning,
        price_mismatch=price_alert,
        channel_metrics=channel_metrics,
        recent_transactions=recent_transactions,
    )


@router.post("/bundle-kit/create", response_model=ProductNode)
async def create_bundle_or_kit(
    request: OrbitCreateBundleKitRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Form a USAV Bundle (Type B) or Predefined Manufacturer Kit (Type K) per USAV UPIS specification.
    """
    btype_raw = request.type.strip().upper()
    if btype_raw not in ["B", "K"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type must be 'B' (USAV Bundle) or 'K' (Predefined Kit)",
        )

    # 1. Determine ProductID namespace root
    if request.product_id:
        pid = request.product_id
    else:
        # If components are provided, derive from the first component's ProductIdentity
        derived_pid = None
        for comp in request.components:
            child_v = await db.get(ProductVariant, comp.child_variant_id)
            if child_v and child_v.identity_id:
                child_ident = await db.get(ProductIdentity, child_v.identity_id)
                if child_ident:
                    derived_pid = child_ident.product_id
                    break
        if derived_pid:
            pid = derived_pid
        else:
            # Find next available ProductFamily product_id
            max_pid_stmt = select(func.max(ProductFamily.product_id))
            max_pid = (await db.execute(max_pid_stmt)).scalar() or 9000
            pid = max_pid + 1

    family_code = f"{pid:05d}"
    upis_h = f"{family_code}-{btype_raw}"
    hex_sig = f"{family_code}{btype_raw}01"[:8].upper()

    # 2. Find or create ProductFamily
    family = await db.get(ProductFamily, pid)
    if not family:
        family = ProductFamily(
            product_id=pid,
            family_code=family_code,
            base_name=request.name,
        )
        db.add(family)
        await db.flush()

    # 3. Find or create ProductIdentity
    identity_type = IdentityType.B if btype_raw == "B" else IdentityType.K
    ident_stmt = select(ProductIdentity).where(
        ProductIdentity.product_id == family.product_id,
        ProductIdentity.type == identity_type,
    )
    ident_res = await db.execute(ident_stmt)
    identity = ident_res.scalar_one_or_none()

    if not identity:
        identity = ProductIdentity(
            product_id=family.product_id,
            type=identity_type,
            identity_name=request.name,
            generated_upis_h=upis_h,
            hex_signature=hex_sig,
        )
        db.add(identity)
        await db.flush()

    # 4. Add or update Bundle / Kit Component recipes
    for comp in request.components:
        child_var = await db.get(ProductVariant, comp.child_variant_id)
        if child_var and child_var.identity_id:
            # Check if this child recipe already exists
            bc_stmt = select(BundleComponent).where(
                BundleComponent.parent_identity_id == identity.id,
                BundleComponent.child_identity_id == child_var.identity_id,
            )
            bc_existing = (await db.execute(bc_stmt)).scalar_one_or_none()
            if bc_existing:
                bc_existing.quantity_required = comp.quantity_required
            else:
                bc = BundleComponent(
                    parent_identity_id=identity.id,
                    child_identity_id=child_var.identity_id,
                    quantity_required=comp.quantity_required,
                )
                db.add(bc)

    # 5. Find or create default sellable ProductVariant for the Bundle/Kit
    var_stmt = select(ProductVariant).where(
        ProductVariant.identity_id == identity.id,
    )
    var_res = await db.execute(var_stmt)
    bundle_variant = var_res.scalar_one_or_none()

    if not bundle_variant:
        bundle_variant = ProductVariant(
            identity_id=identity.id,
            full_sku=upis_h,
            variant_name=request.name,
            is_active=True,
        )
        db.add(bundle_variant)
        await db.flush()

    await db.commit()
    await db.refresh(bundle_variant)

    return ProductNode(
        variant_id=bundle_variant.id,
        full_sku=bundle_variant.full_sku,
        variant_name=bundle_variant.variant_name,
        identity_name=identity.identity_name,
        family_name=family.base_name,
        family_code=family.family_code,
        identity_type=btype_raw,
    )


@router.post("/convert-type", response_model=ProductNode)
async def convert_product_type(
    request: OrbitConvertTypeRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Fast conversion of a Product Variant to Kit (K), Bundle (B), or Base Product (Product).
    Updates Identity Type, deterministically recalculates UPIS syntax, and attaches component recipes.
    """
    variant = await db.get(ProductVariant, request.variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product variant {request.variant_id} not found",
        )

    identity = await db.get(ProductIdentity, variant.identity_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Identity {variant.identity_id} not found",
        )

    family = await db.get(ProductFamily, identity.product_id)
    if not family:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Family {identity.product_id} not found",
        )

    target_type_raw = request.target_type.strip().upper()
    if target_type_raw == "K":
        identity.type = IdentityType.K
        new_upis_h = f"{family.family_code}-K"
    elif target_type_raw == "B":
        identity.type = IdentityType.B
        new_upis_h = f"{family.family_code}-B"
    else:
        identity.type = IdentityType.PRODUCT
        new_upis_h = family.family_code

    identity.generated_upis_h = new_upis_h

    # Update variant SKU metadata: [UPIS-H]-[Color]-[Condition]
    sku_parts = [new_upis_h]
    if variant.color_code:
        sku_parts.append(variant.color_code)
    if variant.condition_code:
        cond_val = variant.condition_code.value if hasattr(variant.condition_code, "value") else str(variant.condition_code)
        sku_parts.append(cond_val)

    variant.full_sku = "-".join(sku_parts)

    # Attach components if provided
    if request.components:
        for comp in request.components:
            child_v = await db.get(ProductVariant, comp.child_variant_id)
            if child_v and child_v.identity_id:
                bc_stmt = select(BundleComponent).where(
                    BundleComponent.parent_identity_id == identity.id,
                    BundleComponent.child_identity_id == child_v.identity_id,
                )
                bc_existing = (await db.execute(bc_stmt)).scalar_one_or_none()
                if bc_existing:
                    bc_existing.quantity_required = comp.quantity_required
                else:
                    bc = BundleComponent(
                        parent_identity_id=identity.id,
                        child_identity_id=child_v.identity_id,
                        quantity_required=comp.quantity_required,
                    )
                    db.add(bc)

    await db.commit()
    await db.refresh(variant)

    return ProductNode(
        variant_id=variant.id,
        full_sku=variant.full_sku,
        variant_name=variant.variant_name,
        identity_name=identity.identity_name,
        family_name=family.base_name,
        family_code=family.family_code,
        identity_type=identity.type.value if hasattr(identity.type, "value") else str(identity.type),
    )


@router.post("/variant/create", response_model=ProductNode)
async def create_product_variant(
    request: OrbitCreateVariantRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Rapid Variant Creator adhering strictly to USAV UPIS Layer 2 (UML: Color + Condition).
    """
    source_var = await db.get(ProductVariant, request.source_variant_id)
    if not source_var or not source_var.identity_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source variant {request.source_variant_id} not found"
        )

    identity = await db.get(ProductIdentity, source_var.identity_id)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent identity not found"
        )

    color = request.color_code.strip().upper()
    cond_raw = (request.condition_code or "U").strip().upper()
    cond_enum = ConditionCode.N if cond_raw == "N" else ConditionCode.R if cond_raw == "R" else ConditionCode.U

    # Deterministic SKU generation: UPIS-H + Color + Condition
    new_sku = f"{identity.generated_upis_h}-{color}-{cond_enum.value}"

    # Check for duplicate
    dup_stmt = select(ProductVariant).where(ProductVariant.full_sku == new_sku)
    dup = (await db.execute(dup_stmt)).scalar_one_or_none()
    if dup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Variant with SKU '{new_sku}' already exists (ID: {dup.id})"
        )

    v_name = request.variant_name or f"{identity.identity_name or source_var.variant_name or identity.generated_upis_h} ({color})"
    new_variant = ProductVariant(
        identity_id=identity.id,
        full_sku=new_sku,
        variant_name=v_name,
        color_code=color,
        condition_code=cond_enum,
        is_active=True,
    )
    db.add(new_variant)
    await db.commit()
    await db.refresh(new_variant)

    family = await db.get(ProductFamily, identity.product_id)

    return ProductNode(
        variant_id=new_variant.id,
        full_sku=new_variant.full_sku,
        variant_name=new_variant.variant_name,
        identity_name=identity.identity_name,
        family_name=family.base_name if family else None,
        family_code=family.family_code if family else None,
        color_code=new_variant.color_code,
        condition_code=new_variant.condition_code.value if new_variant.condition_code else None,
        identity_type=identity.type.value if identity.type else "Product",
    )


@router.post("/relationship/update")
async def update_orbit_relationship(
    request: OrbitUpdateRelationshipRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Update relationship tether type on a listing or component edge.
    """
    if request.target_type == "listing":
        listing = await db.get(PlatformListing, request.target_id)
        if not listing:
            raise HTTPException(status_code=404, detail="Listing not found")
        meta = dict(listing.platform_metadata or {})
        meta["relationship_type"] = request.relationship_type.value
        listing.platform_metadata = meta
        if request.relationship_type == RelationshipType.EXACT:
            listing.variant_id = request.source_variant_id
        await db.commit()
        return {"success": True, "message": f"Updated listing #{listing.id} relationship to {request.relationship_type.value}"}

    return {"success": True, "message": "Updated relationship"}


@router.post("/relationship/unlink")
async def unlink_orbit_relationship(
    request: OrbitUnlinkRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Unlink a platform listing or sever a component tether.
    """
    if request.target_type == "listing":
        listing = await db.get(PlatformListing, request.target_id)
        if not listing:
            raise HTTPException(status_code=404, detail="Listing not found")
        listing.variant_id = None
        listing.sync_status = PlatformSyncStatus.PENDING
        await db.commit()
        return {"success": True, "message": f"Unlinked listing #{listing.id}"}

    return {"success": True, "message": "Unlinked"}


# ============================================================================
# AI DEEP CLASSIFICATION
# ============================================================================

def _fuzzy_score(query_tokens: set[str], candidate_text: str) -> float:
    """Simple token overlap scoring for local DB matching."""
    cand_tokens = set(candidate_text.lower().split())
    if not query_tokens or not cand_tokens:
        return 0.0
    overlap = len(query_tokens & cand_tokens)
    return overlap / max(len(query_tokens), 1)


@router.post("/ai/deep-classify", response_model=AIDeepClassifyResponse)
async def deep_classify_product(
    request: AIDeepClassifyRequest,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    AI Deep Product Classification (Two-Stage).
    Stage 1: Gemini classifies product type from name + brand (minimal tokens).
    Stage 2: Local DB fuzzy match for suggested components.
    """
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GEMINI_API_KEY is not configured. Deep classification requires AI.",
        )

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
        raise HTTPException(status_code=404, detail=f"Variant {request.variant_id} not found")

    identity = variant.identity
    current_type = identity.type.value if identity and identity.type else "Product"
    full_sku = variant.full_sku
    identity_name = identity.identity_name if identity else (variant.variant_name or "")
    family_name = (identity.family.base_name if identity and identity.family else "") or ""

    # Stage 1: Gemini classification (token-minimal — no catalog dump)
    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)

        prompt = f"""You are an expert product catalog classifier for consumer electronics and audio equipment.
Given a product name and brand, determine its classification and real-world composition.

Product: "{identity_name}"
Brand/Family: "{family_name}"
Current SKU: "{full_sku}"

Classify this product as one of:
- "Product": A standalone individual item (single speaker, single remote, single adapter, etc.)
- "K": A predefined manufacturer Kit — sold as a complete set by the manufacturer (e.g. Bose Companion 3 = subwoofer + 2 satellites + control pod)
- "B": A reseller-assembled Bundle — items packaged together by the seller, not officially sold as a set by the manufacturer
- "P": A Part/Component — this is a sub-part or replacement component of a larger product

If type is K or B: list the expected components with name, quantity, and role (PRIMARY, SATELLITE, SUBWOOFER, ACCESSORY, MAIN_UNIT, CONTROL_POD, POWER_SUPPLY, CABLE, REMOTE).
If type is P: list the parent product(s) this part belongs to.

Use your knowledge of the product brand and product line to determine the real composition.

Return ONLY valid JSON with no markdown fences:
{{"suggested_type": "K"|"B"|"Product"|"P", "confidence": 0.0-1.0, "reasoning": "brief explanation", "expected_components": [{{"name": "component name", "quantity": 1, "role": "PRIMARY"}}], "parent_products": [{{"name": "parent product name"}}]}}"""

        response = client.models.generate_content(
            model=settings.gemini_model_name,
            contents=prompt,
        )
        raw_text = (response.text or "").strip()
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            raw_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        ai_result = json.loads(raw_text)
    except Exception as e:
        logger.error("Gemini deep classification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI classification failed: {str(e)}",
        )

    suggested_type = ai_result.get("suggested_type", "Product")
    type_confidence = max(0.0, min(1.0, float(ai_result.get("confidence", 0.5))))
    type_reasoning = ai_result.get("reasoning", "")
    raw_components = ai_result.get("expected_components", [])
    raw_parents = ai_result.get("parent_products", [])

    # Stage 2: Local DB fuzzy match for components
    family_id = identity.product_id if identity else None
    matched_components: list[AIClassifiedComponent] = []

    for comp in raw_components:
        comp_name = comp.get("name", "")
        comp_qty = int(comp.get("quantity", 1))
        comp_role = comp.get("role", "PRIMARY")
        query_tokens = set(comp_name.lower().split())

        matched_variant_id = None
        matched_sku = None
        matched_name = None
        match_confidence = 0.0

        # First: search within same product family
        if family_id:
            fam_stmt = (
                select(ProductVariant)
                .join(ProductIdentity, ProductVariant.identity_id == ProductIdentity.id)
                .where(
                    ProductIdentity.product_id == family_id,
                    ProductVariant.id != request.variant_id,
                )
                .limit(20)
            )
            fam_res = await db.execute(fam_stmt)
            fam_variants = fam_res.scalars().all()

            best_score = 0.0
            for fv in fam_variants:
                text = f"{fv.variant_name or ''} {fv.full_sku}"
                score = _fuzzy_score(query_tokens, text)
                if score > best_score:
                    best_score = score
                    matched_variant_id = fv.id
                    matched_sku = fv.full_sku
                    matched_name = fv.variant_name
                    match_confidence = round(score, 2)

        # Second: if no good family match, widen to full catalog
        if match_confidence < 0.3:
            # Build ILIKE patterns from the component name tokens (top 3 keywords)
            keywords = [t for t in query_tokens if len(t) > 2][:3]
            if keywords:
                like_conditions = [ProductVariant.variant_name.ilike(f"%{kw}%") for kw in keywords]
                wide_stmt = (
                    select(ProductVariant)
                    .where(
                        and_(*like_conditions),
                        ProductVariant.id != request.variant_id,
                    )
                    .limit(10)
                )
                wide_res = await db.execute(wide_stmt)
                wide_variants = wide_res.scalars().all()

                best_score = match_confidence
                for wv in wide_variants:
                    text = f"{wv.variant_name or ''} {wv.full_sku}"
                    score = _fuzzy_score(query_tokens, text)
                    if score > best_score:
                        best_score = score
                        matched_variant_id = wv.id
                        matched_sku = wv.full_sku
                        matched_name = wv.variant_name
                        match_confidence = round(score, 2)

        matched_components.append(AIClassifiedComponent(
            component_name=comp_name,
            suggested_quantity=comp_qty,
            suggested_role=comp_role,
            matched_variant_id=matched_variant_id,
            matched_sku=matched_sku,
            matched_name=matched_name,
            match_confidence=match_confidence,
        ))

    # Stage 2b: Local DB fuzzy match for parents
    matched_parents: list[AIClassifiedParent] = []
    for parent in raw_parents:
        parent_name = parent.get("name", "")
        query_tokens = set(parent_name.lower().split())

        matched_variant_id = None
        matched_sku = None
        matched_name = None
        match_confidence = 0.0

        keywords = [t for t in query_tokens if len(t) > 2][:3]
        if keywords:
            like_conditions = [ProductVariant.variant_name.ilike(f"%{kw}%") for kw in keywords]
            parent_stmt = (
                select(ProductVariant)
                .where(
                    and_(*like_conditions),
                    ProductVariant.id != request.variant_id,
                )
                .limit(10)
            )
            parent_res = await db.execute(parent_stmt)
            parent_variants = parent_res.scalars().all()

            best_score = 0.0
            for pv in parent_variants:
                text = f"{pv.variant_name or ''} {pv.full_sku}"
                score = _fuzzy_score(query_tokens, text)
                if score > best_score:
                    best_score = score
                    matched_variant_id = pv.id
                    matched_sku = pv.full_sku
                    matched_name = pv.variant_name
                    match_confidence = round(score, 2)

        matched_parents.append(AIClassifiedParent(
            parent_name=parent_name,
            matched_variant_id=matched_variant_id,
            matched_sku=matched_sku,
            matched_name=matched_name,
            match_confidence=match_confidence,
        ))

    # Generate warnings
    warnings: list[str] = []
    if suggested_type != current_type:
        type_labels = {"Product": "Standalone Item", "K": "Kit", "B": "Bundle", "P": "Part/Component"}
        warnings.append(
            f"Type mismatch: currently classified as '{type_labels.get(current_type, current_type)}' "
            f"but AI suggests '{type_labels.get(suggested_type, suggested_type)}' "
            f"({int(type_confidence * 100)}% confidence)"
        )

    return AIDeepClassifyResponse(
        variant_id=request.variant_id,
        full_sku=full_sku,
        current_type=current_type,
        suggested_type=suggested_type,
        type_confidence=type_confidence,
        type_reasoning=type_reasoning,
        suggested_components=matched_components,
        suggested_parents=matched_parents,
        warnings=warnings,
    )


# ============================================================================
# BUNDLE DISCOVERY
# ============================================================================

@router.get("/bundles/{variant_id}", response_model=BundleDiscoveryResponse)
async def get_bundle_participations(
    variant_id: int,
    _user: AdminOrSalesUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Discover all bundles/kits this product participates in (as a child component).
    Returns parent bundle/kit identities with their sibling components.
    """
    # Fetch the variant's identity
    stmt = (
        select(ProductVariant)
        .options(selectinload(ProductVariant.identity))
        .where(ProductVariant.id == variant_id)
    )
    res = await db.execute(stmt)
    variant = res.scalar_one_or_none()
    if not variant:
        raise HTTPException(status_code=404, detail=f"Variant {variant_id} not found")

    identity_id = variant.identity_id
    if not identity_id:
        return BundleDiscoveryResponse(
            variant_id=variant_id,
            full_sku=variant.full_sku,
            participations=[],
        )

    # Find all bundle_component rows where this identity is a child
    bc_stmt = (
        select(BundleComponent)
        .options(
            selectinload(BundleComponent.parent).selectinload(ProductIdentity.family),
            selectinload(BundleComponent.parent).selectinload(ProductIdentity.variants),
        )
        .where(BundleComponent.child_identity_id == identity_id)
    )
    bc_res = await db.execute(bc_stmt)
    parent_links = bc_res.scalars().all()

    participations: list[BundleParticipation] = []
    for link in parent_links:
        parent_identity = link.parent
        if not parent_identity:
            continue

        parent_type = parent_identity.type.value if parent_identity.type else "B"
        parent_variant = parent_identity.variants[0] if parent_identity.variants else None
        if not parent_variant:
            continue

        # Fetch sibling components (other children of the same parent)
        sibling_stmt = (
            select(BundleComponent)
            .options(
                selectinload(BundleComponent.child).selectinload(ProductIdentity.variants),
                selectinload(BundleComponent.child).selectinload(ProductIdentity.family),
            )
            .where(
                BundleComponent.parent_identity_id == parent_identity.id,
                BundleComponent.child_identity_id != identity_id,
            )
        )
        sibling_res = await db.execute(sibling_stmt)
        sibling_links = sibling_res.scalars().all()

        sibling_nodes: list[ProductNode] = []
        for sib in sibling_links:
            sib_identity = sib.child
            if sib_identity and sib_identity.variants:
                sv = sib_identity.variants[0]
                sibling_nodes.append(ProductNode(
                    variant_id=sv.id,
                    full_sku=sv.full_sku,
                    variant_name=sv.variant_name,
                    identity_name=sib_identity.identity_name,
                    family_name=sib_identity.family.base_name if sib_identity.family else None,
                    identity_type=sib_identity.type.value if sib_identity.type else None,
                ))

        participations.append(BundleParticipation(
            parent_variant_id=parent_variant.id,
            parent_sku=parent_variant.full_sku,
            parent_name=parent_variant.variant_name or parent_identity.identity_name,
            parent_type=parent_type,
            role=link.role.value if link.role else "PRIMARY",
            quantity_required=link.quantity_required,
            sibling_components=sibling_nodes,
        ))

    # If no explicit DB recipe exists yet, discover possible bundle combinations in same family
    if not participations and variant.identity and variant.identity.product_id:
        family_id = variant.identity.product_id

        # 1. Search for existing B or K identities in the same family
        cand_stmt = (
            select(ProductIdentity)
            .options(
                selectinload(ProductIdentity.variants),
                selectinload(ProductIdentity.family),
            )
            .where(
                ProductIdentity.product_id == family_id,
                ProductIdentity.type.in_([IdentityType.B, IdentityType.K]),
            )
        )
        cand_res = await db.execute(cand_stmt)
        cand_identities = cand_res.scalars().all()

        for ci in cand_identities:
            if not ci.variants:
                continue
            cv = ci.variants[0]
            # Fetch sibling accessories or parts in family
            sibs_stmt = (
                select(ProductVariant)
                .join(ProductIdentity, ProductVariant.identity_id == ProductIdentity.id)
                .options(selectinload(ProductVariant.identity).selectinload(ProductIdentity.family))
                .where(
                    ProductIdentity.product_id == family_id,
                    ProductVariant.id != variant.id,
                    ProductVariant.id != cv.id,
                )
                .limit(3)
            )
            sibs_res = await db.execute(sibs_stmt)
            sibs_variants = sibs_res.scalars().all()

            sibling_nodes = [
                ProductNode(
                    variant_id=sv.id,
                    full_sku=sv.full_sku,
                    variant_name=sv.variant_name,
                    identity_name=sv.identity.identity_name if sv.identity else None,
                    family_name=sv.identity.family.base_name if sv.identity and sv.identity.family else None,
                    identity_type=sv.identity.type.value if sv.identity and sv.identity.type else "Product",
                )
                for sv in sibs_variants
            ]

            participations.append(BundleParticipation(
                parent_variant_id=cv.id,
                parent_sku=cv.full_sku,
                parent_name=cv.variant_name or ci.identity_name or f"{variant.variant_name} Bundle Package",
                parent_type=ci.type.value,
                role="PRIMARY",
                quantity_required=1,
                sibling_components=sibling_nodes,
            ))

        # 2. If still none, synthesize a candidate possible bundle pairing with the top accessory
        if not participations:
            acc_stmt = (
                select(ProductVariant)
                .join(ProductIdentity, ProductVariant.identity_id == ProductIdentity.id)
                .options(selectinload(ProductVariant.identity).selectinload(ProductIdentity.family))
                .where(
                    ProductIdentity.product_id == family_id,
                    ProductVariant.id != variant.id,
                )
                .limit(2)
            )
            acc_res = await db.execute(acc_stmt)
            acc_variants = acc_res.scalars().all()

            if acc_variants:
                sibling_nodes = [
                    ProductNode(
                        variant_id=av.id,
                        full_sku=av.full_sku,
                        variant_name=av.variant_name,
                        identity_name=av.identity.identity_name if av.identity else None,
                        family_name=av.identity.family.base_name if av.identity and av.identity.family else None,
                        identity_type=av.identity.type.value if av.identity and av.identity.type else "P",
                    )
                    for av in acc_variants
                ]

                base_name = (
                    variant.identity.family.base_name
                    if variant.identity and variant.identity.family
                    else variant.variant_name or "Product"
                )
                parent_sku_guess = f"{variant.full_sku.split('-')[0]}-B-01"

                participations.append(BundleParticipation(
                    parent_variant_id=variant.id * 10000 + 999,  # Synthetic candidate ID
                    parent_sku=parent_sku_guess,
                    parent_name=f"{base_name} Combo Bundle",
                    parent_type="B",
                    role="PRIMARY",
                    quantity_required=1,
                    sibling_components=sibling_nodes,
                ))

    return BundleDiscoveryResponse(
        variant_id=variant_id,
        full_sku=variant.full_sku,
        participations=participations,
    )
