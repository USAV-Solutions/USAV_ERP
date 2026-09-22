# Backend\app\modules\inventory

## What This Folder Does
Inventory/catalog domain: items, variants, identities, listings, images, lookups, multi-channel knowledge graph topology, and AI-powered listing relationship matching (EXACT, BUNDLE, ACCESSORY, PART).

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Knowledge Graph endpoints (`/listings/graph/{variant_id}`, `/listings/suggest`, `/listings/lock-relationship`, `/listings/compare`) require authenticated user.
- For eBay endpoints to work properly, `ebay-accounts.json` must be present in the root of the `Backend` folder.

## Child Folders
- `routes/`
- `schemas/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
