#!/usr/bin/env python
# pyright: reportMissingImports=false
"""Sync flattened SKU thumbnails into product_variant.thumbnail_url.

Expected flattened layout:
    {images_root}/sku/{sku}/img-0.jpg

DB update rule:
    UPDATE product_variant SET thumbnail_url = /product-images/sku/{sku}/img-0.jpg
  WHERE full_sku = {sku}
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.models import ProductVariant


SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _find_primary_image(sku_dir: Path) -> Path | None:
    for ext in SUPPORTED_EXTS:
        candidate = sku_dir / f"img-0{ext}"
        if candidate.exists() and candidate.is_file():
            return candidate

    # Fallback: pick first img-* file if img-0.* does not exist.
    candidates = [
        p
        for p in sku_dir.iterdir()
        if p.is_file() and p.name.startswith("img-") and p.suffix.lower() in SUPPORTED_EXTS
    ]
    if not candidates:
        return None
    return sorted(candidates)[0]


async def _run(images_root: Path, dry_run: bool) -> None:
    if not images_root.exists():
        raise SystemExit(f"Images root not found: {images_root}")

    updated = 0
    missing_variant = 0
    scanned = 0

    sku_root = images_root / "sku"
    if not sku_root.exists() or not sku_root.is_dir():
        raise SystemExit(f"SKU namespace root not found: {sku_root}")

    async with async_session_factory() as db:
        for sku_dir in sorted([p for p in sku_root.iterdir() if p.is_dir()]):
            sku = sku_dir.name.strip()
            if not sku:
                continue
            scanned += 1

            primary = _find_primary_image(sku_dir)
            if primary is None:
                continue

            thumbnail_url = f"/product-images/sku/{sku}/{primary.name}"
            variant = (
                await db.execute(select(ProductVariant).where(ProductVariant.full_sku == sku))
            ).scalar_one_or_none()
            if variant is None:
                missing_variant += 1
                continue

            if variant.thumbnail_url == thumbnail_url:
                continue

            variant.thumbnail_url = thumbnail_url
            db.add(variant)
            updated += 1

        if dry_run:
            await db.rollback()
            print("Dry run complete. No DB changes committed.")
        else:
            await db.commit()

    print(f"Scanned sku dirs: {scanned}")
    print(f"Variants updated: {updated}")
    print(f"SKU dirs with no matching variant: {missing_variant}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync local SKU thumbnails to DB")
    parser.add_argument("--images-root", default="/mnt/product_images", help="Base image root containing /sku namespace")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    asyncio.run(_run(Path(args.images_root), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
