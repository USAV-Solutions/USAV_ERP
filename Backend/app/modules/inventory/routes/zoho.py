"""Zoho synchronization endpoints for inventory catalog."""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import async_session_factory, get_db
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
    ZohoRelinkBySkuItemResult,
    ZohoRelinkBySkuRequest,
    ZohoRelinkBySkuResponse,
    ZohoReadinessItem,
    ZohoReadinessRequest,
    ZohoReadinessResponse,
    ZohoSingleSyncRequest,
    ZohoSyncProgressResponse,
)

router = APIRouter(prefix="/zoho", tags=["Zoho Sync"])
logger = logging.getLogger(__name__)
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class _ZohoSyncJobState:
    job_id: str
    request: ZohoBulkSyncRequest
    status: str = "queued"  # queued | running | stopping | stopped | completed | failed
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    total_target: int = 0
    total_processed: int = 0
    total_success: int = 0
    total_failed: int = 0
    current_sku: str | None = None
    cancel_requested: bool = False
    last_error: str | None = None
    items: list[ZohoBulkSyncItemResult] = field(default_factory=list)


_JOB_LOCK = asyncio.Lock()
_CURRENT_JOB: _ZohoSyncJobState | None = None
_LAST_JOB: _ZohoSyncJobState | None = None
_CURRENT_TASK: asyncio.Task | None = None


def _as_progress_response(job: _ZohoSyncJobState) -> ZohoSyncProgressResponse:
    return ZohoSyncProgressResponse(
        job_id=job.job_id,
        status=job.status,
        started_at=job.started_at,
        finished_at=job.finished_at,
        total_target=job.total_target,
        total_processed=job.total_processed,
        total_success=job.total_success,
        total_failed=job.total_failed,
        current_sku=job.current_sku,
        cancel_requested=job.cancel_requested,
        last_error=job.last_error,
    )


def _has_zoho_credentials() -> bool:
    return all([
        settings.zoho_client_id,
        settings.zoho_client_secret,
        settings.zoho_refresh_token,
        settings.zoho_organization_id,
    ])


async def _load_target_variants(db: AsyncSession, data: ZohoBulkSyncRequest) -> list[ProductVariant]:
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
    return (await db.execute(stmt)).scalars().all()


def _resolve_thumbnail_path(thumbnail_url: str | None) -> Path | None:
    if not thumbnail_url:
        logger.info("Zoho image resolve thumbnail: no thumbnail_url provided")
        return None
    prefix = "/product-images/sku/"
    if not thumbnail_url.startswith(prefix):
        logger.info("Zoho image resolve thumbnail: unexpected URL format | thumbnail_url=%s", thumbnail_url)
        return None
    relative = thumbnail_url[len(prefix):].lstrip("/")
    full_path = Path(settings.product_images_path) / "sku" / relative
    if full_path.is_file():
        logger.info("Zoho image resolve thumbnail: found file | path=%s", full_path)
        return full_path
    logger.info("Zoho image resolve thumbnail: file missing | path=%s", full_path)
    return None


def _resolve_best_listing_image_paths(variant: ProductVariant) -> list[Path]:
    variant_dir = Path(settings.product_images_path) / "sku" / variant.full_sku
    if not variant_dir.is_dir():
        logger.info(
            "Zoho image resolve best-listing: variant dir not found | variant_id=%s sku=%s path=%s",
            variant.id,
            variant.full_sku,
            variant_dir,
        )
        return []

    listing_dirs = [
        entry
        for entry in variant_dir.iterdir()
        if entry.is_dir() and entry.name.startswith("listing-")
    ]
    logger.info(
        "Zoho image resolve best-listing: listing dirs discovered | variant_id=%s sku=%s count=%s dirs=%s",
        variant.id,
        variant.full_sku,
        len(listing_dirs),
        [entry.name for entry in listing_dirs],
    )

    def _listing_sort_key(path: Path) -> int:
        match = re.match(r"listing-(\d+)$", path.name)
        return int(match.group(1)) if match else 999999

    best_listing_path: Path | None = None
    best_count = 0
    for listing_dir in sorted(listing_dirs, key=_listing_sort_key):
        image_count = sum(
            1
            for file in listing_dir.iterdir()
            if file.is_file() and file.suffix.lower() in _IMAGE_EXTENSIONS
        )
        logger.info(
            "Zoho image resolve best-listing: listing image count | variant_id=%s sku=%s listing=%s image_count=%s",
            variant.id,
            variant.full_sku,
            listing_dir.name,
            image_count,
        )
        if image_count > best_count:
            best_count = image_count
            best_listing_path = listing_dir

    if best_listing_path is None:
        logger.info(
            "Zoho image resolve best-listing: no eligible listing with images | variant_id=%s sku=%s",
            variant.id,
            variant.full_sku,
        )
        return []

    images = sorted(
        file
        for file in best_listing_path.iterdir()
        if file.is_file() and file.suffix.lower() in _IMAGE_EXTENSIONS
    )
    if not images:
        logger.info(
            "Zoho image resolve best-listing: best listing has no supported images | variant_id=%s sku=%s listing=%s",
            variant.id,
            variant.full_sku,
            best_listing_path.name,
        )
        return []

    logger.info(
        "Zoho image source selected from best listing | variant_id=%s sku=%s listing=%s total_images_in_listing=%s images=%s",
        variant.id,
        variant.full_sku,
        best_listing_path.name,
        len(images),
        [image.name for image in images],
    )
    return images


