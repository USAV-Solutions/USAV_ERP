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

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
