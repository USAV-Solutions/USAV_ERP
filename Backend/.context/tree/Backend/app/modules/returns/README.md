# Backend\app\modules\returns

## What This Folder Does
Read-only returns domain: imports cancellation, return, and refund signals from eBay, Ecwid, and Walmart; normalizes them into dashboard records plus line-item detail; and exposes manual sync plus list/detail API endpoints for the Returns UI.

## Typical Contents
- Router, service, dependencies, and SQLAlchemy models for returns visibility.
- Sync-state handling separate from sales-order sync state.
- Schemas for dashboard list/detail and sync responses.

## Common Pitfalls
- Do not mutate `orders.status`, `order_item.status`, `orders.platform_data`, or Zoho sync state from this module; v1 is linked-but-read-only.
- Partial returns and partial cancellations are line-quantity problems. Keep `return_item` quantities authoritative instead of flattening them into one header-only status.
- eBay true return cases and order-level refunds/cancellations come from different API surfaces. Prefer physical return/cancel classifications over refund-only classifications when the same case overlaps.
- eBay returns sync is intentionally list-first: use `getOrders` by `lastModifiedDate` as the cheap candidate detector, then call `getOrder/{orderId}` only for suspicious candidate payloads that need enrichment. Do not reintroduce per-order detail hydration for the full window.
- Walmart cancellations come from Orders API line statuses, while physical returns/refunds come from Returns API payloads; do not assume one source covers both.
- `return_sync_state` is intentionally separate from `integration_state`; `/returns/sync/status` must not affect the Orders dashboard.

## Child Folders
- `schemas/`
