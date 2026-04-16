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

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
