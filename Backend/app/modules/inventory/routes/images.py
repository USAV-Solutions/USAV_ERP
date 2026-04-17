"""
Product Image API endpoints.

Serves product variant images from /mnt/product_images/.
Directory structure: /mnt/product_images/sku/{full_sku}/...

For each SKU, the listing folder with the most images is selected as the
"best" listing. The first sorted .jpg is used as the thumbnail.
"""
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.models.entities import ProductIdentity, ProductVariant, ZohoSyncStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["Product Images"])

IMAGES_ROOT = Path(getattr(settings, "product_images_path", "/mnt/product_images"))

IMAGE_EXTENSION = [".jpg", ".jpeg", ".png", ".webp"]  # Only consider these as valid image files

IMAGE_DEBUG_COUNTERS: dict[str, int] = {
    "sku_images": 0,
    "sku_thumbnail": 0,
    "sku_file": 0,
    "batch_thumbnails": 0,
}


@dataclass
class VariantImageContext:
    variant_id: int
    full_sku: str
    generated_upis_h: str
    thumbnail_url: Optional[str]


class ImageInfo(BaseModel):
    filename: str
    url: str


class SkuImagesResponse(BaseModel):
    sku: str
    listing: str
    total_images: int
    thumbnail_url: str
    images: list[ImageInfo]


async def _get_variant_context(db: AsyncSession, sku: str) -> Optional[VariantImageContext]:
    """Resolve SKU and return variant metadata needed for image lookup and thumbnail caching."""
    stmt = (
        select(
            ProductVariant.id,
            ProductVariant.full_sku,
            ProductVariant.thumbnail_url,
            ProductIdentity.generated_upis_h,
        )
        .join(ProductIdentity, ProductVariant.identity_id == ProductIdentity.id)
        .where(ProductVariant.full_sku == sku)
    )
    row = (await db.execute(stmt)).first()

    if row is None and sku != sku.upper():
        stmt_upper = (
            select(
                ProductVariant.id,
                ProductVariant.full_sku,
                ProductVariant.thumbnail_url,
                ProductIdentity.generated_upis_h,
            )
            .join(ProductIdentity, ProductVariant.identity_id == ProductIdentity.id)
            .where(ProductVariant.full_sku == sku.upper())
        )
        row = (await db.execute(stmt_upper)).first()

    if row is None:
        logger.warning("[IMAGE_SEARCH] SKU not found in database: %s", sku)
        return None

    return VariantImageContext(
        variant_id=row.id,
        full_sku=row.full_sku,
        generated_upis_h=row.generated_upis_h,
        thumbnail_url=row.thumbnail_url,
    )


def _find_variant_dir(context: VariantImageContext) -> Optional[Path]:
    """
    Resolve SKU and return expected canonical variant image dir:
    /mnt/product_images/sku/{full_sku}
    """
    if not IMAGES_ROOT.is_dir():
        logger.warning("[IMAGE_SEARCH] Image root directory does not exist: %s", IMAGES_ROOT)
        return None

    variant_dir = IMAGES_ROOT / "sku" / context.full_sku
    logger.debug("[DEBUG.INTERNAL_API][IMAGE_DEBUG] Resolved canonical variant path for sku=%s -> upis_h=%s path=%s",
        context.full_sku,
        context.generated_upis_h,
        variant_dir,
    )
    if variant_dir.is_dir():
        logger.debug("[DEBUG.INTERNAL_API][IMAGE_SEARCH] Found variant directory: %s", variant_dir)
        return variant_dir

    logger.warning("[IMAGE_SEARCH] Variant directory not found for sku=%s at %s", context.full_sku, variant_dir)
    return None


def _iter_listing_dirs(variant_dir: Path) -> list[Path]:
    """Return listing directories sorted by listing index (listing-0, listing-1, ...)."""
    listing_dirs = [
        entry
        for entry in variant_dir.iterdir()
        if entry.is_dir() and entry.name.startswith("listing-")
    ]

    def listing_sort_key(path: Path) -> int:
        match = re.match(r"listing-(\d+)$", path.name)
        return int(match.group(1)) if match else 999999

    sorted_dirs = sorted(listing_dirs, key=listing_sort_key)
    logger.debug("[DEBUG.INTERNAL_API][IMAGE_DEBUG] Listing directories under %s -> %s",
        variant_dir,
        [str(path) for path in sorted_dirs],
    )
    return sorted_dirs


