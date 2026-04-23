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
- `PurchaseOrder` Zoho billing state columns are deferred in ORM mapping (`zoho_bill_created`, `zoho_payment_created`, etc.). In async sync paths, explicitly `undefer(...)` these fields before reading them to avoid implicit lazy-load IO that raises `sqlalchemy.exc.MissingGreenlet`.
- Purchase-order outbound payload now includes `cf_source` mapping. Keep mapping aligned with script behavior (`EBAY_* -> Ebay`, `AMAZON_* -> Amazon`, `GOODWILL_CSV` and `GOODWILL_PICKUP` -> `Goodwill`, `ALIEXPRESS_* -> AliExpress`, local pickup variants -> `Local Pickup`, fallback -> `Other`).

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
