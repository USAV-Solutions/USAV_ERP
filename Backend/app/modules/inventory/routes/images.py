"""
Product Image API endpoints.

Serves product variant images from /mnt/product_images/.
Directory structure: /mnt/product_images/{base_id}/{sku}/listing-{n}/img-{n}.{ext}

For each SKU, the listing folder with the most images is selected as the
"best" listing. img-0 is used as the thumbnail.
"""
import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["Product Images"])

IMAGES_ROOT = Path(getattr(settings, "product_images_path", "/mnt/product_images"))

# Allowed image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class ImageInfo(BaseModel):
    filename: str
    url: str


class SkuImagesResponse(BaseModel):
    sku: str
    listing: str
    total_images: int
    thumbnail_url: str
    images: list[ImageInfo]


def _find_sku_dir(sku: str) -> Optional[Path]:
    """
    Find the directory for a given SKU.
    Structure: /mnt/product_images/{base_id}/{sku}/
    where base_id is the numeric prefix of the SKU (e.g., 00010 from 00010-GY).
    """
    logger.info(f"[IMAGE_SEARCH] Searching for SKU: {sku}")
    logger.info(f"[IMAGE_SEARCH] Image root: {IMAGES_ROOT}")
    
    if not IMAGES_ROOT.is_dir():
        logger.warning(f"[IMAGE_SEARCH] Image root directory does not exist: {IMAGES_ROOT}")
        return None

    # List all top-level directories for debugging
    try:
        top_dirs = [d.name for d in IMAGES_ROOT.iterdir() if d.is_dir()]
        logger.info(f"[IMAGE_SEARCH] Available top-level directories: {top_dirs[:20]}...")  # First 20
    except Exception as e:
        logger.error(f"[IMAGE_SEARCH] Error listing directories: {e}")

    for top_dir in IMAGES_ROOT.iterdir():
        if not top_dir.is_dir():
            continue
        sku_path = top_dir / sku
        if sku_path.is_dir():
            logger.info(f"[IMAGE_SEARCH] ✓ Found SKU directory: {sku_path}")
            return sku_path

    logger.warning(f"[IMAGE_SEARCH] ✗ SKU directory not found for: {sku}")
    return None


def _get_best_listing(sku_dir: Path) -> Optional[tuple[str, Path]]:
    """
    Find the listing folder with the most images for a given SKU directory.
    Returns (listing_name, listing_path) or None.
    """
    logger.info(f"[IMAGE_SEARCH] Scanning listings in: {sku_dir}")
    best_listing: Optional[str] = None
    best_path: Optional[Path] = None
    best_count = 0
    listing_counts = {}

    for entry in sku_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("listing-"):
            continue

        img_count = sum(
            1 for f in entry.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
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
    
    logger.warning(f"[IMAGE_SEARCH] ✗ No valid listings found in {sku_dir}")
    return None


def _sorted_images(listing_path: Path) -> list[str]:
    """Return image filenames sorted by their numeric index (img-0, img-1, ...)."""
    files = [
        f.name for f in listing_path.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ]

    def sort_key(name: str) -> int:
        match = re.search(r"img-(\d+)", name)
        return int(match.group(1)) if match else 999

    return sorted(files, key=sort_key)


@router.get(
    "/{sku}",
    response_model=SkuImagesResponse,
    summary="Get image info for a product variant SKU",
)
async def get_sku_images(sku: str):
    """
    Returns image metadata for a product variant SKU.
    Automatically selects the listing folder with the most images.
    """
    logger.info(f"[IMAGE_API] GET /{sku} - Fetching image metadata")
    
    sku_dir = _find_sku_dir(sku)
    if not sku_dir:
        logger.warning(f"[IMAGE_API] GET /{sku} - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    result = _get_best_listing(sku_dir)
    if not result:
        logger.warning(f"[IMAGE_API] GET /{sku} - Returning 404: No listing folders found")
        raise HTTPException(status_code=404, detail=f"No listing folders found for SKU: {sku}")

    listing_name, listing_path = result
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

    logger.info(f"[IMAGE_API] GET /{sku} - Returning 200: {len(images)} images from {listing_name}")
    return SkuImagesResponse(
        sku=sku,
        listing=listing_name,
        total_images=len(image_files),
        thumbnail_url=f"/api/v1/images/{sku}/file/{image_files[0]}",
        images=images,
    )


@router.get(
    "/{sku}/thumbnail",
    summary="Get the thumbnail (img-0) for a product variant SKU",
)
async def get_sku_thumbnail(sku: str):
    """Serve img-0 from the best listing as the thumbnail."""
    logger.info(f"[IMAGE_API] GET /{sku}/thumbnail - Fetching thumbnail")
    
    sku_dir = _find_sku_dir(sku)
    if not sku_dir:
        logger.warning(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    result = _get_best_listing(sku_dir)
    if not result:
        logger.warning(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 404: No listing folders found")
        raise HTTPException(status_code=404, detail=f"No listing folders found for SKU: {sku}")

    listing_name, listing_path = result
    image_files = _sorted_images(listing_path)

    if not image_files:
        logger.warning(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 404: No images in best listing")
        raise HTTPException(status_code=404, detail=f"No images in best listing for SKU: {sku}")

    file_path = listing_path / image_files[0]
    logger.info(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 200: {file_path}")
    return FileResponse(
        path=str(file_path),
        media_type=_guess_media_type(file_path),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get(
    "/{sku}/file/{filename}",
    summary="Serve a specific image file for a product variant SKU",
)
async def get_sku_image_file(sku: str, filename: str):
    """Serve a specific image file from the best listing of a SKU."""
    logger.info(f"[IMAGE_API] GET /{sku}/file/{filename} - Fetching image file")
    
    # Security: prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 400: Invalid filename")
        raise HTTPException(status_code=400, detail="Invalid filename")

    sku_dir = _find_sku_dir(sku)
    if not sku_dir:
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    result = _get_best_listing(sku_dir)
    if not result:
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 404: No listing folders found")
        raise HTTPException(status_code=404, detail=f"No listing folders found for SKU: {sku}")

    listing_name, listing_path = result
    file_path = listing_path / filename

    if not file_path.is_file():
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 404: Image not found")
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
async def get_batch_thumbnails(skus: str):
    """
    Get thumbnail URLs for a comma-separated list of SKUs.
    Returns a mapping of SKU -> thumbnail_url (or null if not found).
    """
    sku_list = [s.strip() for s in skus.split(",") if s.strip()]
    logger.info(f"[IMAGE_API] GET /batch/thumbnails - Fetching thumbnails for {len(sku_list)} SKUs")
    result: dict[str, Optional[str]] = {}

    for sku in sku_list:
        sku_dir = _find_sku_dir(sku)
        if not sku_dir:
            result[sku] = None
            continue

        listing_result = _get_best_listing(sku_dir)
        if not listing_result:
            result[sku] = None
            continue

        listing_name, listing_path = listing_result
        image_files = _sorted_images(listing_path)

        if image_files:
            result[sku] = f"/api/v1/images/{sku}/thumbnail"
        else:
            result[sku] = None

    found_count = sum(1 for v in result.values() if v is not None)
    logger.info(f"[IMAGE_API] GET /batch/thumbnails - Returning 200: {found_count}/{len(sku_list)} thumbnails found")
    return result


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
