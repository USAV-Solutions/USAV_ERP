# Backend\app\modules\orders

## What This Folder Does
Sales orders domain: ingestion/import, listing-centric matching, filtering, customer CSV upsert, and order sync state.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Forgetting to align platform/source enums across model, schema, migration, and frontend types.
- Adding filters in route layer but not implementing repository query logic.
- Bypassing OrderSyncService ingestion path and breaking dedupe/matching consistency.
- Customer upsert during ingestion is merge-based (fills missing phone/company/address fields) and source is overwrite-based (latest channel replaces prior `Customer.source`).
- Platforms that failed with credential/auth bootstrap errors (for example token acquisition failures) are auto-reset from `ERROR` to `IDLE` on the next sync attempt; this avoids permanent lockout but still records the current attempt's real failure if credentials remain invalid.
- `SHIPSTATION_CUSTOMER_CSV` is intentionally customer-only (no order rows created); keep frontend messaging aligned with `customers_created/customers_updated` counters.
- `CSV_GENERIC` order import now treats ShipStation order CSV as line-item rows grouped by `Order - Number`; order-level fields (totals, ship-to, customer, date) are read from the first row and item fields come from `Item - Name`/`Item - SKU`/`Item - Qty`/`Item - Price`.
- Blank ShipStation rows (missing `Item - Name`) are removed before import; rows that do not match a parent order (`Ship To - Address 1` + `Ship To - Postal Code`, fallback `Bill To - Name`) are exported to `Backend/misc/unmatched_exceptions.csv` for manual review.
- `CSV_GENERIC` import now attempts per-row platform detection (`platform`/`source` columns) and ingests batches under detected `orders.platform` values instead of forcing everything to `MANUAL`.
- ShipStation `Count - Number of Items` can be `0`; CSV import now clamps synthetic-item quantity to at least `1` to satisfy `order_item` positive-quantity DB constraints.
- Order header no longer stores duplicated customer/shipping snapshot columns; order responses derive customer name/email/address from the linked `customer` relation. Keep customer linkage and backfill behavior healthy before relying on outbound sync fields.
- Tracking numbers are now normalized into order headers from API/CSV payloads; keep adapter/raw key mappings (`trackingNumber`, `tracking_number`, `Tracking Number`) aligned.
- ShipStation multi-line orders can carry different tracking values per row; import now stores a unique merged header string (`tracking_1 + tracking_2 + ...`) in `orders.tracking_number`.
- Order list responses now include `subtotal_amount`, `tax_amount`, and `shipping_amount` so frontend totals can consistently compute `subtotal + tax + shipping`.
- `order_item.variant_id` is denormalized once `platform_listing_id` is introduced; code paths that update listing assignments must keep `order_item.variant_id` in sync.

## Child Folders
- `schemas/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
