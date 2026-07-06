# Backend\app\core

## What This Folder Does
Core infrastructure configuration: environment settings, DB setup, security helpers, and external utility integrations (e.g., Synology NAS WebAPI client and NVIDIA Locate Anything object counting).

## Typical Contents
- `synology.py`: Handles connection, authentication, and file upload via the Synology DSM FileStation WebAPI (with safe local disk fallback).
- `locate_anything.py`: Interfaces with the NVIDIA Locate Anything visual grounding NIM API for packaging box count checks (with offline mock fallback).
- Python modules, schemas, or support assets scoped to this domain.

## Common Pitfalls
- Synology upload: Requires `SYNOLOGY_NAS_IP`, `SYNOLOGY_NAS_PORT`, `SYNOLOGY_NAS_USER`, and `SYNOLOGY_NAS_PASSWORD` to upload scanned photos. If any are unset, it falls back to local disk storage (`static/photos/`) to avoid breaking local setups.
- NVIDIA Locate Anything: Requires `NVIDIA_API_KEY` to run box count validation. If unset, it falls back to a simulated mock object count.
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Zoho PO source sync can use optional `zoho_po_cf_source_id`; if unset, payload falls back to `api_name=cf_source`.
- Zoho contact source sync uses `zoho_contact_cf_source_api_name` (default `cf_source`) and optional `zoho_contact_cf_source_id`; mismatched API names silently drop custom field updates.
- Zoho contact tax-exempt sync can use optional `zoho_contact_tax_exemption_id` and `zoho_contact_tax_authority_id`; if your Zoho org requires these for tax-exempt contacts, leaving them blank may cause contact validation failures.
- `ENVIRONMENT=development` now forces `SEATALK_REDIRECT_URI` to `http://localhost:3636/auth/seatalk/callback` inside backend settings; non-local callbacks in `.env` are ignored in development mode.
- eBay listing publish now depends on per-store env defaults (`ebay_*_{mekong|usav|dragon}`): policy IDs, marketplace/country/currency, location/postal code, and `dispatch_time_max`; missing values will hard-fail publish validation.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
