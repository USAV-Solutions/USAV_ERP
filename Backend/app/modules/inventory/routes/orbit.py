"""
Orbit View API Endpoints.
Provides interactive catalog management, dual Bundle (B) & Kit (K) creation per USAV UPIS spec,
rapid variant generation (UML Layer 2), sales velocity metrics, and automated Ecwid-Shopify price mismatch alerting.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, case, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminOrSalesUser
from app.core.database import get_db
from app.models import Platform, PlatformSyncStatus, ConditionCode, IdentityType, InventoryStatus
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
    OrbitCreateBundleKitRequest,
    OrbitCreateVariantRequest,
    OrbitUpdateRelationshipRequest,
    OrbitUnlinkRequest,
    OrbitConvertTypeRequest,
    ProductNode,
    RelationshipType,
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
