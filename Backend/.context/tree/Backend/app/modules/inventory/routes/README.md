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

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
