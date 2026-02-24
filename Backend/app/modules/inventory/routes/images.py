"""
Product Image API endpoints.

Serves product variant images from /mnt/product_images/.
Directory structure: /mnt/product_images/{generated_upis_h}/{full_sku}/listing-{n}/*.jpg

For each SKU, the listing folder with the most images is selected as the
"best" listing. The first sorted .jpg is used as the thumbnail.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.entities import ProductIdentity, ProductVariant

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
    Resolve SKU to generated_upis_h via DB and return expected variant image dir:
    /mnt/product_images/{generated_upis_h}/{full_sku}
    """
    if not IMAGES_ROOT.is_dir():
        logger.warning("[IMAGE_SEARCH] Image root directory does not exist: %s", IMAGES_ROOT)
        return None

    variant_dir = IMAGES_ROOT / context.generated_upis_h / context.full_sku
    logger.info(
        "[IMAGE_DEBUG] Resolved variant path for sku=%s -> upis_h=%s full_sku=%s path=%s",
        context.full_sku,
        context.generated_upis_h,
        context.full_sku,
        variant_dir,
    )
    if variant_dir.is_dir():
        logger.info("[IMAGE_SEARCH] Found variant directory: %s", variant_dir)
        return variant_dir

    logger.warning("[IMAGE_SEARCH] Variant directory not found: %s", variant_dir)
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
    logger.info(
        "[IMAGE_DEBUG] Listing directories under %s -> %s",
        variant_dir,
        [str(path) for path in sorted_dirs],
    )
    return sorted_dirs


def _get_best_listing(variant_dir: Path) -> Optional[tuple[str, Path]]:
    """
    Find the listing folder with the most .jpg images for a variant directory.
    Returns (listing_name, listing_path) or None.
    """
    logger.info(f"[IMAGE_SEARCH] Scanning listings in: {variant_dir}")
    best_listing: Optional[str] = None
    best_path: Optional[Path] = None
    best_count = 0
    listing_counts = {}

    for entry in _iter_listing_dirs(variant_dir):
        img_count = sum(
            1 for f in entry.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSION
        )
        listing_counts[entry.name] = img_count

        if img_count > best_count:
            best_count = img_count
            best_listing = entry.name
            best_path = entry

    logger.info(f"[IMAGE_SEARCH] Listing image counts: {listing_counts}")
    
    if best_listing and best_path:
        logger.info(f"[IMAGE_SEARCH] ✓ Best listing: {best_listing} with {best_count} images")
        return best_listing, best_path
    
    logger.warning(f"[IMAGE_SEARCH] ✗ No valid listings found in {variant_dir}")
    return None