def _resolve_flattened_image_paths(variant: ProductVariant) -> list[Path]:
    sku_dir = Path(settings.product_images_path) / "sku" / variant.full_sku
    if not sku_dir.is_dir():
        logger.info(
            "Zoho image resolve flattened: sku dir not found | variant_id=%s sku=%s path=%s",
            variant.id,
            variant.full_sku,
            sku_dir,
        )
        return []

    images = sorted(
        file
        for file in sku_dir.iterdir()
        if file.is_file() and file.suffix.lower() in _IMAGE_EXTENSIONS and file.name.startswith("img-")
    )
    if not images:
        logger.info(
            "Zoho image resolve flattened: no supported images | variant_id=%s sku=%s",
            variant.id,
            variant.full_sku,
        )
        return []

    logger.info(
        "Zoho image source selected from flattened SKU folder | variant_id=%s sku=%s count=%s images=%s",
        variant.id,
        variant.full_sku,
        len(images),
        [image.name for image in images],
    )
    return images


def _resolve_sync_image_paths(variant: ProductVariant) -> list[Path]:
    best_listing_images = _resolve_best_listing_image_paths(variant)
    if best_listing_images:
        logger.info(
            "Zoho image resolve final: using best-listing images | variant_id=%s sku=%s count=%s",
            variant.id,
            variant.full_sku,
            len(best_listing_images),
        )
        return best_listing_images

    flattened_images = _resolve_flattened_image_paths(variant)
    if flattened_images:
        logger.info(
            "Zoho image resolve final: using flattened SKU images | variant_id=%s sku=%s count=%s",
            variant.id,
            variant.full_sku,
            len(flattened_images),
        )
        return flattened_images

    thumbnail_image = _resolve_thumbnail_path(variant.thumbnail_url)
    if thumbnail_image:
        logger.info(
            "Zoho image source fallback to thumbnail | variant_id=%s sku=%s thumbnail_path=%s",
            variant.id,
            variant.full_sku,
            thumbnail_image,
        )
        return [thumbnail_image]

    logger.warning(
        "Zoho image resolve final: no uploadable image found | variant_id=%s sku=%s thumbnail_url=%s",
        variant.id,
        variant.full_sku,
        variant.thumbnail_url,
    )
    return []


