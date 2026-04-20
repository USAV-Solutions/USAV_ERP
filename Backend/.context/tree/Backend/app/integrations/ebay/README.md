# Backend\app\integrations\ebay

## What This Folder Does
eBay integration client and API-specific transport/auth/order normalization behaviors.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Reintroducing duplicated hardcoded eBay timestamp formats; use `EBAY_ISO_DATE_FORMAT` in `client.py` for all eBay ISO datetime string generation.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
