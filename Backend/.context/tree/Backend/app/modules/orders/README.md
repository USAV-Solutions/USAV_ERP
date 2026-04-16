# Backend\app\modules\orders

## What This Folder Does
Sales orders domain: ingestion/import, matching, filtering, and order sync state.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Forgetting to align platform/source enums across model, schema, migration, and frontend types.
- Adding filters in route layer but not implementing repository query logic.
- Bypassing OrderSyncService ingestion path and breaking dedupe/matching consistency.

## Child Folders
- `schemas/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
