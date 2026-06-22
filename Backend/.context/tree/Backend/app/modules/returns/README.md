# Backend\app\modules\returns

## What This Folder Does
Returns domain: imports cancellation, return, and refund signals from eBay, Ecwid, Walmart, and Amazon CSVs; normalizes them into dashboard records plus line-item detail with fulfillment channel splitting; exposes manual sync plus list/detail API endpoints for the Returns UI; and validates/syncs eligible records outbound to Zoho Sales Returns or Zoho Sales Order cancellation depending on normalized status. Includes a rematching endpoint (`POST /returns/{record_id}/rematch`) to link previously unmatched records to sales orders.

## Typical Contents
- Router, service, dependencies, and SQLAlchemy models for returns visibility and Zoho outbound sync state.
- Sync-state handling separate from sales-order sync state.
- Schemas for dashboard list/detail, marketplace sync responses, and Zoho validation/sync responses.

## Common Pitfalls
- Return ingestion mirrors linked-order status for cancelled, refunded, partially refunded, and returned records. Keep `order_status_enum` migrations in sync with `OrderStatus` values or the whole return import transaction can roll back after marketplace fetch succeeds.
- Zoho Sales Return sync must validate before calling Zoho create: local linked order, Zoho Sales Order ID/search hit, local order-item match, Zoho Sales Order line match, local available quantity, and Zoho shipped quantity must all pass. Before create, it also marks matched Zoho items `is_returnable=true` when Zoho says the item is not returnable.
- Cancelled and partially cancelled records must not create Zoho Sales Returns. They sync against the Zoho Sales Order instead: full-order cancellation calls Zoho Sales Order void, and partial cancellation updates Sales Order line quantities after validating the requested quantity is still unfulfilled (`quantity - packed/shipped/invoiced`).
- `Order.zoho_id` is the local Zoho Sales Order ID. Return item mapping is resolved from linked/local order item data against live Zoho Sales Order line items; there is no persisted `order_item` Zoho Sales Order line ID column. Zoho Sales Return line payloads need both the live line ID (`salesorder_item_id`) and product `item_id`.
- Partial returns and partial cancellations are line-quantity problems. Keep `return_item` quantities authoritative instead of flattening them into one header-only status.
- Return records that cannot be linked to a local order during ingestion receive the `MISSING_LOCAL_ORDER` `zoho_sync_status` while preserving their original normalized status; they can be re-attempted manually via the rematch endpoint which searches the linked external order ID and links the record, reverting `zoho_sync_status` to `PENDING`.
- Amazon return/cancellation data is imported via CSV (`POST /returns/import-amazon-csv`), filtering for cancelled orders and splitting into `SELF_FULFILLED` and `AMAZON_FBA` fulfillment channels based on `fulfillment-channel`.
- eBay true return cases and order-level refunds/cancellations come from different API surfaces. Prefer physical return/cancel classifications over refund-only classifications when the same case overlaps.
- eBay returns sync is intentionally list-first: use `getOrders` by `lastModifiedDate` as the cheap candidate detector, then call `getOrder/{orderId}` only for suspicious candidate payloads that need enrichment. Do not reintroduce per-order detail hydration for the full window.
- Ecwid order-level refund payloads may expose only `refundedAmount` with no per-line return/refund detail. For a single-line refunded order, the importer assigns the header refund to that one line and sets the returned quantity when the order is refund-only; multi-line refund-only orders remain ambiguous unless Ecwid provides return/line detail.
- Walmart cancellations come from Orders API line statuses, while physical returns/refunds come from Returns API payloads; do not assume one source covers both.
- `return_sync_state` is intentionally separate from `integration_state`; `/returns/sync/status` must not affect the Orders dashboard.

## Child Folders
- `schemas/`