def _get_best_listing(variant_dir: Path) -> Optional[tuple[str, Path]]:
    """
    Find the listing folder with the most .jpg images for a variant directory.
    Returns (listing_name, listing_path) or None.
    """
    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_SEARCH] Scanning listings in: {variant_dir}")
    best_listing: Optional[str] = None
    best_path: Optional[Path] = None
    best_count = 0
    listing_counts = {}

    listing_dirs = _iter_listing_dirs(variant_dir)
    for entry in listing_dirs:
        img_count = sum(
            1 for f in entry.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSION
        )
        listing_counts[entry.name] = img_count

        if img_count > best_count:
            best_count = img_count
            best_listing = entry.name
            best_path = entry

    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_SEARCH] Listing image counts: {listing_counts}")
    
    if best_listing and best_path:
        logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_SEARCH] ✓ Best listing: {best_listing} with {best_count} images")
        return best_listing, best_path

    if not listing_dirs:
        flat_images = _sorted_images(variant_dir)
        if flat_images:
            logger.debug("[DEBUG.INTERNAL_API][IMAGE_SEARCH] Using flattened SKU image layout in %s with %s images",
                variant_dir,
                len(flat_images),
            )
            return "flat", variant_dir
    
    logger.warning(f"[IMAGE_SEARCH] ✗ No valid listings found in {variant_dir}")
    return None


def _sorted_images(listing_path: Path) -> list[str]:
    """Return .jpg image filenames sorted lexicographically."""
    files = [
        f.name for f in listing_path.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSION
    ]
    sorted_files = sorted(files)
    logger.debug("[DEBUG.INTERNAL_API][IMAGE_DEBUG] JPG files in listing %s -> %s",
        listing_path,
        sorted_files,
    )
    return sorted_files


def _build_public_thumbnail_url(
    context: VariantImageContext,
    listing_name: str,
    image_filename: str,
) -> str:
    """Build direct Nginx-served URL for a thumbnail image."""
    if listing_name == "flat":
        return f"/product-images/sku/{context.full_sku}/{image_filename}"
    return f"/product-images/sku/{context.full_sku}/{listing_name}/{image_filename}"


def _resolve_thumbnail_file_path(thumbnail_url: str) -> Optional[Path]:
    """Map a public thumbnail URL to its on-disk file path under IMAGES_ROOT."""
    prefix = "/product-images/sku/"
    if not thumbnail_url.startswith(prefix):
        return None

    relative = thumbnail_url[len(prefix):].lstrip("/")
    if not relative:
        return None

    candidate = IMAGES_ROOT / "sku" / relative
    try:
        candidate.relative_to(IMAGES_ROOT)
    except Exception:
        return None

    return candidate
async def _recompute_thumbnail_url(
    db: AsyncSession,
    context: VariantImageContext,
    mark_sync_dirty: bool = False,
) -> Optional[str]:
    """Recompute and persist thumbnail_url based on current images."""
    variant_dir = _find_variant_dir(context)
    thumbnail_url: Optional[str] = None

    if variant_dir:
        listing_result = _get_best_listing(variant_dir)
        if listing_result:
            listing_name, listing_path = listing_result
            image_files = _sorted_images(listing_path)
            if image_files:
                thumbnail_url = _build_public_thumbnail_url(context, listing_name, image_files[0])

    await db.execute(
        update(ProductVariant)
        .where(ProductVariant.id == context.variant_id)
        .values(thumbnail_url=thumbnail_url)
    )

    if mark_sync_dirty:
        variant = await db.get(ProductVariant, context.variant_id)
        if variant is not None:
            keep_pending = (
                variant.zoho_sync_status == ZohoSyncStatus.PENDING
                and not variant.zoho_item_id
            )
            if not keep_pending:
                variant.zoho_sync_status = ZohoSyncStatus.DIRTY
                variant.zoho_sync_error = None

    await db.commit()
    context.thumbnail_url = thumbnail_url

    logger.debug("[DEBUG.INTERNAL_API][THUMB_DEBUG] Recomputed thumbnail_url for sku=%s variant_id=%s -> %s",
        context.full_sku,
        context.variant_id,
        thumbnail_url,
    )
    return thumbnail_url


