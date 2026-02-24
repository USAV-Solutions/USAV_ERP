"""Zoho synchronization endpoints for inventory catalog."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.integrations.zoho.client import ZohoClient
from app.models import (
    BundleComponent,
    IdentityType,
    ProductIdentity,
    ProductVariant,
    ZohoSyncStatus,
)
from app.modules.inventory.schemas import (
    ZohoBulkSyncItemResult,
    ZohoBulkSyncRequest,
    ZohoBulkSyncResponse,
    ZohoReadinessItem,
    ZohoReadinessRequest,
    ZohoReadinessResponse,
)

router = APIRouter(prefix="/zoho", tags=["Zoho Sync"])


def _resolve_thumbnail_path(thumbnail_url: str | None) -> Path | None:
    if not thumbnail_url:
        return None
    prefix = "/product-images/"
    if not thumbnail_url.startswith(prefix):
        return None
    relative = thumbnail_url[len(prefix):].lstrip("/")
    full_path = Path(settings.product_images_path) / relative
    if full_path.is_file():
        return full_path
    return None


def _build_item_payload(variant: ProductVariant) -> dict:
    identity = variant.identity
    family = identity.family if identity else None
    base_name = family.base_name if family else variant.full_sku
    item_name = f"{base_name} [{variant.full_sku}]"
    description = family.description if family and family.description else ""

    payload: dict = {
        "name": item_name,
        "sku": variant.full_sku,
        "description": description,
        "product_type": "goods",
        "item_type": "inventory",
        "rate": 0,
        "unit": "qty",
        "status": "active" if variant.is_active else "inactive",
    }

    raw_listings = variant.listings
    if raw_listings is None:
        listings = []
    elif isinstance(raw_listings, (list, tuple)):
        listings = raw_listings
    else:
        listings = [raw_listings]

    listing_prices = [
        listing.listing_price
        for listing in listings
        if listing.listing_price is not None
    ]
    if listing_prices:
        payload["rate"] = float(listing_prices[0])

    if family:
        payload["weight"] = float(family.weight) if family.weight is not None else None
        payload["length"] = float(family.dimension_length) if family.dimension_length is not None else None
        payload["width"] = float(family.dimension_width) if family.dimension_width is not None else None
        payload["height"] = float(family.dimension_height) if family.dimension_height is not None else None

    return {key: value for key, value in payload.items() if value is not None}


@router.post("/sync/readiness", response_model=ZohoReadinessResponse)
async def zoho_sync_readiness_report(
    data: ZohoReadinessRequest,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Return a readiness report for bulk Zoho sync with missing field diagnostics."""
    stmt = (
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.identity).selectinload(ProductIdentity.family),
            selectinload(ProductVariant.listings),
        )
        .where(ProductVariant.is_active == True)
        .order_by(ProductVariant.id)
        .limit(data.limit)
    )
    if data.only_unsynced:
        stmt = stmt.where(
            ProductVariant.zoho_sync_status.in_([ZohoSyncStatus.PENDING, ZohoSyncStatus.DIRTY])
        )

    variants = (await db.execute(stmt)).scalars().all()
    if not variants:
        return ZohoReadinessResponse(
            total_checked=0,
            ready_count=0,
            blocked_count=0,
            warning_only_count=0,
            items=[],
        )

    items: list[ZohoReadinessItem] = []
    blocked_count = 0
    warning_only_count = 0

    for variant in variants:
        missing_fields: list[str] = []
        warnings: list[str] = []

        identity = variant.identity
        family = identity.family if identity else None

        if identity is None:
            missing_fields.append("identity")
        if family is None:
            missing_fields.append("family")

        payload = _build_item_payload(variant)
        if not payload.get("name"):
            missing_fields.append("name")
        if not payload.get("sku"):
            missing_fields.append("sku")

        if not variant.listings:
            warnings.append("no_platform_listing_price")
        elif payload.get("rate", 0) == 0:
            warnings.append("listing_price_is_zero")

        if data.include_images and _resolve_thumbnail_path(variant.thumbnail_url) is None:
            warnings.append("thumbnail_missing_for_image_upload")

        identity_type = identity.type.value if identity else "UNKNOWN"
        if data.include_composites and identity and identity.type in {IdentityType.B, IdentityType.K}:
            component_rows = (
                await db.execute(
                    select(BundleComponent)
                    .where(BundleComponent.parent_identity_id == variant.identity_id)
                    .order_by(BundleComponent.id)
                )
            ).scalars().all()

            if not component_rows:
                missing_fields.append("bundle_components")
            else:
                for component in component_rows:
                    child_variant_stmt = (
                        select(ProductVariant.id)
                        .where(ProductVariant.identity_id == component.child_identity_id)
                        .where(ProductVariant.is_active == True)
                        .limit(1)
                    )
                    child_variant_id = (await db.execute(child_variant_stmt)).scalar_one_or_none()
                    if child_variant_id is None:
                        missing_fields.append(f"component_variant_missing:{component.child_identity_id}")

        ready = len(missing_fields) == 0
        severity = "error" if not ready else ("warning" if warnings else "ok")

        if not ready:
            blocked_count += 1
        elif warnings:
            warning_only_count += 1

        items.append(
            ZohoReadinessItem(
                variant_id=variant.id,
                sku=variant.full_sku,
                identity_type=identity_type,
                ready=ready,
                severity=severity,
                missing_fields=missing_fields,
                warnings=warnings,
            )
        )

    ready_count = len(items) - blocked_count

    return ZohoReadinessResponse(
        total_checked=len(items),
        ready_count=ready_count,
        blocked_count=blocked_count,
        warning_only_count=warning_only_count,
        items=items,
    )


