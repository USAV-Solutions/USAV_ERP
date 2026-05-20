# Backend\app\modules\purchasing\schemas

## What This Folder Does
Purchasing request/response and import schema definitions, including delivery-status backfill response payloads.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Keep API defaults/field names aligned with route behavior when adding operational backfill responses (for example, receive-date windows and processed-count fields).

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
