# Backend\app\modules\inventory\schemas

## What This Folder Does
Inventory domain request/response schema contracts.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- `PlatformListing` schema now exposes `merchant_sku` and `platform_metadata` for channel publish workflows (eBay/Ecwid/Amazon). Keep `platform_metadata` shape stable at the API boundary when frontend publishing forms depend on specific keys.
- `PlatformListing` now also carries explicit editable fields `listing_quantity`, `listing_type`, `listing_condition`, and `upc`; keep validation bounds consistent with ORM/migration types.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
