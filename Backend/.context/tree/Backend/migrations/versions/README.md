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

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
