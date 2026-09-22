# Backend\app\integrations\ecwid

## What This Folder Does
Ecwid integration client and Ecwid payload mapping utilities.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Ecwid order normalization should populate optional customer enrichment fields (`customer_phone`, `customer_company`, `customer_source`) when present, otherwise downstream Zoho customer sync loses fidelity.
- Ecwid shipping normalization now checks optional `street2/addressLine2` and `street3/addressLine3`; populate normalized `ship_address_line2/ship_address_line3` when available.
- Ecwid order shipping amount should come from `shippingOption.shippingRate` (fallback `discountedShippingRate` / legacy `shipping`), because many order payloads do not populate top-level `shipping`.
- Ecwid tracking should map from `trackingNumber` into normalized `ExternalOrder.tracking_number` so downstream order headers can expose shipment references.
- Ecwid webhook endpoint (`POST /webhooks/ecwid`) handles `product.updated` and dispatches `sync_ecwid_price_to_shopify` in `price_sync.py` when `SHOPIFY_PRICE_SYNC_ENABLED=true`.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
