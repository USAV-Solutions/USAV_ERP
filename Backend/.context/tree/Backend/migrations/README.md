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

## Child Folders
- `versions/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
