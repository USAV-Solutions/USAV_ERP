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
- `CSV_GENERIC` order import also accepts ShipStation order-export headers (for example `Order - CustomerID`, `Order - Number`, `Date - Order Date`); when product columns are missing, the importer creates a synthetic line item (`Imported order line`) using order-level totals.
- ShipStation `Count - Number of Items` can be `0`; CSV import now clamps synthetic-item quantity to at least `1` to satisfy `order_item` positive-quantity DB constraints.
- `order_item.variant_id` is denormalized once `platform_listing_id` is introduced; code paths that update listing assignments must keep `order_item.variant_id` in sync.

## Child Folders
- `schemas/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
