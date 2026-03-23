#!/usr/bin/env python
# pyright: reportMissingImports=false
"""Preflight checks before wiping/rebuilding product images.

Checks:
- base image root exists
- canonical sku namespace exists (or can be created)
- optional requirement that sku namespace is empty
- optional DB thumbnail URL prefix summary
"""

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


def _count_files(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file())


async def _db_thumbnail_summary() -> tuple[int, int, int]:
    async with async_session_factory() as db:
        total_variants = (
            await db.execute(select(func.count(ProductVariant.id)))
        ).scalar_one()

        with_thumbnail = (
            await db.execute(
                select(func.count(ProductVariant.id)).where(ProductVariant.thumbnail_url.is_not(None))
            )
        ).scalar_one()

        canonical = (
            await db.execute(
                select(func.count(ProductVariant.id)).where(
                    ProductVariant.thumbnail_url.like(f"{CANONICAL_PREFIX}%")
                )
            )
        ).scalar_one()

    return int(total_variants), int(with_thumbnail), int(canonical)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight checks for image reset/rebuild")
    parser.add_argument("--images-root", default="/mnt/product_images", help="Base image root")
    parser.add_argument("--require-empty-sku-root", action="store_true", help="Fail if /sku namespace contains files")
    parser.add_argument("--create-sku-root", action="store_true", help="Create /sku namespace when missing")
    parser.add_argument("--check-db", action="store_true", help="Include DB thumbnail URL summary")
    args = parser.parse_args()

    images_root = Path(args.images_root)
    sku_root = images_root / "sku"

    print(f"Images root: {images_root}")
    print(f"SKU root: {sku_root}")

    if not images_root.exists() or not images_root.is_dir():
        raise SystemExit(f"FAIL: images root does not exist or is not a directory: {images_root}")

    if not sku_root.exists():
        if args.create_sku_root:
            sku_root.mkdir(parents=True, exist_ok=True)
            print("Created missing SKU namespace root.")
        else:
            raise SystemExit("FAIL: SKU namespace root missing. Use --create-sku-root.")

    if not sku_root.is_dir():
        raise SystemExit(f"FAIL: SKU root exists but is not a directory: {sku_root}")

    sku_files = _count_files(sku_root)
    sku_dirs = sum(1 for p in sku_root.iterdir() if p.is_dir())
    print(f"SKU namespace stats: dirs={sku_dirs} files={sku_files}")

    if args.require_empty_sku_root and sku_files > 0:
        raise SystemExit("FAIL: SKU namespace is not empty but --require-empty-sku-root is set")

    if args.check_db:
        total_variants, with_thumbnail, canonical = await _db_thumbnail_summary()
        print("DB thumbnail summary:")
        print(f"  total_variants={total_variants}")
        print(f"  with_thumbnail={with_thumbnail}")
        print(f"  canonical_prefix={canonical} ({CANONICAL_PREFIX})")

    print("Preflight passed.")


if __name__ == "__main__":
    asyncio.run(main())
