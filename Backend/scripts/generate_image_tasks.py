#!/usr/bin/env python
# pyright: reportMissingImports=false
"""Generate image backfill task list from platform listings.

Outputs JSON or CSV records such as:
  {
    "sku": "00002-BK",
    "platform": "AMAZON",
    "external_id": "B00005T3NH",
    "variant_id": 123,
    "listing_id": 456
  }

Why this script exists:
- Extract once from DB, then run fetchers/downloader independently.
- Prevent long-running scraper jobs from keeping DB sessions open.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Iterable

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.models import Platform, PlatformListing, ProductVariant


def _parse_platforms(raw: str | None) -> set[Platform] | None:
    if not raw:
        return None
    parsed: set[Platform] = set()
    for token in raw.split(","):
        key = token.strip().upper()
        if not key:
            continue
        parsed.add(Platform(key))
    return parsed


def _serialize_rows(rows: Iterable[dict], output_path: Path, fmt: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(list(rows), f, indent=2)
        return

    fieldnames = ["sku", "platform", "external_id", "variant_id", "listing_id"]
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


async def _generate_tasks(
    output_path: Path,
    fmt: str,
    include_inactive: bool,
    platforms: set[Platform] | None,
    limit: int | None,
) -> None:
    async with async_session_factory() as db:
        stmt = (
            select(
                ProductVariant.id.label("variant_id"),
                ProductVariant.full_sku.label("sku"),
                ProductVariant.is_active,
                PlatformListing.id.label("listing_id"),
                PlatformListing.platform,
                PlatformListing.external_ref_id,
            )
            .join(PlatformListing, PlatformListing.variant_id == ProductVariant.id)
            .where(PlatformListing.external_ref_id.is_not(None))
            .order_by(ProductVariant.id, PlatformListing.id)
        )

        if not include_inactive:
            stmt = stmt.where(ProductVariant.is_active == True)

        if platforms:
            stmt = stmt.where(PlatformListing.platform.in_(platforms))

        if limit is not None:
            stmt = stmt.limit(limit)

        records = (await db.execute(stmt)).all()

    tasks: list[dict] = []
    for row in records:
        external_id = (row.external_ref_id or "").strip()
        if not external_id:
            continue
        tasks.append(
            {
                "sku": row.sku,
                "platform": row.platform.value,
                "external_id": external_id,
                "variant_id": int(row.variant_id),
                "listing_id": int(row.listing_id),
            }
        )

    _serialize_rows(tasks, output_path, fmt)
    print(f"Generated {len(tasks)} tasks -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate image backfill tasks from DB")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "scripts" / "image_tasks.json"),
        help="Output file path",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format",
    )
    parser.add_argument(
        "--platforms",
        default=None,
        help="Comma-separated platform enums: AMAZON,EBAY_MEKONG,EBAY_USAV,EBAY_DRAGON,ECWID",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive variants",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of listing tasks",
    )
    args = parser.parse_args()

    platforms = _parse_platforms(args.platforms)
    asyncio.run(
        _generate_tasks(
            output_path=Path(args.output),
            fmt=args.format,
            include_inactive=args.include_inactive,
            platforms=platforms,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
