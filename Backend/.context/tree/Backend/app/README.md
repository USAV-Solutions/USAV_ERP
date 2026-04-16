# Backend\app

## What This Folder Does
Main FastAPI application package: routers, domain modules, integrations, models, repositories, and shared schemas.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.

## Child Folders
- `api/`
- `core/`
- `integrations/`
- `models/`
- `modules/`
- `repositories/`
- `schemas/`
- `tasks/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
