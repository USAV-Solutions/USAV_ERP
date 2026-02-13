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
    Structure: /mnt/product_images/{product_id}/{sku}/listing-{n}/img-{n}.{ext}
    
    The product_id is extracted from the SKU (the first part before the dash),
    and formatted as 5-digit zero-padded (e.g., 00002).
    
    Example: SKU "00002-BK" → path is /mnt/product_images/00002/00002-BK/
    """
    print(f"\n[IMAGE_SEARCH] ========== SEARCHING FOR SKU: {sku} ==========")
    print(f"[IMAGE_SEARCH] Image root: {IMAGES_ROOT}")
    
    if not IMAGES_ROOT.exists():
        print(f"[IMAGE_SEARCH] ❌ Root path does NOT exist: {IMAGES_ROOT}")
        logger.warning(f"[IMAGE_SEARCH] Root path does not exist: {IMAGES_ROOT}")
        return None
    
    if not IMAGES_ROOT.is_dir():
        print(f"[IMAGE_SEARCH] ❌ Root path exists but is NOT a directory: {IMAGES_ROOT}")
        logger.warning(f"[IMAGE_SEARCH] Root path exists but is not a directory: {IMAGES_ROOT}")
        return None
    
    print(f"[IMAGE_SEARCH] ✓ Root exists and is a directory")
    
    # Extract product_id from SKU (first part before dash)
    # Examples: "00002-BK" -> "00002", "00001-B" -> "00001", "00845-P-1-WY-N" -> "00845"
    parts = sku.split("-")
    product_id = parts[0]
    print(f"[IMAGE_SEARCH] Extracted product_id from SKU: {product_id}")
    
    # Format product_id as 5-digit zero-padded
    try:
        product_id_int = int(product_id)
        product_id_formatted = f"{product_id_int:05d}"
        print(f"[IMAGE_SEARCH] Formatted product_id: {product_id_formatted} (from int: {product_id_int})")
    except ValueError:
        print(f"[IMAGE_SEARCH] ⚠️  Could not parse product_id as int: {product_id}")
        product_id_formatted = product_id
    
    # Construct the expected path: /mnt/product_images/{product_id}/{sku}/
    sku_path = IMAGES_ROOT / product_id_formatted / sku
    print(f"[IMAGE_SEARCH] Checking path: {sku_path}")
    
    try:
        if sku_path.exists():
            print(f"[IMAGE_SEARCH] ✓ Path EXISTS: {sku_path}")
            if sku_path.is_dir():
                print(f"[IMAGE_SEARCH] ✓ Path IS a directory")
                print(f"[IMAGE_SEARCH] ✓✓✓ FOUND SKU: {sku}")
                logger.info(f"[IMAGE_SEARCH] Found SKU directory: {sku_path}")
                return sku_path
            else:
                print(f"[IMAGE_SEARCH] ❌ Path exists but is NOT a directory")
                return None
        else:
            print(f"[IMAGE_SEARCH] ❌ Path does NOT exist: {sku_path}")
            # Check if product_id directory exists
            product_dir = IMAGES_ROOT / product_id_formatted
            print(f"[IMAGE_SEARCH] Checking product_id directory: {product_dir}")
            print(f"[IMAGE_SEARCH]   - Exists: {product_dir.exists()}")
            
            if product_dir.exists() and product_dir.is_dir():
                print(f"[IMAGE_SEARCH] Product directory exists, listing its contents:")
                try:
                    entries = sorted([d.name for d in product_dir.iterdir()])
                    for entry in entries:
                        print(f"[IMAGE_SEARCH]   - {entry}")
                except Exception as e:
                    print(f"[IMAGE_SEARCH] Error listing product directory: {e}")
            return None
    except PermissionError as e:
        print(f"[IMAGE_SEARCH] ❌ PERMISSION DENIED accessing {sku_path}: {e}")
        logger.error(f"[IMAGE_SEARCH] Permission denied: {sku_path}: {e}")
        return None
    except Exception as e:
        print(f"[IMAGE_SEARCH] ❌ ERROR accessing {sku_path}: {e}")
        logger.error(f"[IMAGE_SEARCH] Error accessing {sku_path}: {e}")
        return None


def _get_best_listing(sku_dir: Path) -> Optional[tuple[str, Path]]:
    """
    Find the listing folder with the most images for a given SKU directory.
    Returns (listing_name, listing_path) or None.
    """
    print(f"[IMAGE_SEARCH] Scanning listings in: {sku_dir}")
    print(f"[IMAGE_SEARCH] Directory exists: {sku_dir.exists()}")
    print(f"[IMAGE_SEARCH] Is directory: {sku_dir.is_dir()}")
    
    best_listing: Optional[str] = None
    best_path: Optional[Path] = None
    best_count = 0
    listing_counts = {}

    try:
        for entry in sku_dir.iterdir():
            if not entry.is_dir():
                print(f"[IMAGE_SEARCH]   {entry.name} - not a directory, skipping")
                continue
            if not entry.name.startswith("listing-"):
                print(f"[IMAGE_SEARCH]   {entry.name} - not a listing folder, skipping")
                continue

            img_count = sum(
                1 for f in entry.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
            )
            listing_counts[entry.name] = img_count
            print(f"[IMAGE_SEARCH]   {entry.name}: {img_count} images")

            if img_count > best_count:
                best_count = img_count
                best_listing = entry.name
                best_path = entry
    except Exception as e:
        print(f"[IMAGE_SEARCH] ❌ Error scanning listings: {e}")
        logger.error(f"[IMAGE_SEARCH] Error scanning listings: {e}")
        return None
    
    print(f"[IMAGE_SEARCH] Listing summary: {listing_counts}")
    
    if best_listing and best_path:
        print(f"[IMAGE_SEARCH] ✓ Best listing: {best_listing} with {best_count} images")
        logger.info(f"[IMAGE_SEARCH] Best listing: {best_listing} with {best_count} images")
        return best_listing, best_path
    
    print(f"[IMAGE_SEARCH] ❌ No valid listings found")
    logger.warning(f"[IMAGE_SEARCH] No valid listings found in {sku_dir}")
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
    print(f"\n[IMAGE_API] ========== GET IMAGES FOR SKU: {sku} ==========")
    logger.info(f"[IMAGE_API] GET /{sku} - Fetching image metadata")
    
    sku_dir = _find_sku_dir(sku)
    if not sku_dir:
        print(f"[IMAGE_API] ❌ GET /{sku} - SKU directory was not found")
        logger.warning(f"[IMAGE_API] GET /{sku} - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")
    
    print(f"[IMAGE_API] ✓ SKU directory found: {sku_dir}")

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
            url=f"/images/{sku}/file/{fname}",
        )
        for fname in image_files
    ]

    logger.info(f"[IMAGE_API] GET /{sku} - Returning 200: {len(images)} images from {listing_name}")
    return SkuImagesResponse(
        sku=sku,
        listing=listing_name,
        total_images=len(image_files),
        thumbnail_url=f"/images/{sku}/file/{image_files[0]}",
        images=images,
    )


@router.get(
    "/{sku}/thumbnail",
    summary="Get the thumbnail (img-0) for a product variant SKU",
)
async def get_sku_thumbnail(sku: str):
    """Serve img-0 from the best listing as the thumbnail."""
    print(f"\n[IMAGE_API] ========== GET THUMBNAIL FOR SKU: {sku} ==========")
    logger.info(f"[IMAGE_API] GET /{sku}/thumbnail - Fetching thumbnail")
    
    sku_dir = _find_sku_dir(sku)
    if not sku_dir:
        print(f"[IMAGE_API] ❌ GET /{sku}/thumbnail - SKU directory not found")
        logger.warning(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    print(f"[IMAGE_API] ✓ SKU directory found, looking for best listing")
    result = _get_best_listing(sku_dir)
    if not result:
        print(f"[IMAGE_API] ❌ No listing folders found")
        logger.warning(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 404: No listing folders found")
        raise HTTPException(status_code=404, detail=f"No listing folders found for SKU: {sku}")

    listing_name, listing_path = result
    image_files = _sorted_images(listing_path)

    if not image_files:
        print(f"[IMAGE_API] ❌ No images in best listing: {listing_name}")
        logger.warning(f"[IMAGE_API] GET /{sku}/thumbnail - Returning 404: No images in best listing")
        raise HTTPException(status_code=404, detail=f"No images in best listing for SKU: {sku}")

    file_path = listing_path / image_files[0]
    print(f"[IMAGE_API] ✓ Returning thumbnail: {file_path}")
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
    print(f"\n[IMAGE_API] ========== GET FILE FOR SKU: {sku}, FILE: {filename} ==========")
    logger.info(f"[IMAGE_API] GET /{sku}/file/{filename} - Fetching image file")
    
    # Security: prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        print(f"[IMAGE_API] ❌ Invalid filename (possible path traversal): {filename}")
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 400: Invalid filename")
        raise HTTPException(status_code=400, detail="Invalid filename")

    sku_dir = _find_sku_dir(sku)
    if not sku_dir:
        print(f"[IMAGE_API] ❌ SKU directory not found")
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 404: No images found")
        raise HTTPException(status_code=404, detail=f"No images found for SKU: {sku}")

    print(f"[IMAGE_API] ✓ SKU directory found, looking for best listing")
    result = _get_best_listing(sku_dir)
    if not result:
        print(f"[IMAGE_API] ❌ No listing folders found")
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 404: No listing folders found")
        raise HTTPException(status_code=404, detail=f"No listing folders found for SKU: {sku}")

    listing_name, listing_path = result
    print(f"[IMAGE_API] ✓ Using listing: {listing_name}")
    file_path = listing_path / filename
    print(f"[IMAGE_API] Checking file path: {file_path}")
    print(f"[IMAGE_API]   - File exists: {file_path.exists()}")
    print(f"[IMAGE_API]   - Is file: {file_path.is_file()}")

    if not file_path.is_file():
        print(f"[IMAGE_API] ❌ File not found or not a file: {file_path}")
        logger.warning(f"[IMAGE_API] GET /{sku}/file/{filename} - Returning 404: Image not found")
        raise HTTPException(status_code=404, detail=f"Image not found: {filename}")

    print(f"[IMAGE_API] ✓ Returning file: {file_path}")
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
            result[sku] = f"/images/{sku}/thumbnail"
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