def _sanitize_zoho_item_name(raw_name: str, fallback_sku: str) -> str:
    """Normalize item name to a conservative Zoho-safe format."""
    candidate = (raw_name or "").strip()
    if not candidate:
        candidate = f"USAV Item {fallback_sku}"

    candidate = candidate.replace("\n", " ").replace("\r", " ")
    candidate = re.sub(r"[^A-Za-z0-9 .,_\-\/()&+]", "", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()

    if not candidate:
        candidate = f"USAV Item {fallback_sku}"

    if not re.search(r"[A-Za-z]", candidate):
        candidate = f"USAV Item {fallback_sku}"

    return candidate[:100]


def _build_item_payload(variant: ProductVariant) -> dict:
    identity = variant.identity
    family = identity.family if identity else None
    if variant.variant_name:
        preferred = variant.variant_name
    else:
        base_name = family.base_name if family else variant.full_sku
        preferred = f"{base_name} {variant.full_sku}" if base_name else f"USAV Item {variant.full_sku}"
    item_name = _sanitize_zoho_item_name(preferred, variant.full_sku)
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

    if identity:
        payload["weight"] = float(identity.weight) if identity.weight is not None else None
        payload["length"] = float(identity.dimension_length) if identity.dimension_length is not None else None
        payload["width"] = float(identity.dimension_width) if identity.dimension_width is not None else None
        payload["height"] = float(identity.dimension_height) if identity.dimension_height is not None else None

    return {key: value for key, value in payload.items() if value is not None}


def _debug_sync_context(variant: ProductVariant, payload: dict, include_images: bool) -> None:
    identity = variant.identity
    family = identity.family if identity else None
    logger.info(
        "Zoho single-sync payload prepared | variant_id=%s sku=%s identity_id=%s identity_type=%s include_images=%s has_thumbnail=%s payload=%s",
        variant.id,
        variant.full_sku,
        variant.identity_id,
        identity.type.value if identity else None,
        include_images,
        bool(variant.thumbnail_url),
        payload,
    )
    if family:
        logger.info(
            "Zoho single-sync family/identity context | variant_id=%s product_id=%s base_name=%s description_len=%s dimensions=(%s,%s,%s) weight=%s",
            variant.id,
            family.product_id,
            family.base_name,
            len(family.description or ""),
            identity.dimension_length if identity else None,
            identity.dimension_width if identity else None,
            identity.dimension_height if identity else None,
            identity.weight if identity else None,
        )


async def _sync_single_standard_variant(
    db: AsyncSession,
    zoho_client: ZohoClient,
    data: ZohoBulkSyncRequest,
    variant: ProductVariant,
    synced_item_ids_by_identity: dict[int, str],
) -> ZohoBulkSyncItemResult:
    previous_zoho_item_id = variant.zoho_item_id
    payload = _build_item_payload(variant)
    _debug_sync_context(variant=variant, payload=payload, include_images=data.include_images)
    item_name = payload.get("name", variant.full_sku)
    logger.info(
        "Zoho standard item sync call | variant_id=%s sku=%s name=%s rate=%s extras=%s",
        variant.id,
        variant.full_sku,
        item_name,
        payload.get("rate", 0),
        {k: v for k, v in payload.items() if k not in {"name", "sku", "rate", "description"}},
    )
    zoho_item = await zoho_client.sync_item(
        sku=variant.full_sku,
        name=item_name,
        rate=float(payload.get("rate", 0) or 0),
        description=payload.get("description", ""),
        preferred_item_id=previous_zoho_item_id,
        **{k: v for k, v in payload.items() if k not in {"name", "sku", "rate", "description"}},
    )

    zoho_item_id = str(zoho_item.get("item_id", "")) if zoho_item else ""
    if not zoho_item_id:
        raise ValueError("Zoho response missing item_id")

    logger.info(
        "Zoho standard item sync success | variant_id=%s sku=%s zoho_item_id=%s",
        variant.id,
        variant.full_sku,
        zoho_item_id,
    )

    image_uploaded = False
    if data.include_images:
        image_paths = _resolve_sync_image_paths(variant)
        if image_paths:
            for image_path in image_paths:
                logger.info(
                    "Zoho image upload attempt (standard) | variant_id=%s sku=%s zoho_item_id=%s image_path=%s",
                    variant.id,
                    variant.full_sku,
                    zoho_item_id,
                    image_path,
                )
                await zoho_client.upload_item_image(zoho_item_id, image_path)
            image_uploaded = True
            logger.info(
                "Zoho image upload success (standard) | variant_id=%s sku=%s zoho_item_id=%s uploaded_count=%s",
                variant.id,
                variant.full_sku,
                zoho_item_id,
                len(image_paths),
            )
        else:
            logger.warning(
                "Zoho image upload skipped (standard): no resolved image | variant_id=%s sku=%s",
                variant.id,
                variant.full_sku,
            )

    variant.zoho_item_id = zoho_item_id
    variant.zoho_sync_status = ZohoSyncStatus.SYNCED
    variant.zoho_last_synced_at = datetime.now()

    # If sync moved the link to a different Zoho item, retire the old one to prevent duplicates.
    if previous_zoho_item_id and previous_zoho_item_id != zoho_item_id:
        try:
            await zoho_client.mark_item_inactive(previous_zoho_item_id)
            logger.info(
                "Zoho standard item cleanup: previous item marked inactive | variant_id=%s old_zoho_item_id=%s new_zoho_item_id=%s",
                variant.id,
                previous_zoho_item_id,
                zoho_item_id,
            )
        except Exception as exc:
            logger.warning(
                "Zoho standard item cleanup failed | variant_id=%s old_zoho_item_id=%s error=%s",
                variant.id,
                previous_zoho_item_id,
                exc,
            )

    if variant.identity_id:
        synced_item_ids_by_identity[variant.identity_id] = zoho_item_id

    await db.commit()

    return ZohoBulkSyncItemResult(
        variant_id=variant.id,
        sku=variant.full_sku,
        action="item_sync",
        success=True,
        zoho_sync_status=ZohoSyncStatus.SYNCED.value,
        zoho_item_id=zoho_item_id,
        image_uploaded=image_uploaded,
        message="Synced as standard inventory item",
    )


async def _sync_single_composite_variant(
    db: AsyncSession,
    zoho_client: ZohoClient,
    data: ZohoBulkSyncRequest,
    variant: ProductVariant,
    synced_item_ids_by_identity: dict[int, str],
) -> ZohoBulkSyncItemResult:
    previous_zoho_item_id = variant.zoho_item_id
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
        child_variant = None
        if not child_item_id:
            child_variant_stmt = (
                select(ProductVariant)
                .where(ProductVariant.identity_id == component.child_identity_id)
                .order_by(ProductVariant.id)
                .limit(1)
            )
            child_variant = (await db.execute(child_variant_stmt)).scalar_one_or_none()
            if child_variant and child_variant.zoho_item_id:
                child_item_id = child_variant.zoho_item_id

        if not child_item_id and child_variant:
            existing_item = await zoho_client.get_item_by_sku(child_variant.full_sku)
            if existing_item:
                child_item_id = str(existing_item.get("item_id", ""))
            else:
                existing_composite = await zoho_client.get_composite_item_by_sku(child_variant.full_sku)
                if existing_composite:
                    child_item_id = str(
                        existing_composite.get("item_id")
                        or existing_composite.get("composite_item_id")
                        or ""
                    )

            if child_item_id:
                child_variant.zoho_item_id = child_item_id
                child_variant.zoho_sync_status = ZohoSyncStatus.SYNCED
                child_variant.zoho_last_synced_at = datetime.now()
                logger.info(
                    "Zoho composite dependency resolved via SKU lookup | child_identity_id=%s child_variant_id=%s sku=%s zoho_item_id=%s",
                    component.child_identity_id,
                    child_variant.id,
                    child_variant.full_sku,
                    child_item_id,
                )

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
    _debug_sync_context(variant=variant, payload=payload, include_images=data.include_images)

    item_name = payload.get("name", variant.full_sku)
    logger.info(
        "Zoho composite item sync call | variant_id=%s sku=%s name=%s rate=%s component_count=%s extras=%s",
        variant.id,
        variant.full_sku,
        item_name,
        payload.get("rate", 0),
        len(component_items),
        {k: v for k, v in payload.items() if k not in {"name", "sku", "rate", "description", "component_items"}},
    )
    composite_item = await zoho_client.sync_composite_item(
        sku=variant.full_sku,
        name=item_name,
        rate=float(payload.get("rate", 0) or 0),
        description=payload.get("description", ""),
        component_items=component_items,
        preferred_item_id=previous_zoho_item_id,
        **{k: v for k, v in payload.items() if k not in {"name", "sku", "rate", "description", "component_items"}},
    )

    composite_item_id = str(composite_item.get("composite_item_id", "")) if composite_item else ""
    if not composite_item_id:
        composite_item_id = str(composite_item.get("item_id", "")) if composite_item else ""
    if not composite_item_id:
        raise ValueError("Zoho response missing composite item id")

    logger.info(
        "Zoho composite item sync success | variant_id=%s sku=%s zoho_item_id=%s",
        variant.id,
        variant.full_sku,
        composite_item_id,
    )

    image_uploaded = False
    if data.include_images:
        image_paths = _resolve_sync_image_paths(variant)
        if image_paths:
            for image_path in image_paths:
                logger.info(
                    "Zoho image upload attempt (composite) | variant_id=%s sku=%s zoho_item_id=%s image_path=%s",
                    variant.id,
                    variant.full_sku,
                    composite_item_id,
                    image_path,
                )
                await zoho_client.upload_item_image(composite_item_id, image_path)
            image_uploaded = True
            logger.info(
                "Zoho image upload success (composite) | variant_id=%s sku=%s zoho_item_id=%s uploaded_count=%s",
                variant.id,
                variant.full_sku,
                composite_item_id,
                len(image_paths),
            )
        else:
            logger.warning(
                "Zoho image upload skipped (composite): no resolved image | variant_id=%s sku=%s",
                variant.id,
                variant.full_sku,
            )

    variant.zoho_item_id = composite_item_id
    variant.zoho_sync_status = ZohoSyncStatus.SYNCED
    variant.zoho_last_synced_at = datetime.now()

    # If sync moved the link to a different Zoho item, retire the old one to prevent duplicates.
    if previous_zoho_item_id and previous_zoho_item_id != composite_item_id:
        try:
            await zoho_client.mark_item_inactive(previous_zoho_item_id)
            logger.info(
                "Zoho composite cleanup: previous item marked inactive | variant_id=%s old_zoho_item_id=%s new_zoho_item_id=%s",
                variant.id,
                previous_zoho_item_id,
                composite_item_id,
            )
        except Exception as exc:
            logger.warning(
                "Zoho composite cleanup failed | variant_id=%s old_zoho_item_id=%s error=%s",
                variant.id,
                previous_zoho_item_id,
                exc,
            )

    await db.commit()

    return ZohoBulkSyncItemResult(
        variant_id=variant.id,
        sku=variant.full_sku,
        action="composite_sync",
        success=True,
        zoho_sync_status=ZohoSyncStatus.SYNCED.value,
        zoho_item_id=composite_item_id,
        image_uploaded=image_uploaded,
        composite_synced=True,
        message="Synced as composite item",
    )


async def _load_variant_for_single_sync(db: AsyncSession, variant_id: int) -> ProductVariant:
    stmt = (
        select(ProductVariant)
        .options(
            selectinload(ProductVariant.identity).selectinload(ProductIdentity.family),
            selectinload(ProductVariant.listings),
        )
        .where(ProductVariant.id == variant_id)
        .limit(1)
    )
    variant = (await db.execute(stmt)).scalar_one_or_none()
    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Variant {variant_id} not found.",
        )
    if not variant.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Variant {variant_id} is inactive and cannot be synced.",
        )
    return variant


