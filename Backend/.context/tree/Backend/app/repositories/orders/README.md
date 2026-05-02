# Backend\app\repositories\orders

## What This Folder Does
Sales order repositories and sync-state persistence helpers.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- After migration `0028`, order search by customer must use relationship predicates (`Order.customer.has(...)`) instead of dropped `orders.customer_name` columns.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
