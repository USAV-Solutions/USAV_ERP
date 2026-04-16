# Backend

## What This Folder Does
Top-level backend service workspace containing application code, DB migrations, scripts, and tests.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.

## Child Folders
- `app/`
- `migrations/`
- `misc/`
- `scripts/`
- `tests/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
