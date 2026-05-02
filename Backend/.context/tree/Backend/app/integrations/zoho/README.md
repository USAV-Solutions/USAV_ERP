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
- Purchase-order hash-match (`zoho_last_sync_hash`) does not mean Zoho billing is complete; when billing sync is enabled, bill/payment reconciliation must still run on unchanged PO payloads.
- Auto bill/payment sync eligibility includes all `EBAY_*` sources and `GOODWILL_SHIPPED`; keep this source-gate aligned with import/source mappings to avoid silent billing skips.
- `PurchaseOrder` Zoho billing state columns are deferred in ORM mapping (`zoho_bill_created`, `zoho_payment_created`, etc.). In async sync paths, explicitly `undefer(...)` these fields before reading them to avoid implicit lazy-load IO that raises `sqlalchemy.exc.MissingGreenlet`.
- Purchase-order outbound payload now includes `cf_source` mapping. Keep mapping aligned with script behavior (`EBAY_* -> Ebay`, `AMAZON_* -> Amazon`, `GOODWILL_SHIPPED` and `GOODWILL_PICKUP` -> `Goodwill`, `ALIEXPRESS_* -> AliExpress`, local pickup variants -> `Local Pickup`, fallback -> `Other`).
- Customer outbound payload now mirrors billing to shipping address and can include a contact source custom field via `zoho_contact_cf_source_api_name`/`zoho_contact_cf_source_id`; inbound mapper reads this value back into `Customer.source` when present.
- Customer outbound payload now forces tax preference to tax-exempt (`is_taxable=false`) and, when configured, includes `tax_exemption_id`/`tax_authority_id`. It also sends a primary `contact_persons` entry to keep Zoho UI email/phone fields populated for business contacts.
- Sales-order outbound payload uses `salesorder_number` (from `external_order_number` fallback `external_order_id`) and reserves `reference_number` for tracking (`Order.tracking_number`). Legacy duplicate detection still falls back to matching `reference_number == external_order_id` for older rows.
- Sales-order source is sent through SO custom fields (`api_name=cf_source`) using SO-specific dropdown mapping: `Ebay_Dragon`, `Ebay_Mekong`, `Ebay_USAV`, `ECWID`, `Amazon`, `Walmart`, fallback `Other`.
- Zoho can return code `15` for sales-order `shipping_address` length even after normal trimming; outbound sync now retries once without `shipping_address` when this exact validation fires so order sync can proceed.
- Sales-order outbound customer/address values are sourced from linked `Customer` records (not duplicated order snapshot columns). If customer address data is incomplete, Zoho shipping payload will also be incomplete.
- Sales-order outbound payload now sends `shipping_charge` from `Order.shipping_amount` for all sources. For `ECWID_API` orders, each line is forced to `tax_percentage=0` and order tax is sent as `adjustment` with `adjustment_description="Tax adjustment"`.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
