#!/usr/bin/env python
"""Backfill default bundle variants for legacy identity-only bundles.

This maintenance script is idempotent and safe to run multiple times.
It ensures every bundle identity (type B) has a default variant where:
- color_code is NULL
- condition_code is NULL
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as: python scripts/backfill_bundle_default_variants.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import and_, func, select

from app.core.database import async_session_factory
from app.models import IdentityType, ProductIdentity, ProductVariant
from scripts.import_databasework_restart import RestartImporter


async def orphan_bundle_count() -> int:
    async with async_session_factory() as session:
        stmt = (
            select(func.count(ProductIdentity.id))
            .where(ProductIdentity.type == IdentityType.B)
            .where(
                ~select(ProductVariant.id)
                .where(
                    and_(
                        ProductVariant.identity_id == ProductIdentity.id,
                        ProductVariant.color_code.is_(None),
                        ProductVariant.condition_code.is_(None),
                    )
                )
                .exists()
            )
        )
        return int((await session.execute(stmt)).scalar_one())


async def run_backfill(dry_run: bool) -> None:
    before = await orphan_bundle_count()
    print(f"Orphan bundle identities before: {before}")

    async with async_session_factory() as session:
        importer = RestartImporter(session, dry_run=dry_run)
        repaired = await importer.repair_bundle_default_variants()

        if dry_run:
            await session.rollback()
            print("Dry run complete. Changes were rolled back.")
        else:
            await session.commit()
            print("Backfill committed.")

        print(f"Bundle identities seen:        {importer.stats.bundle_identities_seen}")
        print(f"Bundle defaults repaired:      {repaired}")
        print(f"Bundle defaults inactive:      {importer.stats.bundle_default_variants_inactive}")

    after = await orphan_bundle_count()
    print(f"Orphan bundle identities after:  {after}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing default variants for bundle identities")
    parser.add_argument("--dry-run", action="store_true", help="Run without persisting DB changes")
    args = parser.parse_args()

    asyncio.run(run_backfill(args.dry_run))


if __name__ == "__main__":
    main()
