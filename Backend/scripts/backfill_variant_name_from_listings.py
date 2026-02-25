#!/usr/bin/env python
"""Backfill product_variant.variant_name from shortest platform listing name.

Rules:
- For each variant, collect non-empty listed_name values from platform_listing
- Pick the shortest name (trimmed length); tie-break alphabetically
- Update product_variant.variant_name only when a candidate exists
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.entities import PlatformListing, ProductVariant


@dataclass
class BackfillStats:
    scanned: int = 0
    updated: int = 0
    skipped_no_listing_name: int = 0
    unchanged: int = 0


def _normalize_name(name: str | None) -> str | None:
    if name is None:
        return None
    normalized = " ".join(name.split()).strip()
    return normalized if normalized else None


def _select_shortest_name(candidates: list[str]) -> str | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda value: (len(value), value.lower()))[0]


async def run_backfill() -> BackfillStats:
    stats = BackfillStats()

    async with async_session_factory() as session:
        variants = (await session.execute(select(ProductVariant).order_by(ProductVariant.id))).scalars().all()

        for variant in variants:
            stats.scanned += 1

            rows = (
                await session.execute(
                    select(PlatformListing.listed_name)
                    .where(PlatformListing.variant_id == variant.id)
                )
            ).all()

            normalized_names = []
            for row in rows:
                normalized = _normalize_name(row[0])
                if normalized:
                    normalized_names.append(normalized)

            best_name = _select_shortest_name(normalized_names)
            if best_name is None:
                stats.skipped_no_listing_name += 1
                continue

            if variant.variant_name == best_name:
                stats.unchanged += 1
                continue

            variant.variant_name = best_name
            stats.updated += 1

        await session.commit()

    return stats


async def main() -> None:
    stats = await run_backfill()
    print("Variant name backfill complete")
    print(f"  scanned: {stats.scanned}")
    print(f"  updated: {stats.updated}")
    print(f"  unchanged: {stats.unchanged}")
    print(f"  skipped_no_listing_name: {stats.skipped_no_listing_name}")


if __name__ == "__main__":
    asyncio.run(main())