async def _resolve_or_backfill_thumbnail_url(
    db: AsyncSession,
    sku: str,
) -> tuple[Optional[VariantImageContext], Optional[str]]:
    """
    Read thumbnail_url from DB when available.
    For legacy rows without thumbnail_url, compute best image URL and persist it.
    """
    logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] Resolve requested for sku=%s", sku)
    context = await _get_variant_context(db, sku)
    if context is None:
        logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] Resolve result: SKU not found in DB for sku=%s", sku)
        return None, None

    if context.thumbnail_url:
        thumbnail_path = _resolve_thumbnail_file_path(context.thumbnail_url)
        if thumbnail_path and thumbnail_path.is_file():
            logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] Cache hit for sku=%s variant_id=%s thumbnail_url=%s",
                context.full_sku,
                context.variant_id,
                context.thumbnail_url,
            )
            return context, context.thumbnail_url

        logger.warning(
            "[THUMB_TRACE] Cached thumbnail_url is stale or invalid; recomputing | sku=%s variant_id=%s thumbnail_url=%s resolved_path=%s",
            context.full_sku,
            context.variant_id,
            context.thumbnail_url,
            thumbnail_path,
        )

    logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] Cache miss for sku=%s variant_id=%s -> computing best listing",
        context.full_sku,
        context.variant_id,
    )

    variant_dir = _find_variant_dir(context)
    if not variant_dir:
        logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] Resolve failed: variant_dir not found for sku=%s", context.full_sku)
        return context, None

    listing_result = _get_best_listing(variant_dir)
    if not listing_result:
        logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] Resolve failed: no listing folders for sku=%s", context.full_sku)
        return context, None

    listing_name, listing_path = listing_result
    image_files = _sorted_images(listing_path)
    if not image_files:
        logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] Resolve failed: no images in best listing for sku=%s", context.full_sku)
        return context, None

    thumbnail_url = _build_public_thumbnail_url(context, listing_name, image_files[0])

    await db.execute(
        update(ProductVariant)
        .where(ProductVariant.id == context.variant_id)
        .values(thumbnail_url=thumbnail_url)
    )
    await db.commit()
    context.thumbnail_url = thumbnail_url

    logger.debug("[DEBUG.INTERNAL_API][THUMB_DEBUG] Backfilled thumbnail_url for sku=%s variant_id=%s -> %s",
        context.full_sku,
        context.variant_id,
        thumbnail_url,
    )
    return context, thumbnail_url



def _extract_image_index(filename: str) -> Optional[int]:
    match = re.match(r"img-(\d+)\.[a-zA-Z0-9]+$", filename)
    return int(match.group(1)) if match else None

def _ensure_listing_dir(context: VariantImageContext, listing_index: int) -> Path:
    if not IMAGES_ROOT.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Image root directory does not exist: {IMAGES_ROOT}",
        )

    listing_dir = IMAGES_ROOT / "sku" / context.full_sku / f"listing-{listing_index}"
    listing_dir.mkdir(parents=True, exist_ok=True)
    return listing_dir

