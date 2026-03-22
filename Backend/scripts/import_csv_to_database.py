#!/usr/bin/env python
"""
CSV Import Script for USAV Inventory Database

This script parses product_attributes_extracted_merged.csv and populates the database
using the backend API endpoints.

Features:
---------
- Creates Product Families for each unique group in the CSV
- Creates Product Identities (base products, parts, bundles)
- Creates Product Variants for each unique (color, condition) combination
- Creates Platform Listings for each SKU entry (Amazon, eBay, Ecwid)
- Creates LCI Definitions for parts with component names
- Creates Bundle Components linking bundles to their parts

Data Processing Rules:
----------------------
1. Products (Product Type = "Product"):
   - Create a base identity for the group
   - Create variants for each (color, condition) combination
   - Add listings for each SKU

2. Parts (Product Type = "Parts"):
   - Create LCI definition with the component type as name
   - Create a Part identity (type="P") 
   - Create variants and listings for each part

3. Bundles (Product Type = "Bundle"):
   - Parse "Included Products" to identify components
   - Create a Bundle identity (type="B")
   - Create Part identities for additional components (with LCI definitions)
   - Link parts to bundle via Bundle Components
   - Create variants and listings for the bundle

Usage:
    python import_csv_to_database.py [--csv-path PATH] [--api-url URL] [--username USER] [--password PASS]
    
Examples:
    # Full import
    python import_csv_to_database.py --csv-path ../misc/product_attributes_extracted_merged.csv
    
    # Dry run (no API calls)
    python import_csv_to_database.py --dry-run --csv-path ../misc/product_attributes_extracted_merged.csv
    
    # Test with limited groups
    python import_csv_to_database.py --dry-run --limit 10 --csv-path ../misc/product_attributes_extracted_merged.csv

Prerequisites:
    - Backend API must be running (default: http://localhost:8000)
    - Admin user credentials (default: admin/admin123)
    - httpx package: pip install httpx
"""

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx

# Default configuration
DEFAULT_API_URL = "http://localhost:8080/api/v1"
DEFAULT_CSV_PATH = "/app/product_attributes_extracted_merged.csv"
DEFAULT_USERNAME = "sysad"
DEFAULT_PASSWORD = "bach9999"

# Platform mapping from CSV to API enum values
PLATFORM_MAP = {
    "Amazon": "AMAZON",
    "MEKONG_eBay": "EBAY_MEKONG",
    "USAV_eBay": "EBAY_USAV",
    "DRAGON_eBay": "EBAY_DRAGON",
    "Ecwid": "ECWID",
}

# Condition code mapping - API now supports explicit U (Used)
CONDITION_MAP = {
    "U": "U",  # Used
    "N": "N",   # New
    "R": "R",   # Refurbished
}


@dataclass
class CSVRow:
    """Parsed CSV row data."""
    group_id: int
    group_name: str
    product_type: str  # Product, Parts, Bundle
    color_code: str | None
    condition_code: str | None  # N, R, U, or None
    component_type: str | None
    included_products: str | None
    group_size: int
    id_in_group: int
    stripped_name: str
    name: str
    sku: str
    platform: str
    asin: str | None
    
    @classmethod
    def from_dict(cls, row: dict[str, str]) -> "CSVRow":
        """Create CSVRow from CSV dict row."""
        # Map condition code to API enum value when present.
        raw_condition = row["Product Condition"].strip() if row["Product Condition"].strip() else None
        condition_code = CONDITION_MAP.get(raw_condition, raw_condition) if raw_condition else None
        
        return cls(
            group_id=int(row["groupid"]),
            group_name=row["Group Name"].strip(),
            product_type=row["Product Type"].strip(),
            color_code=row["Product Color"].strip() if row["Product Color"].strip() else None,
            condition_code=condition_code,
            component_type=row["Component Type"].strip() if row["Component Type"].strip() else None,
            included_products=row["Included Products"].strip() if row["Included Products"].strip() else None,
            group_size=int(row["groupsize"]) if row["groupsize"] else 1,
            id_in_group=int(row["idingroup"]) if row["idingroup"] else 0,
            stripped_name=row["strippedname"].strip(),
            name=row["name"].strip(),
            sku=row["sku"].strip(),
            platform=row["platform"].strip(),
            asin=row["ASIN"].strip() if row["ASIN"].strip() else None,
        )


