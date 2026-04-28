# Backend\app\core

## What This Folder Does
Core infrastructure configuration: environment settings, DB setup, and security helpers.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Zoho PO source sync can use optional `zoho_po_cf_source_id`; if unset, payload falls back to `api_name=cf_source`.
- Zoho contact source sync uses `zoho_contact_cf_source_api_name` (default `cf_source`) and optional `zoho_contact_cf_source_id`; mismatched API names silently drop custom field updates.
- `ENVIRONMENT=development` now forces `SEATALK_REDIRECT_URI` to `http://localhost:3636/auth/seatalk/callback` inside backend settings; non-local callbacks in `.env` are ignored in development mode.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
