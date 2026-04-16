# Backend\app\repositories

## What This Folder Does
Data access abstraction layer for all domains; isolates query logic from routes/services.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.

## Child Folders
- `inventory/`
- `orders/`
- `product/`
- `purchasing/`
- `user/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
