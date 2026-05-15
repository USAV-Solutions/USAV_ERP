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
- Variants export endpoint `GET /variants/export/zoho-import.csv` now treats Kits like Bundles for `exclude_bundles=true` (both `B` and `K` are excluded).
- Identity creation flow now auto-generates the base variant for `K` identities (same as Product/Part/Bundle), so downstream variant/search screens see newly created Kits immediately.
- eBay publish endpoints under listings validate required store defaults before calling eBay. Business policy IDs follow an all-or-none rule: if all three IDs are configured they are sent; if none are configured publish continues and relies on eBay account defaults; partial configuration returns `400`.
- eBay listing wizard now has image endpoints under listings: available-image preload, local image upload (Admin/Sales), and selected-image send to eBay Media API; publish should use returned EPS URLs and enforce max 24 images.
- eBay publish flow persists identity dimension/weight only when DB fields are currently empty, then maps these values to Trading `ShippingPackageDetails`; incomplete package inputs hard-fail publish validation.
- Listing creation UI scaffolding now has dedicated routes under `/listings/create/*`; these are intentional placeholders and return scaffold status until full creation flows are implemented.
- Active Listings UI actions now rely on listing routes for `POST /listings/{id}/sync`, `POST /listings/{id}/match`, and `POST /listings/{id}/unmatch`; these currently update listing sync/match state in DB and do not call remote platform APIs directly.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
