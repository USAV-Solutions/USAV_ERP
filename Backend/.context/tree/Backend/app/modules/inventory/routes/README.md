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
- eBay publish route now uses Inventory API sequence (`PUT inventory_item` -> create/update `offer` -> `publish`) and stores `platform_metadata.publish_engine=inventory_api_v1`, `platform_metadata.offer_id`, and `external_ref_id=listingId`.
- eBay draft defaults now set title from variant naming chain (`variant_name` first, then identity/family/SKU) and base price from the highest ECWID listing price for the same variant when ECWID rows exist.
- eBay publish policy selection is now config-driven: payment policy + return policy (standard vs no-returns hook) + fulfillment policy (light/heavy/free via configured threshold and shipping mode flags), plus per-store `merchant_location_key`.
- Publish accepts public image URLs directly; relative `/product-images/...` entries are normalized via `LISTING_PUBLIC_BASE_URL`, and invalid/non-public URLs return `400`.
- eBay listing wizard image-send endpoint remains available as optional Media API flow, but publish validation no longer depends on EPS upload/signature gates.
- New optional `POST /listings/ebay/ai-enrich` endpoint returns best-effort category/aspect/title/description/dimension suggestions with warning list; GraphQL/Gemini failures must not block manual publish path.
- `ai-enrich` Gemini prompts intentionally mirror the prompt patterns used in `misc/Ebay_Listing/useAppLogic.ts` (HTML description template + package JSON estimate), and AI package values only fill missing dimensions/weight fields.
- Listing creation UI scaffolding now has dedicated routes under `/listings/create/*`; these are intentional placeholders and return scaffold status until full creation flows are implemented.
- Active Listings UI actions now rely on listing routes for `POST /listings/{id}/sync`, `POST /listings/{id}/match`, and `POST /listings/{id}/unmatch`; these currently update listing sync/match state in DB and do not call remote platform APIs directly.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
