# Backend\migrations

## What This Folder Does
Alembic migration environment and revision history for database evolution.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Skipping data backfill for new required fields.
- Introducing irreversible enum changes without clear downgrade strategy.
- Not seeding required operational rows (for example, sync state rows).
- Revision `0025` creates a unique partial index on `platform_listing(platform, external_ref_id)`; legacy duplicates or blank-string refs must be normalized/deduped in-migration before index creation.

## Child Folders
- `versions/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