@router.post("/sync/items/{variant_id}", response_model=ZohoBulkSyncItemResult)
async def sync_single_item_to_zoho(
    variant_id: int,
    data: ZohoSingleSyncRequest,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Sync a single variant to Zoho with detailed debug logging."""
    if not _has_zoho_credentials():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zoho credentials are missing (client_id/client_secret/refresh_token/organization_id).",
        )

    async with _JOB_LOCK:
        if _CURRENT_JOB and _CURRENT_JOB.status in {"queued", "running", "stopping"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A Zoho bulk sync job is already running. Stop it before single-item sync.",
            )

    variant = await _load_variant_for_single_sync(db=db, variant_id=variant_id)

    if not data.force_resync and variant.zoho_sync_status == ZohoSyncStatus.SYNCED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Variant {variant_id} is already SYNCED. Use force_resync=true to push again.",
        )

    zoho_client = ZohoClient()
    identity_type = variant.identity.type if variant.identity else None
    is_composite = data.include_composites and identity_type in {IdentityType.B, IdentityType.K}

    logger.info(
        "Zoho single-sync request | variant_id=%s sku=%s include_images=%s include_composites=%s force_resync=%s detected_composite=%s",
        variant.id,
        variant.full_sku,
        data.include_images,
        data.include_composites,
        data.force_resync,
        is_composite,
    )

    try:
        if is_composite:
            result = await _sync_single_composite_variant(
                db=db,
                zoho_client=zoho_client,
                data=ZohoBulkSyncRequest(
                    include_images=data.include_images,
                    include_composites=data.include_composites,
                    force_resync=data.force_resync,
                    limit=1,
                ),
                variant=variant,
                synced_item_ids_by_identity={},
            )
        else:
            result = await _sync_single_standard_variant(
                db=db,
                zoho_client=zoho_client,
                data=ZohoBulkSyncRequest(
                    include_images=data.include_images,
                    include_composites=data.include_composites,
                    force_resync=data.force_resync,
                    limit=1,
                ),
                variant=variant,
                synced_item_ids_by_identity={},
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        variant.zoho_sync_status = ZohoSyncStatus.ERROR
        await db.commit()
        logger.exception(
            "Zoho single-sync failed | variant_id=%s sku=%s error=%s",
            variant.id,
            variant.full_sku,
            str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Zoho single-item sync failed: {str(exc)}",
        ) from exc


async def _execute_bulk_sync(
    db: AsyncSession,
    data: ZohoBulkSyncRequest,
    job: _ZohoSyncJobState | None = None,
) -> ZohoBulkSyncResponse:
    if not _has_zoho_credentials():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zoho credentials are missing (client_id/client_secret/refresh_token/organization_id).",
        )

    started_at = datetime.now()
    zoho_client = ZohoClient()
    variants = await _load_target_variants(db, data)

    if not variants:
        now = datetime.now()
        if job is not None:
            job.status = "completed"
            job.finished_at = now
        return ZohoBulkSyncResponse(
            started_at=started_at,
            finished_at=now,
            total_processed=0,
            total_success=0,
            total_failed=0,
            items=[],
        )

    synced_item_ids_by_identity: dict[int, str] = {}
    results: list[ZohoBulkSyncItemResult] = []

    non_composite_variants = [
        variant
        for variant in variants
        if not (
            data.include_composites
            and variant.identity
            and variant.identity.type in {IdentityType.B, IdentityType.K}
        )
    ]
    composite_variants = [
        variant
        for variant in variants
        if data.include_composites and variant.identity and variant.identity.type in {IdentityType.B, IdentityType.K}
    ]

    if job is not None:
        job.total_target = len(non_composite_variants) + len(composite_variants)
        job.status = "running"

    async def _handle_result(result: ZohoBulkSyncItemResult):
        results.append(result)
        if job is not None:
            job.items.append(result)
            job.total_processed += 1
            if result.success:
                job.total_success += 1
            else:
                job.total_failed += 1

    for variant in non_composite_variants:
        if job is not None:
            if job.cancel_requested:
                job.status = "stopped"
                break
            job.current_sku = variant.full_sku

        try:
            result = await _sync_single_standard_variant(
                db=db,
                zoho_client=zoho_client,
                data=data,
                variant=variant,
                synced_item_ids_by_identity=synced_item_ids_by_identity,
            )
            await _handle_result(result)
        except Exception as exc:
            variant.zoho_sync_status = ZohoSyncStatus.ERROR
            await db.commit()
            failure = ZohoBulkSyncItemResult(
                variant_id=variant.id,
                sku=variant.full_sku,
                action="item_sync",
                success=False,
                zoho_sync_status=ZohoSyncStatus.ERROR.value,
                message=f"{str(exc)} | attempted_name={_build_item_payload(variant).get('name', '')}",
            )
            if job is not None:
                job.last_error = str(exc)
            await _handle_result(failure)

    if job is None or job.status != "stopped":
        for variant in composite_variants:
            if job is not None:
                if job.cancel_requested:
                    job.status = "stopped"
                    break
                job.current_sku = variant.full_sku

            try:
                result = await _sync_single_composite_variant(
                    db=db,
                    zoho_client=zoho_client,
                    data=data,
                    variant=variant,
                    synced_item_ids_by_identity=synced_item_ids_by_identity,
                )
                await _handle_result(result)
            except Exception as exc:
                variant.zoho_sync_status = ZohoSyncStatus.ERROR
                await db.commit()
                failure = ZohoBulkSyncItemResult(
                    variant_id=variant.id,
                    sku=variant.full_sku,
                    action="composite_sync",
                    success=False,
                    zoho_sync_status=ZohoSyncStatus.ERROR.value,
                    composite_synced=False,
                    message=f"{str(exc)} | attempted_name={_build_item_payload(variant).get('name', '')}",
                )
                if job is not None:
                    job.last_error = str(exc)
                await _handle_result(failure)

    finished_at = datetime.now()
    total_success = len([result for result in results if result.success])
    total_failed = len(results) - total_success

    if job is not None:
        if job.status not in {"stopped", "failed"}:
            job.status = "completed"
        job.finished_at = finished_at
        job.current_sku = None

    return ZohoBulkSyncResponse(
        started_at=started_at,
        finished_at=finished_at,
        total_processed=len(results),
        total_success=total_success,
        total_failed=total_failed,
        items=results,
    )


async def _run_background_job(job: _ZohoSyncJobState) -> None:
    global _CURRENT_JOB, _LAST_JOB, _CURRENT_TASK

    try:
        async with async_session_factory() as db:
            await _execute_bulk_sync(db=db, data=job.request, job=job)
    except Exception as exc:
        job.status = "failed"
        job.last_error = str(exc)
        job.finished_at = datetime.now()
    finally:
        async with _JOB_LOCK:
            _LAST_JOB = job
            _CURRENT_JOB = None
            _CURRENT_TASK = None


@router.post("/sync/items/relink-by-sku", response_model=ZohoRelinkBySkuResponse)
async def relink_zoho_item_ids_by_sku(
    data: ZohoRelinkBySkuRequest,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Relink local ProductVariant.zoho_item_id using exact Zoho item SKU matches."""
    if not _has_zoho_credentials():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zoho credentials are missing (client_id/client_secret/refresh_token/organization_id).",
        )

    stmt = select(ProductVariant).where(ProductVariant.full_sku.is_not(None)).order_by(ProductVariant.id).limit(data.limit)
    if not data.include_inactive:
        stmt = stmt.where(ProductVariant.is_active == True)

    variants = (await db.execute(stmt)).scalars().all()
    if not variants:
        return ZohoRelinkBySkuResponse(
            total_processed=0,
            total_matched=0,
            total_updated=0,
            total_unchanged=0,
            total_not_found=0,
            total_skipped=0,
            dry_run=data.dry_run,
            items=[],
        )

    zoho_client = ZohoClient()
    items: list[ZohoRelinkBySkuItemResult] = []
    total_matched = 0
    total_updated = 0
    total_unchanged = 0
    total_not_found = 0
    total_skipped = 0

    for variant in variants:
        previous_id = variant.zoho_item_id

        try:
            zoho_item = await zoho_client.get_item_by_sku(variant.full_sku)
        except Exception as exc:
            total_skipped += 1
            items.append(
                ZohoRelinkBySkuItemResult(
                    variant_id=variant.id,
                    sku=variant.full_sku,
                    previous_zoho_item_id=previous_id,
                    matched_zoho_item_id=None,
                    matched=False,
                    updated=False,
                    message=f"Zoho lookup failed: {str(exc)}",
                )
            )
            continue

        if not zoho_item:
            total_not_found += 1
            items.append(
                ZohoRelinkBySkuItemResult(
                    variant_id=variant.id,
                    sku=variant.full_sku,
                    previous_zoho_item_id=previous_id,
                    matched_zoho_item_id=None,
                    matched=False,
                    updated=False,
                    message="No Zoho item found for SKU",
                )
            )
            continue

        matched_id = str(zoho_item.get("item_id", ""))
        if not matched_id:
            total_skipped += 1
            items.append(
                ZohoRelinkBySkuItemResult(
                    variant_id=variant.id,
                    sku=variant.full_sku,
                    previous_zoho_item_id=previous_id,
                    matched_zoho_item_id=None,
                    matched=False,
                    updated=False,
                    message="Zoho SKU match missing item_id in response",
                )
            )
            continue

        total_matched += 1

        if previous_id == matched_id:
            total_unchanged += 1
            items.append(
                ZohoRelinkBySkuItemResult(
                    variant_id=variant.id,
                    sku=variant.full_sku,
                    previous_zoho_item_id=previous_id,
                    matched_zoho_item_id=matched_id,
                    matched=True,
                    updated=False,
                    message="Already linked to matched Zoho item",
                )
            )
            continue

        if previous_id and not data.overwrite_existing:
            total_skipped += 1
            items.append(
                ZohoRelinkBySkuItemResult(
                    variant_id=variant.id,
                    sku=variant.full_sku,
                    previous_zoho_item_id=previous_id,
                    matched_zoho_item_id=matched_id,
                    matched=True,
                    updated=False,
                    message="Skipped because overwrite_existing=false and local zoho_item_id is set",
                )
            )
            continue

        if not data.dry_run:
            variant.zoho_item_id = matched_id
            variant.zoho_sync_status = ZohoSyncStatus.SYNCED
            variant.zoho_last_synced_at = datetime.now()
            variant.zoho_sync_error = None

        total_updated += 1
        items.append(
            ZohoRelinkBySkuItemResult(
                variant_id=variant.id,
                sku=variant.full_sku,
                previous_zoho_item_id=previous_id,
                matched_zoho_item_id=matched_id,
                matched=True,
                updated=True,
                message="Relinked by exact SKU match" if not data.dry_run else "Dry run: relink would be applied",
            )
        )

    if not data.dry_run:
        await db.commit()

    return ZohoRelinkBySkuResponse(
        total_processed=len(variants),
        total_matched=total_matched,
        total_updated=total_updated,
        total_unchanged=total_unchanged,
        total_not_found=total_not_found,
        total_skipped=total_skipped,
        dry_run=data.dry_run,
        items=items,
    )


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

        if data.include_images and len(_resolve_sync_image_paths(variant)) == 0:
            warnings.append("best_listing_and_thumbnail_missing_for_image_upload")

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
    """Synchronous bulk push endpoint (kept for compatibility)."""
    global _CURRENT_JOB, _LAST_JOB

    async with _JOB_LOCK:
        if _CURRENT_JOB and _CURRENT_JOB.status in {"queued", "running", "stopping"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A Zoho sync job is already running.",
            )

        job = _ZohoSyncJobState(
            job_id=str(uuid.uuid4()),
            request=data,
            status="queued",
            started_at=datetime.now(),
        )
        _CURRENT_JOB = job
        _LAST_JOB = job

    try:
        return await _execute_bulk_sync(db=db, data=data, job=job)
    except Exception as exc:
        job.status = "failed"
        job.last_error = str(exc)
        job.finished_at = datetime.now()
        raise
    finally:
        async with _JOB_LOCK:
            _LAST_JOB = job
            _CURRENT_JOB = None


