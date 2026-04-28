# Backend\app\models

## What This Folder Does
SQLAlchemy ORM entities and enums for inventory, orders, purchasing, users, and customer sync metadata, including listing-centric order matching links.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Adding enum values in Python without DB enum migration.
- Adding non-null columns without safe default/backfill.
- New purchase-order Zoho billing columns are intentionally deferred at ORM load time to keep legacy databases (without migration `0023`) from failing simple list/read queries.
- `Customer.source` is nullable and overwrite-oriented (latest source wins during ingestion); avoid adding uniqueness assumptions around this field.
- Changing constraints/index names without migration compatibility checks.
- `PlatformListing.variant_id` is nullable after migration `0024`; unresolved listings are valid and must not be treated as data corruption.
- `PlatformListing.external_ref_id` is now unique per platform only when non-null; do not repurpose `merchant_sku` as canonical listing identity.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