def _sorted_images(listing_path: Path) -> list[str]:
    """Return .jpg image filenames sorted lexicographically."""
    files = [
        f.name for f in listing_path.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSION
    ]
    sorted_files = sorted(files)
    logger.info(
        "[IMAGE_DEBUG] JPG files in listing %s -> %s",
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
    return f"/product-images/{context.generated_upis_h}/{context.full_sku}/{listing_name}/{image_filename}"


async def _resolve_or_backfill_thumbnail_url(
    db: AsyncSession,
    sku: str,
) -> tuple[Optional[VariantImageContext], Optional[str]]:
    """
    Read thumbnail_url from DB when available.
    For legacy rows without thumbnail_url, compute best image URL and persist it.
    """
    logger.info("[THUMB_TRACE] Resolve requested for sku=%s", sku)
    context = await _get_variant_context(db, sku)
    if context is None:
        logger.warning("[THUMB_TRACE] Resolve result: SKU not found in DB for sku=%s", sku)
        return None, None

    if context.thumbnail_url:
        logger.warning(
            "[THUMB_TRACE] Cache hit for sku=%s variant_id=%s thumbnail_url=%s",
            context.full_sku,
            context.variant_id,
            context.thumbnail_url,
        )
        return context, context.thumbnail_url

    logger.warning(
        "[THUMB_TRACE] Cache miss for sku=%s variant_id=%s -> computing best listing",
        context.full_sku,
        context.variant_id,
    )

    variant_dir = _find_variant_dir(context)
    if not variant_dir:
        logger.warning("[THUMB_TRACE] Resolve failed: variant_dir not found for sku=%s", context.full_sku)
        return context, None

    listing_result = _get_best_listing(variant_dir)
    if not listing_result:
        logger.warning("[THUMB_TRACE] Resolve failed: no listing folders for sku=%s", context.full_sku)
        return context, None

    listing_name, listing_path = listing_result
    image_files = _sorted_images(listing_path)
    if not image_files:
        logger.warning("[THUMB_TRACE] Resolve failed: no images in best listing for sku=%s", context.full_sku)
        return context, None

    thumbnail_url = _build_public_thumbnail_url(context, listing_name, image_files[0])

    await db.execute(
        update(ProductVariant)
        .where(ProductVariant.id == context.variant_id)
        .values(thumbnail_url=thumbnail_url)
    )
    await db.commit()
    context.thumbnail_url = thumbnail_url

    logger.info(
        "[THUMB_DEBUG] Backfilled thumbnail_url for sku=%s variant_id=%s -> %s",
        context.full_sku,
        context.variant_id,
        thumbnail_url,
    )
    return context, thumbnail_url


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
    logger.info(f"[IMAGE_API] GET /{sku} - Fetching image metadata")

    context, resolved_thumbnail_url = await _resolve_or_backfill_thumbnail_url(db, sku)

    if context is None:
        logger.warning(f"[IMAGE_API] GET /{sku} - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    variant_dir = _find_variant_dir(context)

    if not variant_dir:
        logger.warning(f"[IMAGE_API] GET /{sku} - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    result = _get_best_listing(variant_dir)
    if not result:
        logger.warning(f"[IMAGE_API] GET /{sku} - Returning 404: No listing folders found")
        raise HTTPException(status_code=404, detail=f"No listing folders found for SKU: {sku}")

    listing_name, listing_path = result
    logger.info(
        "[IMAGE_DEBUG] Selected listing for sku=%s -> listing=%s path=%s",
        sku,
        listing_name,
        listing_path,
    )
    image_files = _sorted_images(listing_path)

    if not image_files:
        logger.warning(f"[IMAGE_API] GET /{sku} - Returning 404: No images in best listing")
        raise HTTPException(status_code=404, detail=f"No images in best listing for SKU: {sku}")

    images = [
        ImageInfo(
            filename=fname,
            url=f"/api/v1/images/{sku}/file/{fname}",
        )
        for fname in image_files
    ]

    logger.info(
        "[IMAGE_DEBUG] Response URLs for sku=%s -> thumbnail=%s images=%s",
        context.full_sku,
        resolved_thumbnail_url or f"/api/v1/images/{context.full_sku}/file/{image_files[0]}",
        [img.url for img in images],
    )

    logger.info(f"[IMAGE_API] GET /{sku} - Returning 200: {len(images)} images from {listing_name}")
    return SkuImagesResponse(
        sku=context.full_sku,
        listing=listing_name,
        total_images=len(image_files),
        thumbnail_url=resolved_thumbnail_url or f"/api/v1/images/{context.full_sku}/file/{image_files[0]}",
        images=images,
    )


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
    logger.warning(
        "[THUMB_TRACE] ROUTE_HIT method=%s path=%s sku=%s host=%s forwarded_for=%s forwarded_proto=%s user_agent=%s referer=%s",
        request.method,
        request.url.path,
        sku,
        request.headers.get("host"),
        request.headers.get("x-forwarded-for"),
        request.headers.get("x-forwarded-proto"),
        request.headers.get("user-agent"),
        request.headers.get("referer"),
    )
    logger.info(f"[IMAGE_API] GET /{sku}/thumbnail - Fetching thumbnail")
    logger.info("[THUMB_DEBUG] Incoming request path: %s", request.url.path)
    if "/api/v1/api/v1/" in request.url.path:
        logger.warning(
            "[THUMB_DEBUG] Detected duplicated API prefix in request path: %s",
            request.url.path,
        )

    context, thumbnail_url = await _resolve_or_backfill_thumbnail_url(db, sku)

    logger.warning(
        "[THUMB_TRACE] ROUTE_RESOLVE sku=%s context_found=%s thumbnail_url=%s",
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

    logger.info(
        "[IMAGE_API] GET /%s/thumbnail - Returning redirect to %s",
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
    logger.info(f"[IMAGE_API] GET /{sku}/file/{filename} - Fetching image file")
    logger.info("[IMAGE_DEBUG] Incoming request path: %s", request.url.path)
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
    logger.info(
        "[IMAGE_DEBUG] Checking requested JPG path for sku=%s listing=%s filename=%s -> %s",
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

    logger.info(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 200: {file_path}")
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
    logger.info(f"[IMAGE_API] GET /batch/thumbnails - Fetching thumbnails for {len(sku_list)} SKUs")
    result: dict[str, Optional[str]] = {}

    for sku in sku_list:
        context, thumbnail_url = await _resolve_or_backfill_thumbnail_url(db, sku)
        if context is None:
            result[sku] = None
            continue

        result[context.full_sku] = thumbnail_url

    found_count = sum(1 for v in result.values() if v is not None)
    logger.info(f"[IMAGE_API] GET /batch/thumbnails - Returning 200: {found_count}/{len(sku_list)} thumbnails found")
    return result


@router.get(
    "/debug/counters",
    summary="Debug counters for image routes",
)
async def get_image_debug_counters():
    """Return in-memory counters showing which image routes are receiving traffic."""
    return {
        "counters": IMAGE_DEBUG_COUNTERS,
        "note": "In-memory counters reset when backend process restarts.",
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
