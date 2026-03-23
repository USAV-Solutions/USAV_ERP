#!/usr/bin/env python
# pyright: reportMissingImports=false
"""Verify SKU image rebuild coverage and DB thumbnail URL compliance."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.models import ProductVariant


CANONICAL_PREFIX = "/product-images/sku/"
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _has_final_images(sku_dir: Path) -> bool:
    return any(
        p.is_file() and p.name.startswith("img-") and p.suffix.lower() in SUPPORTED_EXTS
        for p in sku_dir.iterdir()
    )


async def _db_counts(active_only: bool) -> tuple[int, int, int, int]:
    async with async_session_factory() as db:
        base_query = select(ProductVariant.id)
        if active_only:
            base_query = base_query.where(ProductVariant.is_active == True)

        variant_ids = [row[0] for row in (await db.execute(base_query)).all()]
        total = len(variant_ids)

        if not variant_ids:
            return 0, 0, 0, 0

        with_thumbnail = (
            await db.execute(
                select(func.count(ProductVariant.id)).where(
                    ProductVariant.id.in_(variant_ids),
                    ProductVariant.thumbnail_url.is_not(None),
                )
            )
        ).scalar_one()

        canonical = (
            await db.execute(
                select(func.count(ProductVariant.id)).where(
                    ProductVariant.id.in_(variant_ids),
                    ProductVariant.thumbnail_url.like(f"{CANONICAL_PREFIX}%"),
                )
            )
        ).scalar_one()

        non_canonical = int(with_thumbnail) - int(canonical)

    return total, int(with_thumbnail), int(canonical), non_canonical


def _fs_counts(images_root: Path) -> tuple[int, int]:
    sku_root = images_root / "sku"
    if not sku_root.exists() or not sku_root.is_dir():
        return 0, 0

    sku_dirs = [p for p in sku_root.iterdir() if p.is_dir()]
    with_images = [p for p in sku_dirs if _has_final_images(p)]
    return len(sku_dirs), len(with_images)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Verify image rebuild coverage")
    parser.add_argument("--images-root", default="/mnt/product_images", help="Base image root")
    parser.add_argument("--active-only", action="store_true", help="Evaluate only active variants in DB")
    args = parser.parse_args()

    images_root = Path(args.images_root)
    sku_dirs, sku_dirs_with_images = _fs_counts(images_root)
    total, with_thumbnail, canonical, non_canonical = await _db_counts(active_only=args.active_only)

    print("Filesystem summary:")
    print(f"  sku_dirs={sku_dirs}")
    print(f"  sku_dirs_with_final_images={sku_dirs_with_images}")

    print("DB thumbnail summary:")
    print(f"  variants_in_scope={total}")
    print(f"  variants_with_thumbnail={with_thumbnail}")
    print(f"  canonical_thumbnail_prefix={canonical} ({CANONICAL_PREFIX})")
    print(f"  non_canonical_thumbnail_prefix={non_canonical}")

    if total > 0:
        coverage = (with_thumbnail / total) * 100.0
        canonical_ratio = (canonical / total) * 100.0
        print(f"  thumbnail_coverage_pct={coverage:.2f}")
        print(f"  canonical_coverage_pct={canonical_ratio:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