def _build_sku_images_response(
    context: VariantImageContext,
) -> SkuImagesResponse:
    variant_dir = _find_variant_dir(context)
    if not variant_dir:
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {context.full_sku}")

    result = _get_best_listing(variant_dir)
    if not result:
        raise HTTPException(status_code=404, detail=f"No listing folders found for SKU: {context.full_sku}")

    listing_name, listing_path = result
    image_files = _sorted_images(listing_path)
    if not image_files:
        raise HTTPException(status_code=404, detail=f"No images in best listing for SKU: {context.full_sku}")

    images = [
        ImageInfo(
            filename=fname,
            url=f"/api/v1/images/{context.full_sku}/file/{fname}",
        )
        for fname in image_files
    ]

    thumbnail_url = context.thumbnail_url or f"/api/v1/images/{context.full_sku}/file/{image_files[0]}"

    return SkuImagesResponse(
        sku=context.full_sku,
        listing=listing_name,
        total_images=len(image_files),
        thumbnail_url=thumbnail_url,
        images=images,
    )
@router.get(
    "/{sku}",
    response_model=SkuImagesResponse,
    summary="Get image info for a product variant SKU",
)
async def get_sku_images(
    sku: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns image metadata for a product variant SKU.
    Automatically selects the listing folder with the most images.
    """
    IMAGE_DEBUG_COUNTERS["sku_images"] += 1
    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_API] GET /{sku} - Fetching image metadata")

    context, resolved_thumbnail_url = await _resolve_or_backfill_thumbnail_url(db, sku)

    if context is None:
        logger.warning(f"[IMAGE_API] GET /{sku} - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    if resolved_thumbnail_url:
        context.thumbnail_url = resolved_thumbnail_url

    response = _build_sku_images_response(context)
    logger.debug("[DEBUG.INTERNAL_API][IMAGE_DEBUG] Response URLs for sku=%s -> thumbnail=%s images=%s",
        context.full_sku,
        response.thumbnail_url,
        [img.url for img in response.images],
    )
    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_API] GET /{sku} - Returning 200: {len(response.images)} images from {response.listing}")
    return response

@router.get(
    "/{sku}/thumbnail",
    summary="Get the thumbnail for a product variant SKU",
)
async def get_sku_thumbnail(
    sku: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Serve the first sorted .jpg from the best listing as the thumbnail."""
    IMAGE_DEBUG_COUNTERS["sku_thumbnail"] += 1
    logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] ROUTE_HIT method=%s path=%s sku=%s host=%s forwarded_for=%s forwarded_proto=%s user_agent=%s referer=%s",
        request.method,
        request.url.path,
        sku,
        request.headers.get("host"),
        request.headers.get("x-forwarded-for"),
        request.headers.get("x-forwarded-proto"),
        request.headers.get("user-agent"),
        request.headers.get("referer"),
    )
    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_API] GET /{sku}/thumbnail - Fetching thumbnail")
    logger.debug("[DEBUG.INTERNAL_API][THUMB_DEBUG] Incoming request path: %s", request.url.path)
    if "/api/v1/api/v1/" in request.url.path:
        logger.warning(
            "[THUMB_DEBUG] Detected duplicated API prefix in request path: %s",
            request.url.path,
        )

    context, thumbnail_url = await _resolve_or_backfill_thumbnail_url(db, sku)

    logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] ROUTE_RESOLVE sku=%s context_found=%s thumbnail_url=%s",
        sku,
        context is not None,
        thumbnail_url,
    )

    if context is None:
        logger.warning(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    if not thumbnail_url:
        logger.warning(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 404: No thumbnail found")
        raise HTTPException(status_code=404, detail=f"No thumbnail found for SKU: {sku}")

    logger.debug("[DEBUG.INTERNAL_API][IMAGE_API] GET /%s/thumbnail - Returning redirect to %s",
        context.full_sku,
        thumbnail_url,
    )
    return RedirectResponse(
        url=thumbnail_url,
        status_code=307,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/{sku}/file/{filename}",
    summary="Serve a specific image file for a product variant SKU",
)
async def get_sku_image_file(
    sku: str,
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Serve a specific image file from the best listing of a SKU."""
    IMAGE_DEBUG_COUNTERS["sku_file"] += 1
    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_API] GET /{sku}/file/{filename} - Fetching image file")
    logger.debug("[DEBUG.INTERNAL_API][IMAGE_DEBUG] Incoming request path: %s", request.url.path)
    if "/api/v1/api/v1/" in request.url.path:
        logger.warning(
            "[IMAGE_DEBUG] Detected duplicated API prefix in request path: %s",
            request.url.path,
        )

    # Security: prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 400: Invalid filename")
        raise HTTPException(status_code=400, detail="Invalid filename")

    context = await _get_variant_context(db, sku)
    variant_dir = _find_variant_dir(context) if context else None

    if not variant_dir:
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    result = _get_best_listing(variant_dir)
    if not result:
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 404: No listing folders found")
        raise HTTPException(status_code=404, detail=f"No listing folders found for SKU: {sku}")

    listing_name, listing_path = result
    file_path = listing_path / filename
    logger.debug("[DEBUG.INTERNAL_API][IMAGE_DEBUG] Checking requested JPG path for sku=%s listing=%s filename=%s -> %s",
        sku,
        listing_name,
        filename,
        file_path,
    )

    if not file_path.is_file():
        available = _sorted_images(listing_path)
        logger.warning(
            "[IMAGE_API] GET /%s/file/%s - Returning 404: Image not found at %s; available_jpg=%s",
            sku,
            filename,
            file_path,
            available,
        )
        raise HTTPException(status_code=404, detail=f"Image not found: {filename}")

    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_API] GET /{sku}/file/{filename} - Returning 200: {file_path}")
    return FileResponse(
        path=str(file_path),
        media_type=_guess_media_type(file_path),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/batch/thumbnails",
    summary="Get thumbnail URLs for multiple SKUs",
)
async def get_batch_thumbnails(
    skus: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get thumbnail URLs for a comma-separated list of SKUs.
    Returns a mapping of SKU -> thumbnail_url (or null if not found).
    """
    IMAGE_DEBUG_COUNTERS["batch_thumbnails"] += 1
    sku_list = [s.strip() for s in skus.split(",") if s.strip()]
    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_API] GET /batch/thumbnails - Fetching thumbnails for {len(sku_list)} SKUs")
    result: dict[str, Optional[str]] = {}

    for sku in sku_list:
        context, thumbnail_url = await _resolve_or_backfill_thumbnail_url(db, sku)
        if context is None:
            result[sku] = None
            continue

        result[context.full_sku] = thumbnail_url

    found_count = sum(1 for v in result.values() if v is not None)
    logger.debug(f"[DEBUG.INTERNAL_API][IMAGE_API] GET /batch/thumbnails - Returning 200: {found_count}/{len(sku_list)} thumbnails found")
    return result


@router.get(
    "/debug/counters",
    summary="Debug counters for image routes",
)
async def get_image_debug_counters(
    _admin: AdminUser,
):
    """Return in-memory counters showing which image routes are receiving traffic."""
    return {
        "counters": IMAGE_DEBUG_COUNTERS,
        "note": "In-memory counters reset when backend process restarts.",
    }


@router.post(
    "/debug/backfill-thumbnails",
    summary="Backfill missing thumbnail_url values",
)
async def backfill_missing_thumbnail_urls(
    _admin: AdminUser,
    limit: int = Query(500, ge=1, le=5000, description="Max number of variants to process in this run"),
    db: AsyncSession = Depends(get_db),
):
    """
    Compute and persist thumbnail_url for variants that are currently NULL.
    Uses existing resolve/backfill logic to keep behavior consistent.
    """
    rows = (
        await db.execute(
            select(ProductVariant.full_sku)
            .where(ProductVariant.thumbnail_url.is_(None))
            .order_by(ProductVariant.id)
            .limit(limit)
        )
    ).all()

    sku_list = [row.full_sku for row in rows]
    processed = 0
    updated = 0
    failed = 0
    updated_skus: list[str] = []
    failed_skus: list[str] = []

    for sku in sku_list:
        processed += 1
        _context, url = await _resolve_or_backfill_thumbnail_url(db, sku)
        if url:
            updated += 1
            updated_skus.append(sku)
        else:
            failed += 1
            failed_skus.append(sku)

    logger.debug("[DEBUG.INTERNAL_API][THUMB_TRACE] BULK_BACKFILL completed processed=%s updated=%s failed=%s limit=%s",
        processed,
        updated,
        failed,
        limit,
    )

    remaining_null_thumbnail_url = (
        await db.execute(
            select(func.count(ProductVariant.id)).where(ProductVariant.thumbnail_url.is_(None))
        )
    ).scalar_one()

    return {
        "processed": processed,
        "updated": updated,
        "failed": failed,
        "remaining_null_thumbnail_url": remaining_null_thumbnail_url,
        "updated_skus": updated_skus,
        "failed_skus": failed_skus,
    }


def _guess_media_type(path: Path) -> str:
    """Guess the MIME type from file extension."""
    ext = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return mime_map.get(ext, "application/octet-stream")





@router.post(
    "/{sku}/upload",
    summary="Upload images for a product variant SKU",
)
async def upload_sku_images(
    sku: str,
    _admin: AdminUser,
    files: list[UploadFile] = File(...),
    listing_index: int = Form(0),
    replace: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    if listing_index < 0 or listing_index > 9999:
        raise HTTPException(status_code=400, detail="Invalid listing_index")

    context = await _get_variant_context(db, sku)
    if context is None:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku}")

    listing_dir = _ensure_listing_dir(context, listing_index)

    if replace:
        for entry in listing_dir.iterdir():
            if entry.is_file() and entry.suffix.lower() in IMAGE_EXTENSION:
                entry.unlink()

    existing_indices = [
        _extract_image_index(f.name)
        for f in listing_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSION
    ]
    next_index = max([i for i in existing_indices if i is not None], default=-1) + 1

    saved_files: list[str] = []

    for upload in files:
        if not upload.filename:
            continue

        ext = Path(upload.filename).suffix.lower()
        if ext not in IMAGE_EXTENSION:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {ext}")

        target_name = f"img-{next_index}{ext}"
        next_index += 1

        target_tmp = listing_dir / f"{target_name}.tmp"
        target_final = listing_dir / target_name

        with target_tmp.open("wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)

        target_tmp.replace(target_final)
        saved_files.append(target_name)

    if not saved_files:
        raise HTTPException(status_code=400, detail="No valid files uploaded")

    await _recompute_thumbnail_url(db, context, mark_sync_dirty=True)
    return _build_sku_images_response(context)


@router.delete(
    "/{sku}/listing/{listing_index}/file/{filename}",
    summary="Delete a single image from a listing",
)
async def delete_sku_image(
    sku: str,
    listing_index: int,
    filename: str,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    if listing_index < 0 or listing_index > 9999:
        raise HTTPException(status_code=400, detail="Invalid listing_index")

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    context = await _get_variant_context(db, sku)
    if context is None:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku}")

    listing_dir = _ensure_listing_dir(context, listing_index)
    file_path = listing_dir / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found: {filename}")

    file_path.unlink()
    await _recompute_thumbnail_url(db, context, mark_sync_dirty=True)

    remaining = [
        f.name for f in listing_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSION
    ]
    return {
        "deleted": filename,
        "remaining": sorted(remaining),
        "thumbnail_url": context.thumbnail_url,
    }


@router.post(
    "/{sku}/listing/{listing_index}/clear",
    summary="Clear all images in a listing",
)
async def clear_sku_listing(
    sku: str,
    listing_index: int,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    if listing_index < 0 or listing_index > 9999:
        raise HTTPException(status_code=400, detail="Invalid listing_index")

    context = await _get_variant_context(db, sku)
    if context is None:
        raise HTTPException(status_code=404, detail=f"SKU not found: {sku}")

    listing_dir = _ensure_listing_dir(context, listing_index)
    deleted = 0
    for entry in listing_dir.iterdir():
        if entry.is_file() and entry.suffix.lower() in IMAGE_EXTENSION:
            entry.unlink()
            deleted += 1

    await _recompute_thumbnail_url(db, context, mark_sync_dirty=True)
    return {
        "cleared": deleted,
        "thumbnail_url": context.thumbnail_url,
    }

