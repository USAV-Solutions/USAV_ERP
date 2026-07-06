# Backend\app\modules\orders

## What This Folder Does
Sales orders domain: ingestion/import, listing-centric matching, filtering, customer CSV upsert, order sync state, the split between self-fulfilled orders vs Amazon FBA orders, and **Photo Station package verification workflow** including end-of-day box counting.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- `routes.py`: Holds endpoints including `/orders/photo-station/verify`, `/orders/photo-station/verify-shelf`, `/orders/photo-station/upload`, and `/orders/photo-station/extract-ocr`.

## Common Pitfalls
- **Order Verification States:** `orders.verify_status` transitions between `UNVERIFIED` (default), `VERIFIED` (photos captured and tracking exists), `READY` (shelf count validation matches), `ERROR_MISSING_TRACKING`, and `ERROR_COUNT_MISMATCH`. Keep status mutations aligned with business logic.
- **Gemini Vision OCR Extraction:** The `/orders/photo-station/extract-ocr` endpoint requires a valid `GEMINI_API_KEY` or `GOOGLE_API_KEY` environment variable on the backend container. It uses the `google-genai` SDK to run zero-shot parsing of marketplace name, Order ID, and tracking numbers from packing slips, bypassing client-side Tesseract.js.
- **Packing Metadata:** `orders.packing_metadata` stores JSON paths to Synology NAS photo attachments (`slip_photo` and `box_photo`).
- **FileStation/Upload Proxying:** Frontend uploads base64 canvas captures to `/api/orders/photo-station/upload` which uploads to Synology DS418j FileStation API via DSM WebAPI. If NAS is offline or unconfigured, it defaults to saving locally under `Backend/static/photos/` as a fallback.
- **End-of-Day Box Count:** `/photo-station/verify-shelf` queries `locate_anything.py` using NVIDIA Locate Anything 3B model prompt. If the counted boxes mismatch today's `VERIFIED` order count, all active verified orders are flagged as `ERROR_COUNT_MISMATCH` and a discrepancy warning is returned.
- Forgetting to align platform/source enums across model, schema, migration, and frontend types.
- Adding filters in route layer but not implementing repository query logic.
- Bypassing OrderSyncService ingestion path and breaking dedupe/matching consistency.
- Order ingestion is now true upsert by `(platform, external_order_id)`: existing headers/line items are refreshed from inbound payloads (new items inserted), so duplicates are no longer pure no-op skips.
- Customer upsert during ingestion is merge-based (fills missing phone/company/address fields) and source is overwrite-based (latest channel replaces prior `Customer.source`).
- Platforms that failed with credential/auth bootstrap errors (for example token acquisition failures) are auto-reset from `ERROR` to `IDLE` on the next sync attempt; this avoids permanent lockout but still records the current attempt's real failure if credentials remain invalid.
- `SHIPSTATION_CUSTOMER_CSV` is intentionally customer-only (no order rows created); keep frontend messaging aligned with `customers_created/customers_updated` counters.
- `CSV_GENERIC` order import now treats ShipStation order CSV as line-item rows grouped by `Order - Number`; order-level fields (totals, ship-to, customer, date) are read from the first row and item fields come from `Item - Name`/`Item - SKU`/`Item - Qty`/`Item - Price`. For ShipStation rows, missing line totals now fall back to `Item - Price * Qty` instead of order-level subtotal/total so marketplace line items do not absorb tax/shipping.
- Blank ShipStation rows (missing `Item - Name`) are removed before import; rows that do not match a parent order (`Ship To - Address 1` + `Ship To - Postal Code`, fallback `Bill To - Name`) are exported to `Backend/misc/unmatched_exceptions.csv` for manual review.
- `CSV_GENERIC` import now attempts per-row platform detection (`platform`/`source` plus ShipStation store/source columns) and ingests batches under detected `orders.platform` values instead of forcing everything to `MANUAL`; rows identified as `ECWID` are skipped so ShipStation CSV cannot duplicate Ecwid API orders.
- ShipStation `Count - Number of Items` can be `0`; CSV import now clamps synthetic-item quantity to at least `1` to satisfy `order_item` positive-quantity DB constraints.
- Order header no longer stores duplicated customer/shipping snapshot columns; order responses derive customer name/email/address from the linked `customer` relation. Keep customer linkage and backfill behavior healthy before relying on outbound sync fields.
- Tracking numbers are now normalized into order headers from API/CSV payloads; keep adapter/raw key mappings (`trackingNumber`, `tracking_number`, `Tracking Number`) aligned.
- ShipStation multi-line orders can carry different tracking values per row; import now stores a unique merged header string (`tracking_1 + tracking_2 + ...`) in `orders.tracking_number`.
- Order list responses now include `subtotal_amount`, `tax_amount`, and `shipping_amount` so frontend totals can consistently compute `subtotal + tax + shipping`.
- `OrderStatus` now includes `RETURN` and `PARTIALLY_REFUNDED`; these are automatically applied to the order when an order return record is successfully linked during return ingestion or manual rematch.
- `CSV_GENERIC` order import persists `orders.source=SHIPSTATION_CSV` for all imported orders (including platform-detected batches) instead of using `*_API` source values.
- When CSV rows omit subtotal/order-line totals, import derives subtotal from summed item row totals; if order total is missing, fallback total is calculated as `line_total + tax + shipping + handling`. Marketplace orders are normalized after ingestion so stored `subtotal_amount` follows summed item prices and stored `total_amount` excludes marketplace tax while preserving shipping/handling.
- Order list/detail responses now include `platform_total_amount` and `zoho_total_amount`; `zoho_total_amount` excludes tax for marketplace platforms (`AMAZON`, `WALMART`, and all eBay stores) and includes tax for other platforms.
- `order_item.variant_id` is denormalized once `platform_listing_id` is introduced; code paths that update listing assignments must keep `order_item.variant_id` in sync.
- Sales-order line items can now be added manually via `POST /orders/{order_id}/items`; new rows mark order `zoho_sync_status=DIRTY`, set item status from `variant_id` (`MATCHED` vs `UNMATCHED`), and recalculate order subtotal/total from line totals while preserving any previously inferred handling delta.
- Sales-order line items now support inline maintenance via `PATCH /orders/items/{item_id}` and `DELETE /orders/items/{item_id}`; successful edits/deletes mark parent order `zoho_sync_status=DIRTY` and recalculate order subtotal/total from current line totals.
- Admin can bulk re-check unmatched line items via `POST /orders/sync/refresh-matching`; it tries `external_item_id` → `platform_listing.external_ref_id` first, then normalized name matching (`lowercase` + punctuation/spacing removed) between `item_name` and `platform_listing.listed_name`, and auto-sets `order_item.variant_id/status` when a mapped active listing is found.
- Tracking number uniqueness and validation: Tracking numbers are unique across all orders in the database. Manual updates assigning duplicate tracking numbers fail with 400.
- Order and shipping status constraints: Changing order status to `SHIPPED`/`DELIVERED` or shipping status to `SHIPPING`/`DELIVERED` requires a tracking number.
- `TRACKING_CSV` file import source: Allows bulk updating order tracking details. Matches automatically update orders to `SHIPPED`/`SHIPPING`, auto-detect carrier, and mark Zoho `DIRTY`.
- Orders persist `fulfillment_channel` separately from `source`.
- `GET /orders` and `GET /orders/sync/status` filter by `fulfillment_channel`.
- `AMAZON_FBA_CSV` imports Amazon orders and maps customers using `Customer.amazon_buyer_id`.
- FBA orders cannot be downgraded back to `SELF_FULFILLED` by regular API syncs.
- Tracking number uniqueness and validation: Tracking numbers are unique across all orders in the database. Manual updates attempting to assign duplicate tracking numbers will fail with 400 Bad Request. Background syncs and tracking CSV imports will log a warning and skip duplicates.
- Order and shipping status constraints: Changing order status to `SHIPPED` or `DELIVERED`, or shipping status to `SHIPPING` or `DELIVERED`, requires a tracking number.
- `TRACKING_CSV` file import source: Allows bulk updating order tracking details using daily Google Sheet summary files (Platform in Col A, Order Number in Col B, Tracking in Col I). Successful matches automatically update orders to `SHIPPED`/`SHIPPING`, auto-detect carrier, and mark Zoho sync status `DIRTY`. Missing orders, empty tracking numbers, and Google Sheets scientific-notation tracking values are ignored.
- `SHIPPING_STATUS_CSV` file import source: Allows bulk updating order shipping status via a CSV (matching by `order_number` column and applying `scraped_status`). Handles unrecognised/empty statuses by defaulting to `PENDING`.
- Orders now persist `fulfillment_channel` separately from `source`: use `source` for provenance (`*_API`, `SHIPSTATION_CSV`, `AMAZON_FBA_CSV`) and `fulfillment_channel` for the UI/business split (`SELF_FULFILLED`, `AMAZON_FBA`). Do not overload `source` when adding new views or sync rules.
- `GET /orders` and `GET /orders/sync/status` accept `fulfillment_channel`; repository filtering is applied before search/count/pagination so search results only include the active view.
- `AMAZON_FBA_CSV` imports `Backend/misc/weekly.csv`-style exports, groups rows by `order-id`, always ingests under platform `AMAZON`, and marks matching/new orders `fulfillment_channel=AMAZON_FBA`.
- `AMAZON_FBA_CSV` customer handling now treats `buyer-id` as the stable identity key (fallback: marketplace-email local part), stores it on `Customer.amazon_buyer_id`, and keeps `buyer-name` as the local human-readable customer name. Matching now prefers `amazon_buyer_id` before email/name fallbacks.
- Standard API / ShipStation CSV imports create new orders as `SELF_FULFILLED`; if an existing Amazon order was previously upgraded by FBA CSV import, later API syncs must not downgrade it back.

## Recent Behavior Change: Platform Listing mappings
- The `_learn_listing` flow allows multiple listings per `variant_id` on the same platform as long as `external_ref_id` is unique.

## Child Folders
- `schemas/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