@router.post("/sync/items", response_model=ZohoBulkSyncResponse)
async def sync_all_items_to_zoho(
    data: ZohoBulkSyncRequest,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Push all eligible catalog variants to Zoho Inventory."""
    if not all([
        settings.zoho_client_id,
        settings.zoho_client_secret,
        settings.zoho_refresh_token,
        settings.zoho_organization_id,
    ]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zoho credentials are missing (client_id/client_secret/refresh_token/organization_id).",
        )

    started_at = datetime.now()
    zoho_client = ZohoClient()

    stmt = (
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.identity).selectinload(ProductIdentity.family),
            selectinload(ProductVariant.listings),
        )
        .where(ProductVariant.is_active == True)
        .order_by(ProductVariant.id)
        .limit(data.limit)
    )
    if not data.force_resync:
        stmt = stmt.where(
            ProductVariant.zoho_sync_status.in_([ZohoSyncStatus.PENDING, ZohoSyncStatus.DIRTY])
        )

    variants = (await db.execute(stmt)).scalars().all()
    if not variants:
        now = datetime.now()
        return ZohoBulkSyncResponse(
            started_at=started_at,
            finished_at=now,
            total_processed=0,
            total_success=0,
            total_failed=0,
            items=[],
        )

    results: list[ZohoBulkSyncItemResult] = []
    synced_item_ids_by_identity: dict[int, str] = {}

    non_composite_variants = [
        variant
        for variant in variants
        if not (
            data.include_composites
            and variant.identity
            and variant.identity.type in {IdentityType.B, IdentityType.K}
        )
    ]

    for variant in non_composite_variants:
        try:
            payload = _build_item_payload(variant)
            zoho_item = await zoho_client.sync_item(
                sku=variant.full_sku,
                name=payload.get("name", variant.full_sku),
                rate=float(payload.get("rate", 0) or 0),
                description=payload.get("description", ""),
                **{k: v for k, v in payload.items() if k not in {"name", "sku", "rate", "description"}},
            )

            zoho_item_id = str(zoho_item.get("item_id", "")) if zoho_item else ""
            if not zoho_item_id:
                raise ValueError("Zoho response missing item_id")

            image_uploaded = False
            if data.include_images:
                image_path = _resolve_thumbnail_path(variant.thumbnail_url)
                if image_path:
                    await zoho_client.upload_item_image(zoho_item_id, image_path)
                    image_uploaded = True

            variant.zoho_item_id = zoho_item_id
            variant.zoho_sync_status = ZohoSyncStatus.SYNCED
            variant.zoho_last_synced_at = datetime.now()

            if variant.identity_id:
                synced_item_ids_by_identity[variant.identity_id] = zoho_item_id

            results.append(
                ZohoBulkSyncItemResult(
                    variant_id=variant.id,
                    sku=variant.full_sku,
                    action="item_sync",
                    success=True,
                    zoho_item_id=zoho_item_id,
                    image_uploaded=image_uploaded,
                    message="Synced as standard inventory item",
                )
            )
        except Exception as exc:
            variant.zoho_sync_status = ZohoSyncStatus.ERROR
            results.append(
                ZohoBulkSyncItemResult(
                    variant_id=variant.id,
                    sku=variant.full_sku,
                    action="item_sync",
                    success=False,
                    message=str(exc),
                )
            )

    if data.include_composites:
        composite_variants = [
            variant
            for variant in variants
            if variant.identity and variant.identity.type in {IdentityType.B, IdentityType.K}
        ]

        for variant in composite_variants:
            try:
                component_rows = (
                    await db.execute(
                        select(BundleComponent)
                        .where(BundleComponent.parent_identity_id == variant.identity_id)
                        .order_by(BundleComponent.id)
                    )
                ).scalars().all()

                component_items = []
                for component in component_rows:
                    child_item_id = synced_item_ids_by_identity.get(component.child_identity_id)
                    if not child_item_id:
                        child_variant_stmt = (
                            select(ProductVariant)
                            .where(ProductVariant.identity_id == component.child_identity_id)
                            .where(ProductVariant.zoho_item_id.is_not(None))
                            .order_by(ProductVariant.id)
                            .limit(1)
                        )
                        child_variant = (await db.execute(child_variant_stmt)).scalar_one_or_none()
                        if child_variant and child_variant.zoho_item_id:
                            child_item_id = child_variant.zoho_item_id

                    if child_item_id:
                        component_items.append(
                            {
                                "item_id": child_item_id,
                                "quantity": int(component.quantity_required),
                            }
                        )

                if not component_items:
                    raise ValueError("Bundle/Kit has no Zoho-synced child components")

                payload = _build_item_payload(variant)
                payload["component_items"] = component_items

                composite_item = await zoho_client.sync_composite_item(
                    sku=variant.full_sku,
                    name=payload.get("name", variant.full_sku),
                    rate=float(payload.get("rate", 0) or 0),
                    description=payload.get("description", ""),
                    component_items=component_items,
                    **{k: v for k, v in payload.items() if k not in {"name", "sku", "rate", "description", "component_items"}},
                )

                composite_item_id = str(composite_item.get("composite_item_id", "")) if composite_item else ""
                if not composite_item_id:
                    composite_item_id = str(composite_item.get("item_id", "")) if composite_item else ""
                if not composite_item_id:
                    raise ValueError("Zoho response missing composite item id")

                image_uploaded = False
                if data.include_images:
                    image_path = _resolve_thumbnail_path(variant.thumbnail_url)
                    if image_path:
                        await zoho_client.upload_item_image(composite_item_id, image_path)
                        image_uploaded = True

                variant.zoho_item_id = composite_item_id
                variant.zoho_sync_status = ZohoSyncStatus.SYNCED
                variant.zoho_last_synced_at = datetime.now()

                results.append(
                    ZohoBulkSyncItemResult(
                        variant_id=variant.id,
                        sku=variant.full_sku,
                        action="composite_sync",
                        success=True,
                        zoho_item_id=composite_item_id,
                        image_uploaded=image_uploaded,
                        composite_synced=True,
                        message="Synced as composite item",
                    )
                )
            except Exception as exc:
                variant.zoho_sync_status = ZohoSyncStatus.ERROR
                results.append(
                    ZohoBulkSyncItemResult(
                        variant_id=variant.id,
                        sku=variant.full_sku,
                        action="composite_sync",
                        success=False,
                        composite_synced=False,
                        message=str(exc),
                    )
                )

    await db.commit()

    total_success = len([result for result in results if result.success])
    total_failed = len(results) - total_success

    return ZohoBulkSyncResponse(
        started_at=started_at,
        finished_at=datetime.now(),
        total_processed=len(results),
        total_success=total_success,
        total_failed=total_failed,
        items=results,
    )
