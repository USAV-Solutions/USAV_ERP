# Backend\app\modules\inventory\routes

## What This Folder Does
Inventory route handlers split by feature surface (variants, listings, images, etc.).

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Stored `thumbnail_url` values can become stale when files move or disappear; image routes should validate cached URLs and recompute from on-disk listing folders when missing.
- `thumbnail_url` is SKU-path scoped; when `full_sku` changes, clear/recompute `thumbnail_url` to avoid cross-SKU thumbnails being shown.
- Product-to-kit conversion now has a dedicated route: `POST /variants/{variant_id}/convert-to-kit` (Admin/Sales). It creates a new `K` identity+variant, writes bundle components, migrates linked rows (`platform_listing`, `inventory_item`, `order_item`, `purchase_order_item`), and deactivates the source variant in one transaction.
- `convert-to-kit` child lines accept only Product/Part variants, reject Bundle/Kit/self/duplicate-child-identity lines, and intentionally do not call Zoho APIs; the new kit variant remains pending for manual Zoho sync.
- Zoho composite sync resolves bundle/kit child dependencies from active child variants only; inactive child variants are ignored to avoid sending stale Zoho `item_id` values in composite mapped items.
- Variants export endpoint `GET /variants/export/zoho-import.csv` now treats Kits like Bundles for `exclude_bundles=true` (both `B` and `K` are excluded).
- Identity creation flow now auto-generates the base variant for `K` identities (same as Product/Part/Bundle), so downstream variant/search screens see newly created Kits immediately.
- Active Listings UI actions now rely on listing routes for `POST /listings/{id}/sync`, `POST /listings/{id}/match`, and `POST /listings/{id}/unmatch`; these currently update listing sync/match state in DB and do not call remote platform APIs directly.
- Active Listings now supports bulk CSV import via `POST /listings/import/csv` (Admin/Sales): expected columns are `item_id` (external ref), `platform`, `inventory_db_sku_primary` (variant full SKU), and `item_name`/`listing_name`; platform values may come as list-like strings (for example `['amazon']`) and are normalized to internal platform enums.
- CSV import response now includes per-row `created_logs`, `updated_logs`, and `errors` summaries (first 200 lines each), and server logs emit row-level create/update/skip messages for troubleshooting.
- eBay Listing flow is handled under `/listings/ebay/*` (e.g., `/accounts`, `/categories`, `/ai/*`, `/publish`). It uses the Inventory API (`put_inventory_item`, `create_offer`, `publish_offer`) and Gemini for AI suggestions. The store-specific configurations (policy IDs) are read from `ebay-accounts.json` external file.
- Active Listings now supports Shopify catalog import via `POST /listings/import/shopify` (Admin/Sales): queries Shopify GraphQL `products` and auto-links to ERP variants by matching SKU against `ProductVariant.full_sku` or Ecwid `PlatformListing.merchant_sku`.
- Active Listings Knowledge Graph and AI match endpoints added:
  - `GET /listings/graph/{variant_id}`: returns central ProductVariant node, linked PlatformListing nodes, hub group nodes (`Variants`, `Accessory`, `Component`), and topology edges for grouped orbit visualization.
  - `POST /listings/suggest`: AI listing matcher combining string heuristic pre-filtering with Gemini AI confidence scoring (0.0 to 1.0) and semantic relationship classification (`EXACT`, `ACCESSORY`, `BUNDLE_COMPONENT`, `KIT_COMPONENT`, `PART_LCI`).
  - `POST /listings/lock-relationship`: locks a platform listing to a product variant and enriches missing variant master metadata.
  - `POST /listings/compare`: compares 2 to 10 listing nodes side-by-side across all channel metrics.
- Orbit View & USAV UPIS Specification Endpoints (`/orbit/*`):
  - `GET /orbit/analytics/{variant_id}`: Computes real-time sales order velocity, 30d/90d revenue, warehouse available inventory, stock runway days, automated Ecwid ↔ Shopify price mismatch detection, and 10 most recent order sales transactions (`platform`, `order_id`, `quantity`, `unit_price`, `ordered_at`, `status`).
  - `POST /orbit/bundle-kit/create`: Dual creator for USAV Bundles (Type `B` - dynamic assembly) and Predefined Manufacturer Kits (Type `K` - fixed unit with roles `MAIN_UNIT`, `SATELLITE_SPEAKER`, `SUBWOOFER`, `ACCESSORY`) adhering to USAV UPIS Layer 1 syntax (`[ProductID]-[Type]`).
  - `POST /orbit/convert-type`: Instant product classification converter (Type `Product`, `B`, `K`) with automated recipe updates and UPIS SKU re-evaluation.
  - `POST /orbit/variant/create`: Rapid variant generator adhering to USAV UPIS Layer 2 (UML: `[UPIS-H]-[Color]-[Condition]`).
  - `POST /orbit/relationship/update`: Updates semantic relationship tether type (`EXACT`, `ACCESSORY`, `BUNDLE_COMPONENT`, `KIT_COMPONENT`, `PART_LCI`, `SIBLING_VARIANT`).
  - `POST /orbit/relationship/unlink`: Unlinks listing from variant or severs component tether.
  - `POST /orbit/ai/deep-classify`: Two-stage AI product classification. Stage 1 sends product name/brand to Gemini to infer real-world product type (`Product`, `K`, `B`, `P`) and expected components. Stage 2 executes local SQL fuzzy matching across catalog to link existing database variants with zero additional AI token cost.
  - `GET /orbit/bundles/{variant_id}`: Discovers parent bundles/kits that this product participates in, along with other sibling components.
  - `GET /orbit/universe`: Returns the complete 3D macro universe topology (Brands as Big Stars, Product Families as Small Planets, Products/Units as Moons, and Cross-family bundle/kit tethers).

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
