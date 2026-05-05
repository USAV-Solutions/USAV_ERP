# Backend\app\repositories\purchasing

## What This Folder Does
Purchase order and vendor repository/query logic.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Purchase-order total filtering now supports tolerance windows (`total_amount_range`) and must remain inclusive on both ends to match accountant search expectations.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
