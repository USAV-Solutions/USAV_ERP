# Inventory Domain Branch

## Scope
- `app/modules/inventory/`
- `app/repositories/inventory/`
- Inventory-facing models in `app/models/entities.py`

## What This Domain Does
- Manages catalog structures (families, identities, variants)
- Manages platform listings and listing sync state
- Handles inventory item lifecycle and lookups

## Core Rules
- Preserve SKU/identity invariants; avoid ad-hoc naming mutations in route handlers.
- Listing-related platform enums must stay aligned with integration + order matching flows.
- Variant/listing lookups are reused by order/purchase auto-match pipelines; do not break repository signatures lightly.

## Naming Conventions
- Platform/listing statuses are enum-based and uppercase.
- IDs are generally numeric DB PKs; external refs are strings.
- Search endpoints often use query params and lightweight response models.

## Common Pitfalls
- Forgetting to add new platform enum values (e.g., WALMART) to all layers.
- Breaking `PlatformListing` lookup semantics used by orders/purchasing matching.
- Mixing migration concerns into route logic when column availability differs by environment.

## Safe Change Pattern
- Extend enum -> add migration -> update schema/type docs -> update UI selectors.
- Validate that inventory changes do not regress order/purchase auto-matching.

