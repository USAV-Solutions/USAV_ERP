# Backend\app\models

## What This Folder Does
SQLAlchemy ORM entities and enums for inventory, orders, purchasing, and users.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Adding enum values in Python without DB enum migration.
- Adding non-null columns without safe default/backfill.
- Changing constraints/index names without migration compatibility checks.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