@dataclass
class ProductGroup:
    """Represents a product group from the CSV."""
    group_id: int
    group_name: str
    rows: list[CSVRow] = field(default_factory=list)
    
    # Processed data
    family_product_id: int | None = None
    base_identity_id: int | None = None
    variants: dict[tuple[str | None, str | None], int] = field(default_factory=dict)  # (color, condition) -> variant_id
    parts: dict[str, int] = field(default_factory=dict)  # component_type -> identity_id
    bundles: dict[str, int] = field(default_factory=dict)  # bundle_key -> identity_id


class APIClient:
    """HTTP client for interacting with the USAV Inventory API."""
    
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None
        self.client = httpx.Client(timeout=30.0)
        
    def authenticate(self) -> bool:
        """Authenticate and get access token."""
        try:
            response = self.client.post(
                f"{self.base_url}/auth/token",
                data={"username": self.username, "password": self.password},
            )
            if response.status_code == 200:
                data = response.json()
                self.token = data["access_token"]
                print(f"✓ Authenticated as {self.username}")
                return True
            else:
                print(f"✗ Authentication failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"✗ Authentication error: {e}")
            return False
    
    def _headers(self) -> dict[str, str]:
        """Get request headers with auth token."""
        return {"Authorization": f"Bearer {self.token}"}
    
    def _request(
        self,
        method: str,
        endpoint: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> tuple[int, dict | None]:
        """Make an API request."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.client.request(
                method,
                url,
                json=json,
                params=params,
                headers=self._headers(),
            )
            if response.status_code in (200, 201):
                return response.status_code, response.json()
            elif response.status_code == 204:
                return response.status_code, None
            elif response.status_code == 409:
                # Conflict - item already exists
                return response.status_code, {"detail": response.json().get("detail", "Conflict")}
            else:
                return response.status_code, {"detail": response.text}
        except Exception as e:
            return 500, {"detail": str(e)}
    
    # -------------------------------------------------------------------------
    # Product Families
    # -------------------------------------------------------------------------
    
    def create_family(self, base_name: str, product_id: int | None = None) -> tuple[int, dict | None]:
        """Create a product family."""
        payload = {"base_name": base_name}
        if product_id is not None:
            payload["product_id"] = product_id
        return self._request("POST", "/families", json=payload)
    
    def get_family(self, product_id: int) -> tuple[int, dict | None]:
        """Get a product family by ID."""
        return self._request("GET", f"/families/{product_id}")
    
    def search_families(self, search: str) -> tuple[int, dict | None]:
        """Search for product families."""
        return self._request("GET", "/families", params={"search": search, "limit": 100})
    
    # -------------------------------------------------------------------------
    # Product Identities
    # -------------------------------------------------------------------------
    
    def create_identity(
        self,
        product_id: int,
        identity_type: str,  # "Product", "B", "P", "K"
        lci: int | None = None,
        physical_class: str | None = None,
    ) -> tuple[int, dict | None]:
        """Create a product identity."""
        payload: dict[str, Any] = {
            "product_id": product_id,
            "type": identity_type,
        }
        if lci is not None:
            payload["lci"] = lci
        if physical_class is not None:
            payload["physical_class"] = physical_class
        return self._request("POST", "/identities", json=payload)
    
    def get_identity(self, identity_id: int) -> tuple[int, dict | None]:
        """Get a product identity by ID."""
        return self._request("GET", f"/identities/{identity_id}")
    
    def get_identity_by_upis(self, upis_h: str) -> tuple[int, dict | None]:
        """Get a product identity by UPIS-H string."""
        return self._request("GET", f"/identities/upis/{upis_h}")
    
    def list_identities(self, product_id: int) -> tuple[int, dict | None]:
        """List identities for a product family."""
        return self._request("GET", "/identities", params={"product_id": product_id, "limit": 1000})
    
    # -------------------------------------------------------------------------
    # Product Variants
    # -------------------------------------------------------------------------
    
    def create_variant(
        self,
        identity_id: int,
        color_code: str | None = None,
        condition_code: str | None = None,
    ) -> tuple[int, dict | None]:
        """Create a product variant."""
        payload: dict[str, Any] = {"identity_id": identity_id}
        if color_code:
            payload["color_code"] = color_code
        if condition_code:
            payload["condition_code"] = condition_code
        return self._request("POST", "/variants", json=payload)
    
    def get_variant(self, variant_id: int) -> tuple[int, dict | None]:
        """Get a product variant by ID."""
        return self._request("GET", f"/variants/{variant_id}")
    
    def get_variant_by_sku(self, full_sku: str) -> tuple[int, dict | None]:
        """Get a product variant by full SKU."""
        return self._request("GET", f"/variants/sku/{full_sku}")
    
    def list_variants(self, identity_id: int) -> tuple[int, dict | None]:
        """List variants for an identity."""
        return self._request("GET", "/variants", params={"identity_id": identity_id, "limit": 1000})
    
    # -------------------------------------------------------------------------
    # Platform Listings
    # -------------------------------------------------------------------------
    
    def create_listing(
        self,
        variant_id: int,
        platform: str,
        external_ref_id: str | None = None,
        listed_name: str | None = None,
    ) -> tuple[int, dict | None]:
        """Create a platform listing."""
        payload: dict[str, Any] = {
            "variant_id": variant_id,
            "platform": platform,
        }
        if external_ref_id:
            payload["external_ref_id"] = external_ref_id
        if listed_name:
            payload["listed_name"] = listed_name
        return self._request("POST", "/listings", json=payload)
    
    def get_listing_by_external_ref(self, platform: str, external_ref_id: str) -> tuple[int, dict | None]:
        """Get a listing by platform and external reference ID."""
        return self._request("GET", f"/listings/platform/{platform}/ref/{external_ref_id}")
    
    # -------------------------------------------------------------------------
    # Bundle Components
    # -------------------------------------------------------------------------
    
    def create_bundle_component(
        self,
        parent_identity_id: int,
        child_identity_id: int,
        quantity_required: int = 1,
        role: str = "Primary",
    ) -> tuple[int, dict | None]:
        """Add a component to a bundle."""
        payload = {
            "parent_identity_id": parent_identity_id,
            "child_identity_id": child_identity_id,
            "quantity_required": quantity_required,
            "role": role,
        }
        status, data = self._request("POST", "/bundles", json=payload)
        if status == 500:
            print(f"        DEBUG: Bundle component error: parent={parent_identity_id}, child={child_identity_id}, response={data}")
        return status, data
    
    def get_bundle_components(self, parent_identity_id: int) -> tuple[int, dict | None]:
        """Get all components of a bundle."""
        return self._request("GET", f"/bundles/parent/{parent_identity_id}/components")
    
    # -------------------------------------------------------------------------
    # LCI Definitions
    # -------------------------------------------------------------------------
    
    def create_lci_definition(
        self,
        product_id: int,
        component_name: str,
        lci_index: int | None = None,
    ) -> tuple[int, dict | None]:
        """Create an LCI definition for a component type."""
        payload: dict[str, Any] = {
            "product_id": product_id,
            "component_name": component_name,
        }
        if lci_index is not None:
            payload["lci_index"] = lci_index
        return self._request("POST", "/lci-definitions", json=payload)
    
    def list_lci_definitions(self, product_id: int) -> tuple[int, dict | None]:
        """List LCI definitions for a product family."""
        return self._request("GET", "/lci-definitions", params={"product_id": product_id, "limit": 100})


def parse_included_products(included_str: str, group_name: str) -> list[str]:
    """
    Parse the 'Included Products' column to extract individual product names.
    Returns a list of product names, removing duplicates while preserving order.
    """
    if not included_str:
        return []
    
    # Split by comma and clean up
    products = [p.strip() for p in included_str.split(",") if p.strip()]
    
    # Remove duplicates while preserving order
    seen = set()
    unique_products = []
    for p in products:
        if p not in seen:
            seen.add(p)
            unique_products.append(p)
    
    return unique_products


def extract_bundle_components(included_products: list[str], group_name: str) -> tuple[bool, list[str]]:
    """
    Analyze bundle components to determine if it includes the base product
    and what additional parts/accessories are included.
    
    Returns:
        (has_base_product, additional_parts)
    """
    if not included_products:
        return True, []
    
    additional_parts = []
    has_base_product = False
    
    for product in included_products:
        # Check if this is the base product (matches group name or is very similar)
        if product.lower() == group_name.lower() or group_name.lower() in product.lower():
            has_base_product = True
        else:
            additional_parts.append(product)
    
    return has_base_product, additional_parts


def normalize_part_name(part_name: str) -> str:
    """Normalize a part name for consistent naming."""
    # Remove common prefixes/suffixes
    normalized = part_name.strip()
    # Title case but preserve common abbreviations
    words = normalized.split()
    result = []
    for word in words:
        if word.upper() in ("HDMI", "USB", "OEM", "PCB", "CD", "DVD", "AM", "FM", "AC", "DC"):
            result.append(word.upper())
        else:
            result.append(word.title())
    return " ".join(result)


def create_part_lci_name(component_type: str) -> str:
    """Create an LCI name from component type."""
    return normalize_part_name(component_type)


def create_bundle_part_name(group_name: str, part_name: str) -> str:
    """Create a full part name for a bundle component: {group_name} {part_name}."""
    return f"{group_name} {normalize_part_name(part_name)}"


class CSVImporter:
    """Main importer class for processing CSV and populating the database."""
    
    def __init__(self, api_client: APIClient, dry_run: bool = False):
        self.api = api_client
        self.dry_run = dry_run
        self.groups: dict[int, ProductGroup] = {}
        self.stats = {
            "families_created": 0,
            "identities_created": 0,
            "variants_created": 0,
            "listings_created": 0,
            "bundle_components_created": 0,
            "lci_definitions_created": 0,
            "errors": [],
        }
    
    def load_csv(self, csv_path: str) -> None:
        """Load and parse the CSV file."""
        print(f"\n📂 Loading CSV from: {csv_path}")
        
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row_count = 0
            
            for row in reader:
                try:
                    csv_row = CSVRow.from_dict(row)
                    
                    # Get or create group
                    if csv_row.group_id not in self.groups:
                        self.groups[csv_row.group_id] = ProductGroup(
                            group_id=csv_row.group_id,
                            group_name=csv_row.group_name,
                        )
                    
                    self.groups[csv_row.group_id].rows.append(csv_row)
                    row_count += 1
                    
                except Exception as e:
                    print(f"  ⚠ Error parsing row: {e}")
                    self.stats["errors"].append(f"Parse error: {e}")
        
        print(f"  ✓ Loaded {row_count} rows in {len(self.groups)} groups")
    
    def process_groups(self) -> None:
        """Process all product groups."""
        print(f"\n🔄 Processing {len(self.groups)} product groups...")
        
        for group_id, group in sorted(self.groups.items()):
            self._process_group(group)
    
    def _process_group(self, group: ProductGroup) -> None:
        """Process a single product group."""
        print(f"\n{'='*60}")
        print(f"📦 Group {group.group_id}: {group.group_name}")
        print(f"   Rows: {len(group.rows)}")
        
        # Step 1: Create Product Family
        self._create_family(group)
        if group.family_product_id is None:
            print(f"  ✗ Failed to create/get family, skipping group")
            return
        
        # Step 2: Analyze and categorize rows
        product_rows = []
        parts_rows = []
        bundle_rows = []
        
        for row in group.rows:
            if row.product_type == "Product":
                product_rows.append(row)
            elif row.product_type == "Parts":
                parts_rows.append(row)
            elif row.product_type == "Bundle":
                bundle_rows.append(row)
        
        print(f"   Products: {len(product_rows)}, Parts: {len(parts_rows)}, Bundles: {len(bundle_rows)}")
        
        # Step 3: Create base identity for Products (if any product rows exist)
        if product_rows or bundle_rows:
            self._create_base_identity(group)
        
        # Step 4: Process Parts - Create Part identities
        self._process_parts(group, parts_rows)
        
        # Step 5: Process Products - Create variants and listings
        self._process_products(group, product_rows)
        
        # Step 6: Process Bundles - Create bundle identities and components
        self._process_bundles(group, bundle_rows)
    
    def _create_family(self, group: ProductGroup) -> None:
        """Create or get existing product family."""
        if self.dry_run:
            print(f"  [DRY RUN] Would create family: {group.group_name}")
            group.family_product_id = group.group_id
            return
        
        # First, try to search for existing family
        status, data = self.api.search_families(group.group_name)
        if status == 200 and data and data.get("items"):
            for item in data["items"]:
                if item["base_name"].lower() == group.group_name.lower():
                    group.family_product_id = item["product_id"]
                    print(f"  ✓ Found existing family: product_id={group.family_product_id}")
                    return
        
        # Create new family
        status, data = self.api.create_family(group.group_name)
        if status == 201 and data:
            group.family_product_id = data["product_id"]
            self.stats["families_created"] += 1
            print(f"  ✓ Created family: product_id={group.family_product_id}")
        elif status == 409:
            # Already exists - search again
            status, data = self.api.search_families(group.group_name)
            if status == 200 and data and data.get("items"):
                for item in data["items"]:
                    if item["base_name"].lower() == group.group_name.lower():
                        group.family_product_id = item["product_id"]
                        print(f"  ✓ Found existing family (409): product_id={group.family_product_id}")
                        return
            print(f"  ✗ Family conflict but not found: {data}")
            self.stats["errors"].append(f"Family conflict for {group.group_name}")
        else:
            print(f"  ✗ Failed to create family: {status} - {data}")
            self.stats["errors"].append(f"Failed to create family {group.group_name}: {data}")
    
    def _create_base_identity(self, group: ProductGroup) -> None:
        """Create or get the base product identity for the group."""
        if group.family_product_id is None:
            return
        
        if self.dry_run:
            print(f"  [DRY RUN] Would create base identity for family {group.family_product_id}")
            group.base_identity_id = 1  # Placeholder
            return
        
        # Check for existing identity
        status, data = self.api.list_identities(group.family_product_id)
        if status == 200 and data and data.get("items"):
            for item in data["items"]:
                if item["type"] == "Product":
                    group.base_identity_id = item["id"]
                    print(f"  ✓ Found existing base identity: id={group.base_identity_id}")
                    return
        
        # Create base identity (type="Product" for main product)
        status, data = self.api.create_identity(
            product_id=group.family_product_id,
            identity_type="Product",
        )
        if status == 201 and data:
            group.base_identity_id = data["id"]
            self.stats["identities_created"] += 1
            print(f"  ✓ Created base identity: id={group.base_identity_id}, upis={data.get('generated_upis_h')}")
        elif status == 409:
            # Check for existing
            status, data = self.api.list_identities(group.family_product_id)
            if status == 200 and data and data.get("items"):
                for item in data["items"]:
                    if item["type"] == "Product":
                        group.base_identity_id = item["id"]
                        print(f"  ✓ Found existing base identity (409): id={group.base_identity_id}")
                        return
        else:
            print(f"  ✗ Failed to create base identity: {status} - {data}")
            self.stats["errors"].append(f"Failed to create base identity for group {group.group_id}")
    
    def _process_parts(self, group: ProductGroup, parts_rows: list[CSVRow]) -> None:
        """Process Parts rows - create part identities."""
        if not parts_rows or group.family_product_id is None:
            return
        
        # Group by component type
        component_types: dict[str, list[CSVRow]] = defaultdict(list)
        for row in parts_rows:
            if row.component_type:
                component_types[row.component_type].append(row)
        
        print(f"  📎 Parts: {len(component_types)} component types")
        
        for component_type, rows in component_types.items():
            self._create_part_identity(group, component_type, rows)
    
    def _create_part_identity(
        self,
        group: ProductGroup,
        component_type: str,
        rows: list[CSVRow],
    ) -> None:
        """Create a part identity and its variants/listings."""
        if self.dry_run:
            print(f"    [DRY RUN] Would create part: {group.group_name} - {component_type}")
            return
        
        # First, create LCI definition for this component type
        lci_name = create_part_lci_name(component_type)
        lci_status, lci_data = self.api.create_lci_definition(
            product_id=group.family_product_id,
            component_name=lci_name,
        )
        
        if lci_status == 201 and lci_data:
            self.stats["lci_definitions_created"] += 1
            print(f"    ✓ Created LCI definition: {lci_name} -> lci_index={lci_data.get('lci_index')}")
        elif lci_status != 409:
            print(f"    ⚠ Failed to create LCI definition: {lci_status}")
        
        # Create Part identity (type="P")
        status, data = self.api.create_identity(
            product_id=group.family_product_id,
            identity_type="P",
            # LCI is auto-assigned by the API
        )
        
        if status == 201 and data:
            part_id = data["id"]
            group.parts[component_type] = part_id
            self.stats["identities_created"] += 1
            print(f"    ✓ Created part identity: {component_type} -> id={part_id}")
            
            # Create variants and listings for this part
            self._create_variants_and_listings(group, part_id, rows)
        elif status == 409:
            print(f"    ⚠ Part identity already exists for {component_type}")
            # Try to find existing
            status, data = self.api.list_identities(group.family_product_id)
            if status == 200 and data:
                for item in data.get("items", []):
                    if item["type"] == "P":
                        # Could match by LCI or other means
                        group.parts[component_type] = item["id"]
                        break
        else:
            print(f"    ✗ Failed to create part identity: {status} - {data}")
            self.stats["errors"].append(f"Failed to create part {component_type}")
    
    def _process_products(self, group: ProductGroup, product_rows: list[CSVRow]) -> None:
        """Process Product rows - create variants and listings."""
        if not product_rows or group.base_identity_id is None:
            return
        
        print(f"  📦 Processing {len(product_rows)} product listings")
        self._create_variants_and_listings(group, group.base_identity_id, product_rows)
    
    def _create_variants_and_listings(
        self,
        group: ProductGroup,
        identity_id: int,
        rows: list[CSVRow],
    ) -> None:
        """Create variants and platform listings for a set of rows."""
        # Group rows by (color, condition) to identify unique variants
        variant_rows: dict[tuple[str | None, str | None], list[CSVRow]] = defaultdict(list)
        for row in rows:
            variant_key = (row.color_code, row.condition_code)
            variant_rows[variant_key].append(row)
        
        for variant_key, vrows in variant_rows.items():
            color_code, condition_code = variant_key
            variant_id = self._get_or_create_variant(identity_id, color_code, condition_code)
            
            if variant_id:
                # Track variant
                if identity_id == group.base_identity_id:
                    group.variants[variant_key] = variant_id
                
                # Create listings for each row
                for row in vrows:
                    self._create_listing(variant_id, row)
    
    def _get_or_create_variant(
        self,
        identity_id: int,
        color_code: str | None,
        condition_code: str | None,
    ) -> int | None:
        """Get or create a variant for the given identity."""
        if self.dry_run:
            return 1  # Placeholder
        
        # Check for existing variants
        status, data = self.api.list_variants(identity_id)
        if status == 200 and data:
            for item in data.get("items", []):
                if item["color_code"] == color_code and item["condition_code"] == condition_code:
                    return item["id"]
        
        # Create new variant
        status, data = self.api.create_variant(
            identity_id=identity_id,
            color_code=color_code,
            condition_code=condition_code,
        )
        
        if status == 201 and data:
            self.stats["variants_created"] += 1
            print(f"      ✓ Created variant: color={color_code}, condition={condition_code}")
            return data["id"]
        elif status == 409:
            # Already exists - fetch it
            status, data = self.api.list_variants(identity_id)
            if status == 200 and data:
                for item in data.get("items", []):
                    if item["color_code"] == color_code and item["condition_code"] == condition_code:
                        return item["id"]
        else:
            print(f"      ✗ Failed to create variant: {status} - {data}")
            self.stats["errors"].append(f"Failed to create variant for identity {identity_id}")
        
        return None
    
    def _create_listing(self, variant_id: int, row: CSVRow) -> None:
        """Create a platform listing for a variant."""
        platform = PLATFORM_MAP.get(row.platform)
        if not platform:
            print(f"      ⚠ Unknown platform: {row.platform}")
            return
        
        if self.dry_run:
            print(f"      [DRY RUN] Would create listing: {platform} - {row.sku}")
            return
        
        # Determine external_ref_id (ASIN for Amazon, SKU for others)
        external_ref_id = row.asin if platform == "AMAZON" and row.asin else row.sku
        
        status, data = self.api.create_listing(
            variant_id=variant_id,
            platform=platform,
            external_ref_id=external_ref_id,
            listed_name=row.name,
        )
        
        if status == 201:
            self.stats["listings_created"] += 1
            # Don't spam the console for every listing
        elif status == 409:
            # Already exists - that's fine
            pass
        else:
            print(f"      ✗ Failed to create listing: {status} - {data}")
            self.stats["errors"].append(f"Failed to create listing {row.sku}")
    
    def _process_bundles(self, group: ProductGroup, bundle_rows: list[CSVRow]) -> None:
        """Process Bundle rows - create bundle identities and components."""
        if not bundle_rows or group.family_product_id is None:
            return
        
        print(f"  📦 Processing {len(bundle_rows)} bundle listings")
        
        # Group bundles by their included products (to identify unique bundle configurations)
        bundle_configs: dict[str, list[CSVRow]] = defaultdict(list)
        for row in bundle_rows:
            bundle_key = row.included_products or ""
            bundle_configs[bundle_key].append(row)
        
        for bundle_key, brows in bundle_configs.items():
            if not bundle_key:
                # Bundle without included products - treat as product variant
                if group.base_identity_id:
                    self._create_variants_and_listings(group, group.base_identity_id, brows)
                continue
            
            # Parse included products
            included_products = parse_included_products(bundle_key, group.group_name)
            has_base, additional_parts = extract_bundle_components(included_products, group.group_name)
            
            if not additional_parts:
                # Just the base product - treat as regular variant
                if group.base_identity_id:
                    self._create_variants_and_listings(group, group.base_identity_id, brows)
                continue
            
            # Create bundle identity
            bundle_identity_id = self._create_bundle_identity(group, additional_parts)
            
            if bundle_identity_id:
                # Add components to the bundle
                self._add_bundle_components(group, bundle_identity_id, has_base, additional_parts)
                
                # Create variants and listings for the bundle
                self._create_variants_and_listings(group, bundle_identity_id, brows)
                
                # Store bundle
                group.bundles[bundle_key] = bundle_identity_id
    
    def _create_bundle_identity(self, group: ProductGroup, additional_parts: list[str]) -> int | None:
        """Create a bundle identity."""
        if self.dry_run:
            print(f"    [DRY RUN] Would create bundle with parts: {additional_parts}")
            return 1  # Placeholder
        
        # Create Bundle identity (type="B")
        status, data = self.api.create_identity(
            product_id=group.family_product_id,
            identity_type="B",
        )
        
        if status == 201 and data:
            self.stats["identities_created"] += 1
            print(f"    ✓ Created bundle identity: id={data['id']}")
            return data["id"]
        elif status == 409:
            # Bundle exists - try to find it
            status, data = self.api.list_identities(group.family_product_id)
            if status == 200 and data:
                for item in data.get("items", []):
                    if item["type"] == "B":
                        return item["id"]
        else:
            print(f"    ✗ Failed to create bundle identity: {status} - {data}")
            self.stats["errors"].append(f"Failed to create bundle for group {group.group_id}")
        
        return None
    
    def _add_bundle_components(
        self,
        group: ProductGroup,
        bundle_identity_id: int,
        has_base: bool,
        additional_parts: list[str],
    ) -> None:
        """Add components to a bundle."""
        if self.dry_run:
            return
        
        # Add base product if included
        if has_base and group.base_identity_id:
            status, data = self.api.create_bundle_component(
                parent_identity_id=bundle_identity_id,
                child_identity_id=group.base_identity_id,
                quantity_required=1,
                role="Primary",
            )
            if status == 201:
                self.stats["bundle_components_created"] += 1
                print(f"      ✓ Added base product to bundle")
            elif status != 409:  # 409 = already exists
                print(f"      ✗ Failed to add base to bundle: {status}")
        
        # Add additional parts
        for part_name in additional_parts:
            # First, check if this part exists in group.parts
            # If not, we need to create it as a new part identity
            part_identity_id = self._get_or_create_bundle_part(group, part_name)
            
            if part_identity_id:
                status, data = self.api.create_bundle_component(
                    parent_identity_id=bundle_identity_id,
                    child_identity_id=part_identity_id,
                    quantity_required=1,
                    role="Accessory",
                )
                if status == 201:
                    self.stats["bundle_components_created"] += 1
                    print(f"      ✓ Added part '{part_name}' to bundle")
                elif status != 409:
                    print(f"      ✗ Failed to add part '{part_name}' to bundle: {status}")
    
    def _get_or_create_bundle_part(self, group: ProductGroup, part_name: str) -> int | None:
        """Get or create a part identity for use in a bundle."""
        # Normalize the part name for lookup
        normalized = normalize_part_name(part_name)
        
        # Check if already exists in group parts
        for comp_type, part_id in group.parts.items():
            if normalize_part_name(comp_type) == normalized:
                return part_id
        
        # Create LCI definition for this bundle part
        lci_name = normalize_part_name(part_name)
        lci_status, lci_data = self.api.create_lci_definition(
            product_id=group.family_product_id,
            component_name=lci_name,
        )
        
        if lci_status == 201 and lci_data:
            self.stats["lci_definitions_created"] += 1
            print(f"      ✓ Created LCI definition for bundle part: {lci_name}")
        
        # Create new part identity
        status, data = self.api.create_identity(
            product_id=group.family_product_id,
            identity_type="P",
        )
        
        if status == 201 and data:
            part_id = data["id"]
            group.parts[part_name] = part_id
            self.stats["identities_created"] += 1
            print(f"      ✓ Created part for bundle: {part_name} -> id={part_id}")
            return part_id
        elif status == 409:
            # Part already exists - find it
            status, data = self.api.list_identities(group.family_product_id)
            if status == 200 and data:
                existing_parts = [i for i in data.get("items", []) if i["type"] == "P"]
                # Return the last part (most recently created)
                if existing_parts:
                    return existing_parts[-1]["id"]
        
        return None
    
    def print_summary(self) -> None:
        """Print import summary."""
        print("\n" + "=" * 60)
        print("📊 IMPORT SUMMARY")
        print("=" * 60)
        print(f"  Families created:          {self.stats['families_created']}")
        print(f"  Identities created:        {self.stats['identities_created']}")
        print(f"  Variants created:          {self.stats['variants_created']}")
        print(f"  Listings created:          {self.stats['listings_created']}")
        print(f"  Bundle components created: {self.stats['bundle_components_created']}")
        print(f"  LCI definitions created:   {self.stats['lci_definitions_created']}")
        print(f"  Errors:                    {len(self.stats['errors'])}")
        
        if self.stats["errors"]:
            print("\n⚠ ERRORS:")
            for error in self.stats["errors"][:20]:  # Show first 20 errors
                print(f"  - {error}")
            if len(self.stats["errors"]) > 20:
                print(f"  ... and {len(self.stats['errors']) - 20} more")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Import product data from CSV into USAV Inventory database"
    )
    parser.add_argument(
        "--csv-path",
        default=DEFAULT_CSV_PATH,
        help=f"Path to CSV file (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--username",
        default=DEFAULT_USERNAME,
        help=f"Admin username (default: {DEFAULT_USERNAME})",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help=f"Admin password (default: {DEFAULT_PASSWORD})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate import without making API calls",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of groups to process (for testing)",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🚀 USAV CSV Import Script")
    print("=" * 60)
    print(f"  CSV Path:  {args.csv_path}")
    print(f"  API URL:   {args.api_url}")
    print(f"  Username:  {args.username}")
    print(f"  Dry Run:   {args.dry_run}")
    
    # Initialize API client
    api_client = APIClient(args.api_url, args.username, args.password)
    
    # Authenticate (unless dry run)
    if not args.dry_run:
        if not api_client.authenticate():
            print("\n✗ Failed to authenticate. Exiting.")
            sys.exit(1)
    else:
        print("\n[DRY RUN MODE - No API calls will be made]")
    
    # Create importer and run
    importer = CSVImporter(api_client, dry_run=args.dry_run)
    importer.load_csv(args.csv_path)
    
    # Optionally limit groups for testing
    if args.limit:
        limited_groups = dict(list(importer.groups.items())[:args.limit])
        importer.groups = limited_groups
        print(f"\n⚠ Limited to {args.limit} groups for testing")
    
    importer.process_groups()
    importer.print_summary()
    
    print("\n✅ Import complete!")


if __name__ == "__main__":
    main()
