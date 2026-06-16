# Backend\app\modules\returns

## What This Folder Does
Returns domain: imports cancellation, return, and refund signals from eBay, Ecwid, Walmart, and Amazon CSVs; normalizes them into dashboard records plus line-item detail with fulfillment channel splitting; exposes manual sync plus list/detail API endpoints for the Returns UI; and validates/syncs eligible return records outbound to Zoho Sales Returns. Includes a rematching endpoint (`POST /returns/{record_id}/rematch`) to link previously unmatched records to sales orders.

## Typical Contents
- Router, service, dependencies, and SQLAlchemy models for returns visibility and Zoho Sales Return sync state.
- Sync-state handling separate from sales-order sync state.
- Schemas for dashboard list/detail, marketplace sync responses, and Zoho validation/sync responses.

## Common Pitfalls
- Do not mutate `orders.status`, `order_item.status`, or `orders.platform_data` from this module. The Zoho return path only writes return-level Zoho sync fields and may fill missing return/order Zoho mapping IDs found during validation.
- Zoho Sales Return sync must validate before calling Zoho create: local linked order, Zoho Sales Order ID/search hit, local order-item match, Zoho Sales Order line match, local available quantity, and Zoho shipped quantity must all pass. Before create, it also marks matched Zoho items `is_returnable=true` when Zoho says the item is not returnable.
- `Order.zoho_id` is the local Zoho Sales Order ID. Return item mapping is resolved from linked/local order item data against live Zoho Sales Order line items; there is no persisted `order_item` Zoho Sales Order line ID column. Zoho Sales Return line payloads need both the live line ID (`salesorder_item_id`) and product `item_id`.
- Partial returns and partial cancellations are line-quantity problems. Keep `return_item` quantities authoritative instead of flattening them into one header-only status.
- Return records that cannot be linked to a local order during ingestion receive the `UNMATCHED_ORDER` status; they can be re-attempted manually via the rematch endpoint which searches the linked external order ID and cascades status updates.
- Amazon return/cancellation data is imported via CSV (`POST /returns/import-amazon-csv`), filtering for cancelled orders and splitting into `SELF_FULFILLED` and `AMAZON_FBA` fulfillment channels based on `fulfillment-channel`.
- eBay true return cases and order-level refunds/cancellations come from different API surfaces. Prefer physical return/cancel classifications over refund-only classifications when the same case overlaps.
- eBay returns sync is intentionally list-first: use `getOrders` by `lastModifiedDate` as the cheap candidate detector, then call `getOrder/{orderId}` only for suspicious candidate payloads that need enrichment. Do not reintroduce per-order detail hydration for the full window.
- Ecwid order-level refund payloads may expose only `refundedAmount` with no per-line return/refund detail. For a single-line refunded order, the importer assigns the header refund to that one line and sets the returned quantity when the order is refund-only; multi-line refund-only orders remain ambiguous unless Ecwid provides return/line detail.
- Walmart cancellations come from Orders API line statuses, while physical returns/refunds come from Returns API payloads; do not assume one source covers both.
- `return_sync_state` is intentionally separate from `integration_state`; `/returns/sync/status` must not affect the Orders dashboard.

## Child Folders
- `schemas/`
