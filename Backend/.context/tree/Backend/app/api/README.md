# Backend\app\api

## What This Folder Does
API composition layer and shared dependency utilities for route-level auth and request handling.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Eagerly importing domain routers inside `app/api/__init__.py` can trigger circular imports when modules import `app.api.deps`; keep router wiring lazy via `get_api_router()`.

## Child Folders
- `routes/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