@router.post("/sync/items/start", response_model=ZohoSyncProgressResponse)
async def start_zoho_bulk_sync(
    data: ZohoBulkSyncRequest,
    _admin: AdminUser,
):
    """Start a background Zoho bulk sync job and return initial job status."""
    global _CURRENT_JOB, _LAST_JOB, _CURRENT_TASK

    if not _has_zoho_credentials():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zoho credentials are missing (client_id/client_secret/refresh_token/organization_id).",
        )

    async with _JOB_LOCK:
        if _CURRENT_JOB and _CURRENT_JOB.status in {"queued", "running", "stopping"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A Zoho sync job is already running.",
            )

        job = _ZohoSyncJobState(
            job_id=str(uuid.uuid4()),
            request=data,
            status="queued",
            started_at=datetime.now(),
        )
        _CURRENT_JOB = job
        _LAST_JOB = job
        _CURRENT_TASK = asyncio.create_task(_run_background_job(job))
        return _as_progress_response(job)


@router.get("/sync/items/progress", response_model=ZohoSyncProgressResponse)
async def get_zoho_bulk_sync_progress(
    _admin: AdminUser,
):
    """Get current (or most recent) Zoho bulk sync job progress."""
    async with _JOB_LOCK:
        job = _CURRENT_JOB or _LAST_JOB
        if job is None:
            return ZohoSyncProgressResponse(
                job_id="",
                status="idle",
                started_at=None,
                finished_at=None,
                total_target=0,
                total_processed=0,
                total_success=0,
                total_failed=0,
                current_sku=None,
                cancel_requested=False,
                last_error=None,
            )
        return _as_progress_response(job)


@router.post("/sync/items/stop", response_model=ZohoSyncProgressResponse)
async def stop_zoho_bulk_sync(
    _admin: AdminUser,
):
    """Request cancellation of the currently running Zoho bulk sync job."""
    async with _JOB_LOCK:
        if _CURRENT_JOB is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active Zoho sync job to stop.",
            )

        _CURRENT_JOB.cancel_requested = True
        if _CURRENT_JOB.status in {"queued", "running"}:
            _CURRENT_JOB.status = "stopping"

        return _as_progress_response(_CURRENT_JOB)
