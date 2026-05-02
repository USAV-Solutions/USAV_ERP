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
- eBay publish endpoints under listings now validate required store defaults and business policy IDs before calling eBay; missing env config returns `400` instead of attempting remote publish.
- eBay publish flow persists identity dimension/weight only when DB fields are currently empty, then maps these values to Trading `ShippingPackageDetails`; incomplete package inputs hard-fail publish validation.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
