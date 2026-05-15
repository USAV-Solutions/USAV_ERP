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
- Variant conversion-to-kit contracts are now part of this folder (`ProductVariantConvertToKitRequest/Response`). Keep `children[]` line keys (`child_variant_id`, `quantity_required`, `role`) and `migrated_counts` response structure stable for inventory edit-panel compatibility.
- eBay publish response contract now returns `external_ref_id` (remote listing ID) and `offer_id`; frontend should not rely on legacy `item_id` from Trading API publish.
- New `ebay/ai-enrich` schemas carry optional suggestion payloads (`category_id`, `aspects`, `valid_conditions`, `dimensions`, `warnings`); warnings are first-class response fields because enrich is best-effort.
- eBay publish request still requires explicit `category_id` + `picture_urls` + `condition_text`, but `picture_urls` now represent public URLs used directly for Inventory API `product.imageUrls` (not EPS-only URLs).
- eBay publish request now includes optional shipping-policy hooks (`is_free_shipping`, `use_no_returns_policy`) so publish can select configured fulfillment/return policies without changing endpoint shape for existing callers.
- Category suggestions continue returning normalized `category_id` + breadcrumb tokens; preserve this shape so frontend selection can be injected directly into publish payload.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
