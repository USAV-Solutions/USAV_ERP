# Backend\app\integrations\zoho

## What This Folder Does
Zoho client/sync engine used for outbound and inbound synchronization flows.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Stationery purchase-order sync should use `zoho_po_stationery_location_id` from settings; hardcoded location IDs can fail with Zoho `Invalid value passed for branch_id` errors.
- Purchase-order hash-match (`zoho_last_sync_hash`) does not mean Zoho billing is complete; when billing sync is enabled, bill reconciliation must still run on unchanged PO payloads.
- Auto bill sync eligibility includes all `EBAY_*` sources and `GOODWILL_SHIPPED`; keep this source-gate aligned with import/source mappings to avoid silent billing skips.
- Auto billing in `sync_engine.py` creates bills only; it does not auto-create vendor payments.
- `PurchaseOrder` Zoho billing state columns are deferred in ORM mapping (`zoho_bill_created`, etc.). In async sync paths, explicitly `undefer(...)` these fields before reading them to avoid implicit lazy-load IO that raises `sqlalchemy.exc.MissingGreenlet`.
- Purchase-order outbound payload now includes `cf_source` mapping. Keep mapping aligned with script behavior (`EBAY_* -> Ebay`, `AMAZON_* -> Amazon`, `GOODWILL_SHIPPED` and `GOODWILL_PICKUP` -> `Goodwill`, `ALIEXPRESS_* -> AliExpress`, local pickup variants -> `Local Pickup`, fallback -> `Other`).
- Customer outbound payload now mirrors billing to shipping address and can include a contact source custom field via `zoho_contact_cf_source_api_name`/`zoho_contact_cf_source_id`; inbound mapper reads this value back into `Customer.source` when present.
- Customer outbound payload now forces tax preference to tax-exempt (`is_taxable=false`) and, when configured, includes `tax_exemption_id`/`tax_authority_id`. It also sends a primary `contact_persons` entry to keep Zoho UI email/phone fields populated for business contacts.
- Amazon FBA customers no longer use `Customer.name` as Zoho `contact_name` when a stable buyer key exists. Outbound sync sends `contact_name = "Amazon FBA - {amazon_buyer_id}"`, while the human buyer name stays in the primary contact person/local `Customer.name`. Inbound contact mapping extracts that prefix back into `Customer.amazon_buyer_id` and avoids overwriting the local human name unless Zoho sends one separately.
- Sales-order outbound payload uses `salesorder_number` (from `external_order_number` fallback `external_order_id`) and reserves `reference_number` for tracking (`Order.tracking_number`). Legacy duplicate detection still falls back to matching `reference_number == external_order_id` for older rows.
- Sales-order source is sent through SO custom fields (`api_name=cf_source`) using `Order.platform` first and `Order.source` only as fallback. Current dropdown mapping: `Ebay_Dragon`, `Ebay_Mekong`, `Ebay_USAV`, `ECWID`, `Amazon`, `Shopify`, `Walmart`, fallback `Other`.
- Sales-order outbound payload now also checks `Order.fulfillment_channel`; `AMAZON_FBA` orders must send `location_id=5623409000001937413`, while self-fulfilled orders keep the prior no-location behavior.
- Zoho can return code `15` for sales-order `shipping_address` length; outbound sales-order payload now omits `shipping_address` and relies on `customer_id` contact addresses instead.
- Sales-order outbound payload now sends `shipping_charge` from `Order.shipping_amount` for all sources and syncs totals using Zoho-total math: marketplaces use line total + shipping + inferred handling, while non-marketplace platforms add tax + inferred handling.
- Sales-order outbound tax handling is platform-based end-to-end: marketplaces (`AMAZON`, `WALMART`, all `EBAY_*`) keep line `tax_percentage=0`, exclude tax from stored/Zoho totals, and only send inferred handling as Zoho adjustment; other ecommerce platforms preserve tax in payload adjustment.
- Sales-order outbound sync now calls Zoho confirm (`/salesorders/{id}/status/confirmed`) after create/update; errors that indicate “already confirmed” are treated as non-fatal, while other confirm failures keep sync in `ERROR`.
- Purchase-order outbound line `rate` should be derived from `PurchaseOrderItem.total_price / quantity` when available (not only `unit_price`) to avoid cent drift on multi-qty lines (example: `26.99 / 5 = 5.398`).
- Purchase-order outbound sync now folds `tax_amount + shipping_amount + handling_amount` into line-item rates by splitting the charge pool evenly across PO lines. Do not send PO-level `adjustment`/`adjustment_description` for these charges, and keep the post-sync total guardrail aligned with `PurchaseOrder.total_amount`.
- Zoho composite-item create/update payloads must use `mapped_items` (not `component_items`); Zoho returns `code:4` / `Invalid value passed for mapped_items` when the mapping key or mapped entry shape is wrong.
- Zoho API requests using `httpx.AsyncClient` must configure a generous timeout (e.g., `timeout=30.0`) to avoid `ConnectTimeout` exceptions during slow or large-payload syncs.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
