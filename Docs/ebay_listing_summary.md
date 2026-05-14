# eBay Listing Tools Summary (Product Listing)

This summary reflects the current eBay listing tooling implemented under product listings routes.

## Scope and Base Path

- API base prefix: `/api/v1`
- Listing router prefix: `/listings`
- eBay-specific tools are currently limited to platforms:
  - `EBAY_MEKONG`
  - `EBAY_USAV`
  - `EBAY_DRAGON`

## Current eBay Listing Endpoints

1. `GET /api/v1/listings/create/scaffold`
- Returns current create-flow capability flags.
- eBay platforms are marked enabled with scaffold status; Amazon/Ecwid/Walmart are placeholders.

2. `POST /api/v1/listings/create/ebay/start`
- Scaffold bootstrap endpoint for create-listing flow.
- Returns scaffold status message (full flow still pending).

3. `POST /api/v1/listings/ebay/draft`
- Builds a prefilled draft from variant + existing listing + store defaults.
- Includes title/description/price/quantity/condition, marketplace defaults, dimensions, shipping package details, category (if already known), picture URLs, and seller policy profile IDs.

4. `POST /api/v1/listings/ebay/category-suggestions`
- Builds or accepts a search query and calls eBay Taxonomy APIs.
- Returns `marketplace_id`, `category_tree_id`, resolved query, and parsed category suggestions.

5. `GET /api/v1/listings/ebay/images/available/{variant_id}`
- Scans SKU image directory and returns available image candidates for listing.
- Supports both flat files and `listing-*` subfolders.

6. `POST /api/v1/listings/ebay/images/upload`
- Uploads images into SKU listing folders (`listing-{index}`).
- Auto-increments `img-{n}` filenames.
- Allowed extensions: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`, `.tiff`, `.avif`, `.heic`.

7. `POST /api/v1/listings/ebay/images/send`
- Sends selected local images to eBay Media API (`create_image_from_file`).
- Returns per-image success/error and uploaded EPS image URLs.
- Enforces eBay max image count (24).

8. `POST /api/v1/listings/ebay/publish`
- Validates payload and publishes via eBay Trading API `AddFixedPriceItem`.
- Persists/updates internal `platform_listing` record with returned eBay `item_id`.
- Stores eBay metadata (category, pictures, specifics, shipping package details, profiles).

## Key Validation/Behavior Rules in Current Implementation

- eBay-only guard: eBay listing endpoints reject non-eBay platforms.
- Business policy IDs must be either all present (`payment`, `return`, `shipping`) or all omitted.
- Publish requires at least one picture URL.
- Publish requires a supported condition mapping (`N/NEW`, `U/USED`, `R/REFURBISHED`, `FOR_PARTS` variants).
- Publish requires dimensions + weight to construct `ShippingPackageDetails`.
- Publish requires at least one item specific (brand/mpn/color/upc or extra specifics).
- Publish blocks duplicate active listing publish when variant already has an `external_ref_id` on same platform.
- Image IDs are sanitized and path traversal is rejected.

## Supporting Generic Listing APIs

The same router also includes generic listing CRUD and sync-status endpoints (create, update, delete, mark-synced, mark-error, match/unmatch, queue sync). These are platform-agnostic and support eBay records once created.
