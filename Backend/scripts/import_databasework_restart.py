#!/usr/bin/env python
"""Restart importer for DatabaseWork CSV.

This script is designed for a reset workflow where core catalog rows are removed
before import. It writes directly to the database using SQLAlchemy.

Flow:
1) Products and product variants
2) Parts and part variants
3) Bundles and bundle components
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Allow running as: python scripts/import_databasework_restart.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_factory
from app.models import (
    BundleComponent,
    BundleRole,
    ConditionCode,
    IdentityType,
    LCIDefinition,
    Platform,
    PlatformListing,
    ProductFamily,
    ProductIdentity,
    ProductVariant,
)
from app.repositories.product import ProductIdentityRepository, ProductVariantRepository

DEFAULT_CSV_PATH = Path("..") / "misc" / "DatabaseWork (version 1).csv"

PLATFORM_MAP: dict[str, Platform] = {
    "Amazon": Platform.AMAZON,
    "MEKONG_eBay": Platform.EBAY_MEKONG,
    "USAV_eBay": Platform.EBAY_USAV,
    "DRAGON_eBay": Platform.EBAY_DRAGON,
    "Ecwid": Platform.ECWID,
}

COLOR_NAME_MAP: dict[str, str] = {
    "GR": "Graphite",
    "CH": "Cherry",
    "BK": "Black",
    "WH": "White",
    "GY": "Grey",
    "PL": "Platinum White",
    "CR": "Cream",
}

CONDITION_NAME_MAP: dict[Optional[ConditionCode], str] = {
    ConditionCode.N: "New",
    ConditionCode.R: "Refurbished",
    ConditionCode.U: "Used",
    None: "",
}


@dataclass
class CsvRow:
    group_id: int
    group_name: str
    product_type: str
    product_color: Optional[str]
    product_condition: Optional[ConditionCode]
    listing_name: str
    component_type: Optional[str]
    included_products: Optional[str]
    sku: str
    platform: str
    asin: Optional[str]

    @classmethod
    def from_dict(cls, row: dict[str, str]) -> "CsvRow":
        raw_condition = (row.get("Product Condition") or "").strip().upper()
        condition = None
        if raw_condition in {"N", "R", "U"}:
            condition = ConditionCode(raw_condition)

        raw_color = (row.get("Product Color") or "").strip().upper()
        color = raw_color or None

        return cls(
            group_id=int((row.get("groupid") or "0").strip()),
            group_name=(row.get("Group Name") or "").strip(),
            product_type=(row.get("Product Type") or "").strip(),
            product_color=color,
            product_condition=condition,
            listing_name=(row.get("name") or "").strip(),
            component_type=((row.get("Component Type") or "").strip() or None),
            included_products=((row.get("Included Products") or "").strip() or None),
            sku=(row.get("sku") or "").strip(),
            platform=(row.get("platform") or "").strip(),
            asin=((row.get("ASIN") or "").strip() or None),
        )


@dataclass
class GroupBucket:
    group_id: int
    group_name: str
    rows: list[CsvRow] = field(default_factory=list)


@dataclass
class Stats:
    families_created: int = 0
    identities_created: int = 0
    variants_created: int = 0
    listings_created: int = 0
    lci_definitions_created: int = 0
    bundle_components_created: int = 0
    bundle_families_created: int = 0
    bundle_identities_seen: int = 0
    bundle_default_variants_repaired: int = 0
    bundle_default_variants_inactive: int = 0


@dataclass
class VerificationReport:
    duplicate_skus: list[tuple[str, int]] = field(default_factory=list)
    missing_default_variants: list[str] = field(default_factory=list)
    duplicate_lci_rows: list[tuple[int, int, int]] = field(default_factory=list)
    orphan_bundle_upis_h: list[str] = field(default_factory=list)
    inactive_bundle_default_upis_h: list[str] = field(default_factory=list)


def format_family_code(product_id: int) -> str:
    return f"{product_id:05d}"


def parse_included_products(value: Optional[str]) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    parts: list[str] = []
    for chunk in value.split(","):
        item = chunk.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(item)
    return parts


def compose_name(base: str, color_code: Optional[str], condition_code: Optional[ConditionCode]) -> str:
    color_name = COLOR_NAME_MAP.get((color_code or "").upper(), "") if color_code else ""
    condition_name = CONDITION_NAME_MAP.get(condition_code, "")
    return " ".join(part for part in [base.strip(), color_name, condition_name] if part).strip()


def normalize_name(value: str) -> str:
    return " ".join(value.lower().split())


class RestartImporter:
    def __init__(self, session: AsyncSession, dry_run: bool = False):
        self.session = session
        self.identity_repo = ProductIdentityRepository(session)
        self.variant_repo = ProductVariantRepository(session)
        self.dry_run = dry_run
        self.stats = Stats()
        self._family_by_group_id: dict[int, ProductFamily] = {}
        self._temp_family_code_counter = 0

    async def run(self, groups: list[GroupBucket]) -> None:
        # Pass 1: products + parts.
        for group in groups:
            await self._process_group_products_and_parts(group)

        # Pass 2: bundles after all product/part components are available.
        for group in groups:
            await self._process_group_bundles(group)

        # Pass 3: repair legacy bundle identities that might not have default variants.
        await self.repair_bundle_default_variants()

    async def repair_bundle_default_variants(self) -> int:
        stmt = select(ProductIdentity).where(ProductIdentity.type == IdentityType.B)
        bundle_identities = list((await self.session.execute(stmt)).scalars().all())
        self.stats.bundle_identities_seen = len(bundle_identities)

        repaired = 0
        inactive_defaults = 0
        for identity in bundle_identities:
            default_variant = await self._get_default_variant(identity.id)
            if default_variant is None:
                family = await self.session.get(ProductFamily, identity.product_id)
                base_name = (identity.identity_name or (family.base_name if family else None) or identity.generated_upis_h).strip()
                await self._get_or_create_variant(identity, None, None, base_name)
                repaired += 1
            elif not default_variant.is_active:
                inactive_defaults += 1

        self.stats.bundle_default_variants_repaired = repaired
        self.stats.bundle_default_variants_inactive = inactive_defaults
        return repaired

    async def _process_group_products_and_parts(self, group: GroupBucket) -> None:
        product_rows = [r for r in group.rows if r.product_type.lower() == "product"]
        part_rows = [r for r in group.rows if r.product_type.lower() == "parts"]

        if not product_rows and not part_rows:
            return

        family = await self._get_or_create_family(group.group_id, group.group_name)
        product_identity = await self._get_or_create_product_identity(family, group.group_name)

        await self._ensure_variant_and_listings(
            identity=product_identity,
            base_name=group.group_name,
            rows=product_rows,
            ensure_default=True,
        )

        # Parts grouped by component type.
        parts_by_component: dict[str, list[CsvRow]] = defaultdict(list)
        for row in part_rows:
            component = row.component_type or "Component"
            parts_by_component[component].append(row)

        for component, rows in parts_by_component.items():
            part_identity = await self._get_or_create_part_identity(
                family=family,
                group_name=group.group_name,
                component_name=component,
            )
            await self._ensure_variant_and_listings(
                identity=part_identity,
                base_name=part_identity.identity_name or f"{group.group_name} - {component}",
                rows=rows,
                ensure_default=False,
            )

    async def _process_group_bundles(self, group: GroupBucket) -> None:
        bundle_rows = [r for r in group.rows if r.product_type.lower() == "bundle"]
        if not bundle_rows:
            return

        source_family = await self._get_or_create_family(group.group_id, group.group_name)

        # Bundle rows can have different included component configurations.
        rows_by_components: dict[tuple[str, ...], list[CsvRow]] = defaultdict(list)
        for row in bundle_rows:
            components = tuple(parse_included_products(row.included_products))
            rows_by_components[components].append(row)

        for component_tuple, rows in rows_by_components.items():
            if not component_tuple:
                continue

            component_identities: list[ProductIdentity] = []
            for idx, component_name in enumerate(component_tuple):
                component_identity = await self._resolve_component_identity(
                    source_family=source_family,
                    group_name=group.group_name,
                    component_name=component_name,
                )
                component_identities.append(component_identity)

                # Bundle row color/condition applies to the first component variant.
                if idx == 0:
                    color = rows[0].product_color
                    condition = rows[0].product_condition
                    if color or condition:
                        await self._ensure_first_component_variant(component_identity, component_name, color, condition)

            bundle_name = self._build_bundle_name([i.identity_name or i.generated_upis_h for i in component_identities])
            bundle_family = await self._get_or_create_bundle_family(bundle_name)
            bundle_identity = await self._get_or_create_bundle_identity(bundle_family, bundle_name)
            bundle_variant = await self._get_or_create_variant(bundle_identity, None, None, bundle_name)

            await self._create_bundle_components(bundle_identity, component_identities)

            for row in rows:
                await self._get_or_create_listing(bundle_variant, row)

    async def _next_temp_family_code(self) -> str:
        self._temp_family_code_counter += 1
        return f"z{self._temp_family_code_counter:04d}"

    async def _create_family_auto(self, base_name: str) -> ProductFamily:
        # Insert with temporary unique code first; replace with canonical code after DB assigns product_id.
        family = ProductFamily(base_name=base_name, family_code=await self._next_temp_family_code())
        self.session.add(family)
        await self.session.flush()

        family.family_code = format_family_code(family.product_id)
        await self.session.flush()

        self.stats.families_created += 1
        return family

    async def _get_or_create_family(self, group_id: int, base_name: str) -> ProductFamily:
        cached = self._family_by_group_id.get(group_id)
        if cached is not None:
            return cached

        stmt = (
            select(ProductFamily)
            .where(ProductFamily.base_name == base_name)
            .order_by(ProductFamily.product_id)
            .limit(1)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            self._family_by_group_id[group_id] = existing
            return existing

        created = await self._create_family_auto(base_name)
        self._family_by_group_id[group_id] = created
        return created

    async def _get_or_create_product_identity(self, family: ProductFamily, group_name: str) -> ProductIdentity:
        stmt = (
            select(ProductIdentity)
            .where(ProductIdentity.product_id == family.product_id)
            .where(ProductIdentity.type == IdentityType.PRODUCT)
            .limit(1)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            if not existing.identity_name:
                existing.identity_name = group_name
            return existing

        data = {
            "product_id": family.product_id,
            "type": IdentityType.PRODUCT,
            "identity_name": group_name,
        }
        identity = await self.identity_repo.create_identity(data)
        self.stats.identities_created += 1
        return identity

    async def _get_or_create_part_identity(
        self,
        family: ProductFamily,
        group_name: str,
        component_name: str,
    ) -> ProductIdentity:
        identity_name = f"{group_name} - {component_name}".strip()
        existing = await self._find_identity_by_name(identity_name)
        if existing is not None and existing.product_id == family.product_id and existing.type == IdentityType.P:
            return existing

        lci = await self.identity_repo.get_next_lci(family.product_id)
        await self._get_or_create_lci_definition(family.product_id, lci, component_name)

        data = {
            "product_id": family.product_id,
            "type": IdentityType.P,
            "lci": lci,
            "identity_name": identity_name,
        }
        identity = await self.identity_repo.create_identity(data)
        self.stats.identities_created += 1
        return identity

    async def _get_or_create_lci_definition(self, product_id: int, lci: int, component_name: str) -> None:
        stmt = (
            select(LCIDefinition)
            .where(LCIDefinition.product_id == product_id)
            .where(LCIDefinition.lci_index == lci)
            .limit(1)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return

        self.session.add(
            LCIDefinition(
                product_id=product_id,
                lci_index=lci,
                component_name=component_name.strip()[:100],
            )
        )
        await self.session.flush()
        self.stats.lci_definitions_created += 1

    async def _ensure_variant_and_listings(
        self,
        identity: ProductIdentity,
        base_name: str,
        rows: list[CsvRow],
        ensure_default: bool,
    ) -> None:
        if ensure_default:
            await self._get_or_create_variant(identity, None, None, base_name)

        rows_by_variant: dict[tuple[Optional[str], Optional[ConditionCode]], list[CsvRow]] = defaultdict(list)
        for row in rows:
            rows_by_variant[(row.product_color, row.product_condition)].append(row)

        for (color, condition), variant_rows in rows_by_variant.items():
            variant_name = compose_name(base_name, color, condition)
            variant = await self._get_or_create_variant(identity, color, condition, variant_name)
            for row in variant_rows:
                await self._get_or_create_listing(variant, row)

    async def _get_or_create_variant(
        self,
        identity: ProductIdentity,
        color: Optional[str],
        condition: Optional[ConditionCode],
        variant_name: str,
    ) -> ProductVariant:
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.identity_id == identity.id)
            .where(ProductVariant.color_code == color)
            .where(ProductVariant.condition_code == condition)
            .limit(1)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            if variant_name and not existing.variant_name:
                existing.variant_name = variant_name
            return existing

        variant = await self.variant_repo.create_variant(
            {
                "identity_id": identity.id,
                "color_code": color,
                "condition_code": condition,
                "variant_name": variant_name,
            },
            identity,
        )
        self.stats.variants_created += 1
        return variant

    async def _get_or_create_listing(self, variant: ProductVariant, row: CsvRow) -> None:
        platform = PLATFORM_MAP.get(row.platform)
        if platform is None:
            return

        stmt = (
            select(PlatformListing)
            .where(PlatformListing.variant_id == variant.id)
            .where(PlatformListing.platform == platform)
            .limit(1)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return

        external_ref = row.asin if platform == Platform.AMAZON and row.asin else row.sku
        self.session.add(
            PlatformListing(
                variant_id=variant.id,
                platform=platform,
                external_ref_id=external_ref,
                listed_name=row.listing_name,
            )
        )
        await self.session.flush()
        self.stats.listings_created += 1

    async def _resolve_component_identity(
        self,
        source_family: ProductFamily,
        group_name: str,
        component_name: str,
    ) -> ProductIdentity:
        component_name = component_name.strip()
        if not component_name:
            return await self._get_or_create_product_identity(source_family, group_name)

        candidates = [component_name, f"{group_name} - {component_name}".strip()]

        # 1) identity name candidates
        for name in candidates:
            identity = await self._find_identity_by_name(name)
            if identity is not None:
                return identity

        # 2) variant name candidates
        for name in candidates:
            variant = await self._find_variant_by_name(name)
            if variant is not None:
                identity = await self.session.get(ProductIdentity, variant.identity_id)
                if identity is not None:
                    return identity

        # 3) create part in source family with naming rule
        if group_name.lower() in component_name.lower():
            create_name = component_name.strip()
            component_type = component_name.strip()
        else:
            create_name = f"{group_name} - {component_name}".strip()
            component_type = component_name.strip()

        lci = await self.identity_repo.get_next_lci(source_family.product_id)
        await self._get_or_create_lci_definition(source_family.product_id, lci, component_type)

        identity = await self.identity_repo.create_identity(
            {
                "product_id": source_family.product_id,
                "type": IdentityType.P,
                "lci": lci,
                "identity_name": create_name,
            }
        )
        self.stats.identities_created += 1
        return identity

    async def _ensure_first_component_variant(
        self,
        identity: ProductIdentity,
        component_name: str,
        color: Optional[str],
        condition: Optional[ConditionCode],
    ) -> ProductVariant:
        existing = await self._find_variant_for_first_component(identity, color, condition)
        if existing is not None:
            return existing

        base = identity.identity_name or component_name
        return await self._get_or_create_variant(identity, color, condition, compose_name(base, color, condition))

    async def _find_variant_for_first_component(
        self,
        identity: ProductIdentity,
        color: Optional[str],
        condition: Optional[ConditionCode],
    ) -> Optional[ProductVariant]:
        # Primary check: exact color + condition tuple.
        exact = (
            select(ProductVariant)
            .where(ProductVariant.identity_id == identity.id)
            .where(ProductVariant.color_code == color)
            .where(ProductVariant.condition_code == condition)
            .limit(1)
        )
        found = (await self.session.execute(exact)).scalar_one_or_none()
        if found is not None:
            return found

        # Secondary check for bundle first component: SKU starts with UPIS-H-color.
        if color:
            prefix_stmt = (
                select(ProductVariant)
                .where(ProductVariant.identity_id == identity.id)
                .where(ProductVariant.full_sku.ilike(f"{identity.generated_upis_h}-{color.upper()}%"))
                .order_by(ProductVariant.id)
                .limit(1)
            )
            return (await self.session.execute(prefix_stmt)).scalar_one_or_none()

        return None

    async def _get_default_variant(self, identity_id: int) -> Optional[ProductVariant]:
        stmt = (
            select(ProductVariant)
            .where(ProductVariant.identity_id == identity_id)
            .where(ProductVariant.color_code.is_(None))
            .where(ProductVariant.condition_code.is_(None))
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _find_identity_by_name(self, name: str) -> Optional[ProductIdentity]:
        exact_stmt = (
            select(ProductIdentity)
            .where(func.lower(ProductIdentity.identity_name) == name.lower())
            .limit(1)
        )
        exact = (await self.session.execute(exact_stmt)).scalar_one_or_none()
        if exact is not None:
            return exact

        # Normalized fallback for spacing/case inconsistencies from CSV sources.
        like_stmt = (
            select(ProductIdentity)
            .where(ProductIdentity.identity_name.is_not(None))
            .where(ProductIdentity.identity_name.ilike(f"%{name}%"))
            .limit(200)
        )
        candidates = (await self.session.execute(like_stmt)).scalars().all()
        target = normalize_name(name)
        for candidate in candidates:
            if candidate.identity_name and normalize_name(candidate.identity_name) == target:
                return candidate
        return None

    async def _find_variant_by_name(self, name: str) -> Optional[ProductVariant]:
        exact_stmt = (
            select(ProductVariant)
            .where(func.lower(ProductVariant.variant_name) == name.lower())
            .limit(1)
        )
        exact = (await self.session.execute(exact_stmt)).scalar_one_or_none()
        if exact is not None:
            return exact

        like_stmt = (
            select(ProductVariant)
            .where(ProductVariant.variant_name.is_not(None))
            .where(ProductVariant.variant_name.ilike(f"%{name}%"))
            .limit(200)
        )
        candidates = (await self.session.execute(like_stmt)).scalars().all()
        target = normalize_name(name)
        for candidate in candidates:
            if candidate.variant_name and normalize_name(candidate.variant_name) == target:
                return candidate
        return None

    def _build_bundle_name(self, components: list[str]) -> str:
        if not components:
            return "Bundle"
        if len(components) == 1:
            return components[0].strip()
        return f"{components[0].strip()} with {', '.join(c.strip() for c in components[1:])}"

    async def _get_or_create_bundle_family(self, bundle_name: str) -> ProductFamily:
        existing_stmt = (
            select(ProductFamily)
            .where(ProductFamily.base_name == bundle_name)
            .limit(1)
        )
        existing = (await self.session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        family = await self._create_family_auto(bundle_name)
        self.stats.bundle_families_created += 1
        return family

    async def _create_bundle_identity(self, family: ProductFamily, bundle_name: str) -> ProductIdentity:
        identity = await self.identity_repo.create_identity(
            {
                "product_id": family.product_id,
                "type": IdentityType.B,
                "identity_name": bundle_name,
            }
        )
        self.stats.identities_created += 1
        return identity

    async def _get_or_create_bundle_identity(self, family: ProductFamily, bundle_name: str) -> ProductIdentity:
        stmt = (
            select(ProductIdentity)
            .where(ProductIdentity.product_id == family.product_id)
            .where(ProductIdentity.type == IdentityType.B)
            .limit(1)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            if not existing.identity_name:
                existing.identity_name = bundle_name
            return existing
        return await self._create_bundle_identity(family, bundle_name)

    async def _create_bundle_components(
        self,
        bundle_identity: ProductIdentity,
        component_identities: list[ProductIdentity],
    ) -> None:
        if not component_identities:
            return

        counts = Counter(identity.id for identity in component_identities)
        first_component_id = component_identities[0].id

        for child_identity_id, qty in counts.items():
            stmt = (
                select(BundleComponent)
                .where(BundleComponent.parent_identity_id == bundle_identity.id)
                .where(BundleComponent.child_identity_id == child_identity_id)
                .limit(1)
            )
            existing = (await self.session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                continue

            role = BundleRole.PRIMARY if child_identity_id == first_component_id else BundleRole.ACCESSORY
            self.session.add(
                BundleComponent(
                    parent_identity_id=bundle_identity.id,
                    child_identity_id=child_identity_id,
                    quantity_required=qty,
                    role=role,
                )
            )
            await self.session.flush()
            self.stats.bundle_components_created += 1

    async def verify_import(self) -> VerificationReport:
        report = VerificationReport()

        duplicate_sku_stmt = (
            select(ProductVariant.full_sku, func.count(ProductVariant.id))
            .group_by(ProductVariant.full_sku)
            .having(func.count(ProductVariant.id) > 1)
            .order_by(ProductVariant.full_sku)
        )
        report.duplicate_skus = [(sku, int(count)) for sku, count in (await self.session.execute(duplicate_sku_stmt)).all()]

        default_target_types = [IdentityType.PRODUCT, IdentityType.B, IdentityType.K]
        missing_default_stmt = (
            select(ProductIdentity.generated_upis_h)
            .where(ProductIdentity.type.in_(default_target_types))
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
            .order_by(ProductIdentity.generated_upis_h)
        )
        report.missing_default_variants = list((await self.session.execute(missing_default_stmt)).scalars().all())

        duplicate_lci_stmt = (
            select(ProductIdentity.product_id, ProductIdentity.lci, func.count(ProductIdentity.id))
            .where(ProductIdentity.type == IdentityType.P)
            .where(ProductIdentity.lci.is_not(None))
            .group_by(ProductIdentity.product_id, ProductIdentity.lci)
            .having(func.count(ProductIdentity.id) > 1)
            .order_by(ProductIdentity.product_id, ProductIdentity.lci)
        )
        report.duplicate_lci_rows = [
            (int(product_id), int(lci), int(count))
            for product_id, lci, count in (await self.session.execute(duplicate_lci_stmt)).all()
        ]

        orphan_bundle_stmt = (
            select(ProductIdentity.generated_upis_h)
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
            .order_by(ProductIdentity.generated_upis_h)
        )
        report.orphan_bundle_upis_h = list((await self.session.execute(orphan_bundle_stmt)).scalars().all())

        inactive_bundle_stmt = (
            select(ProductIdentity.generated_upis_h)
            .join(ProductVariant, ProductVariant.identity_id == ProductIdentity.id)
            .where(ProductIdentity.type == IdentityType.B)
            .where(ProductVariant.color_code.is_(None))
            .where(ProductVariant.condition_code.is_(None))
            .where(ProductVariant.is_active.is_(False))
            .order_by(ProductIdentity.generated_upis_h)
        )
        report.inactive_bundle_default_upis_h = list((await self.session.execute(inactive_bundle_stmt)).scalars().all())

        return report


def load_groups(csv_path: Path, group_limit: Optional[int]) -> list[GroupBucket]:
    groups: dict[int, GroupBucket] = {}

    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row = CsvRow.from_dict(raw)
            if row.group_id not in groups:
                groups[row.group_id] = GroupBucket(group_id=row.group_id, group_name=row.group_name)
            groups[row.group_id].rows.append(row)

    ordered = [groups[key] for key in sorted(groups)]
    if group_limit is not None:
        ordered = ordered[:group_limit]
    return ordered


def print_stats(stats: Stats) -> None:
    print("\nImport Summary")
    print("-" * 60)
    print(f"Families created:          {stats.families_created}")
    print(f"Bundle families created:   {stats.bundle_families_created}")
    print(f"Identities created:        {stats.identities_created}")
    print(f"Variants created:          {stats.variants_created}")
    print(f"Bundle identities seen:    {stats.bundle_identities_seen}")
    print(f"Bundle defaults repaired:  {stats.bundle_default_variants_repaired}")
    print(f"Bundle defaults inactive:  {stats.bundle_default_variants_inactive}")
    print(f"Listings created:          {stats.listings_created}")
    print(f"LCI definitions created:   {stats.lci_definitions_created}")
    print(f"Bundle components created: {stats.bundle_components_created}")


def print_verification(report: VerificationReport) -> None:
    print("\nVerification")
    print("-" * 60)

    print(f"Duplicate full SKUs:        {len(report.duplicate_skus)}")
    for sku, count in report.duplicate_skus[:20]:
        print(f"  - {sku}: {count}")
    if len(report.duplicate_skus) > 20:
        print(f"  ... {len(report.duplicate_skus) - 20} more")

    print(f"Missing default variants:   {len(report.missing_default_variants)}")
    for upis_h in report.missing_default_variants[:20]:
        print(f"  - {upis_h}")
    if len(report.missing_default_variants) > 20:
        print(f"  ... {len(report.missing_default_variants) - 20} more")

    print(f"Duplicate part LCI rows:    {len(report.duplicate_lci_rows)}")
    for product_id, lci, count in report.duplicate_lci_rows[:20]:
        print(f"  - product_id={product_id} lci={lci} count={count}")
    if len(report.duplicate_lci_rows) > 20:
        print(f"  ... {len(report.duplicate_lci_rows) - 20} more")

    print(f"Orphan bundle identities:   {len(report.orphan_bundle_upis_h)}")
    for upis_h in report.orphan_bundle_upis_h[:20]:
        print(f"  - {upis_h}")
    if len(report.orphan_bundle_upis_h) > 20:
        print(f"  ... {len(report.orphan_bundle_upis_h) - 20} more")

    print(f"Inactive bundle defaults:   {len(report.inactive_bundle_default_upis_h)}")
    for upis_h in report.inactive_bundle_default_upis_h[:20]:
        print(f"  - {upis_h}")
    if len(report.inactive_bundle_default_upis_h) > 20:
        print(f"  ... {len(report.inactive_bundle_default_upis_h) - 20} more")


async def run_import(csv_path: Path, dry_run: bool, group_limit: Optional[int]) -> None:
    groups = load_groups(csv_path, group_limit)
    print(f"Loaded {sum(len(g.rows) for g in groups)} rows across {len(groups)} groups")

    async with async_session_factory() as session:
        importer = RestartImporter(session, dry_run=dry_run)
        await importer.run(groups)
        verification = await importer.verify_import()
        print_verification(verification)

        if dry_run:
            await session.rollback()
            print("Dry run complete. Changes were rolled back.")
        else:
            await session.commit()
            print("Import committed.")

        print_stats(importer.stats)


async def reset_product_family_sequence(session: AsyncSession) -> None:
    """Align product_family sequence to max(product_id)+1."""
    seq_name = (
        await session.execute(
            select(func.pg_get_serial_sequence("product_family", "product_id"))
        )
    ).scalar_one_or_none()

    if not seq_name:
        print("No serial sequence found for product_family.product_id; skipping sequence reset.")
        return

    max_id = (
        await session.execute(select(func.coalesce(func.max(ProductFamily.product_id), 0)))
    ).scalar_one()
    next_value = int(max_id) + 1

    await session.execute(
        text(f"SELECT setval('{seq_name}', :next_value, false)"),
        {"next_value": next_value},
    )
    print(f"Reset sequence {seq_name} -> next value {next_value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restart import DatabaseWork CSV directly into DB")
    parser.add_argument("--csv-path", default=str(DEFAULT_CSV_PATH), help="Path to DatabaseWork CSV")
    parser.add_argument("--dry-run", action="store_true", help="Run without persisting DB changes")
    parser.add_argument("--limit-groups", type=int, default=None, help="Process only first N groups")
    parser.add_argument(
        "--reset-family-sequence",
        action="store_true",
        help="Reset product_family auto-increment sequence before import",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        raise SystemExit(f"CSV path not found: {csv_path}")

    async def _runner() -> None:
        if args.reset_family_sequence:
            async with async_session_factory() as session:
                await reset_product_family_sequence(session)
                if args.dry_run:
                    await session.rollback()
                else:
                    await session.commit()

        await run_import(csv_path, args.dry_run, args.limit_groups)

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
