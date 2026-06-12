"""
Fill inventory_sku in the older Amazon FBA opening-stock CSV format by matching
lowercase asin to platform_listing.external_ref_id for Platform.AMAZON.

Example:
    python scripts/fba_opening_stock_inventory_sku_match_old_csv.py \
        --input /workspace/misc/'FBA AMZ - Opening Stock @6.8.2026.csv'
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import async_session_factory
from app.models.entities import Platform, PlatformListing, ProductVariant


@dataclass(frozen=True)
class MatchRow:
    asin: str
    inventory_sku: str | None
    listing_id: int | None
    variant_id: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill inventory_sku in old-format FBA opening-stock CSV from platform listings.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to source CSV file.",
    )
    parser.add_argument(
        "--output",
        help="Path to output CSV file. Defaults to <input>_with_inventory_sku.csv",
    )
    return parser.parse_args()


def normalize_asin(value: object) -> str:
    return str(value or "").strip().upper()


def default_output_path(input_path: Path) -> Path:
    suffix = "".join(input_path.suffixes) or ".csv"
    stem = input_path.name[: -len(suffix)] if suffix else input_path.name
    return input_path.with_name(f"{stem}_with_inventory_sku.csv")


async def load_matches(session: AsyncSession, asins: set[str]) -> dict[str, MatchRow]:
    if not asins:
        return {}

    stmt: Select = (
        select(
            PlatformListing.external_ref_id,
            ProductVariant.full_sku,
            PlatformListing.id,
            ProductVariant.id,
        )
        .select_from(PlatformListing)
        .outerjoin(ProductVariant, ProductVariant.id == PlatformListing.variant_id)
        .where(PlatformListing.platform == Platform.AMAZON)
        .where(PlatformListing.external_ref_id.in_(sorted(asins)))
    )
    rows = (await session.execute(stmt)).all()

    matches: dict[str, MatchRow] = {}
    for external_ref_id, full_sku, listing_id, variant_id in rows:
        asin = normalize_asin(external_ref_id)
        if not asin or asin in matches:
            continue
        matches[asin] = MatchRow(
            asin=asin,
            inventory_sku=str(full_sku).strip() if full_sku else None,
            listing_id=int(listing_id) if listing_id is not None else None,
            variant_id=int(variant_id) if variant_id is not None else None,
        )
    return matches


def read_rows(input_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Input CSV is missing a header row.")
        rows = list(reader)
        return rows, list(reader.fieldnames)


def write_rows(
    output_path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def run(input_path: Path, output_path: Path) -> None:
    rows, fieldnames = read_rows(input_path)
    if "asin" not in fieldnames:
        raise ValueError("Input CSV must contain an 'asin' column.")
    if "inventory_sku" not in fieldnames:
        fieldnames.append("inventory_sku")

    asins = {
        normalize_asin(row.get("asin"))
        for row in rows
        if normalize_asin(row.get("asin"))
    }

    async with async_session_factory() as session:
        matches = await load_matches(session, asins)

    total_rows = len(rows)
    matched_rows = 0
    missing_asin_rows = 0
    unresolved_listing_rows = 0
    unmatched_rows = 0

    for row in rows:
        asin = normalize_asin(row.get("asin"))
        if not asin:
            row["inventory_sku"] = ""
            missing_asin_rows += 1
            continue

        match = matches.get(asin)
        if match is None:
            row["inventory_sku"] = ""
            unmatched_rows += 1
            continue

        if not match.inventory_sku:
            row["inventory_sku"] = ""
            unresolved_listing_rows += 1
            continue

        row["inventory_sku"] = match.inventory_sku
        matched_rows += 1

    write_rows(output_path, rows, fieldnames)

    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Total rows: {total_rows}")
    print(f"Matched rows: {matched_rows}")
    print(f"Rows with missing ASIN: {missing_asin_rows}")
    print(f"Rows with listing but no linked variant SKU: {unresolved_listing_rows}")
    print(f"Rows with no Amazon platform listing match: {unmatched_rows}")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else default_output_path(input_path).resolve()
    )

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(input_path, output_path))


if __name__ == "__main__":
    main()
