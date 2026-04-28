# Backend\migrations\versions

## What This Folder Does
Concrete Alembic revision files; source of truth for schema transitions.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- In PostgreSQL, new enum values must be committed before they are used in the same migration (use Alembic autocommit blocks around `ALTER TYPE ... ADD VALUE`).
- Keep model/index names aligned with migration IDs; for `Customer.source`, both the ORM and migration define `ix_customer_source` and must stay in sync.
- Migration `0024` introduces nullable `platform_listing.variant_id` plus partial unique index behavior on `(platform, external_ref_id)`; guard against duplicate non-null refs before applying in production.
- Backfill migrations that bridge old/new matching columns (for example, `order_item.platform_listing_id`) should compare platform enums via `::text` when enum types differ across tables.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
