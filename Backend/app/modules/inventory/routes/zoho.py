"""Zoho synchronization endpoints for inventory catalog."""
from __future__ import annotations

import asyncio
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
    ZohoReadinessItem,
    ZohoReadinessRequest,
    ZohoReadinessResponse,
    ZohoSyncProgressResponse,
)

router = APIRouter(prefix="/zoho", tags=["Zoho Sync"])


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


async def _sync_single_standard_variant(
    db: AsyncSession,
    zoho_client: ZohoClient,
    data: ZohoBulkSyncRequest,
    variant: ProductVariant,
    synced_item_ids_by_identity: dict[int, str],
) -> ZohoBulkSyncItemResult:
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

    await db.commit()

    return ZohoBulkSyncItemResult(
        variant_id=variant.id,
        sku=variant.full_sku,
        action="item_sync",
        success=True,
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

    await db.commit()

    return ZohoBulkSyncItemResult(
        variant_id=variant.id,
        sku=variant.full_sku,
        action="composite_sync",
        success=True,
        zoho_item_id=composite_item_id,
        image_uploaded=image_uploaded,
        composite_synced=True,
        message="Synced as composite item",
    )


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
                message=str(exc),
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
                    composite_synced=False,
                    message=str(exc),
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
    """Synchronous bulk push endpoint (kept for compatibility)."""
    return await _execute_bulk_sync(db=db, data=data, job=None)


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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Zoho sync job has been started yet.",
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
