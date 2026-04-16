# Backend\app\modules

## What This Folder Does
Domain modules grouping route + schema + service logic by business area.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.

## Child Folders
- `auth/`
- `inventory/`
- `orders/`
- `purchasing/`
- `sync/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
