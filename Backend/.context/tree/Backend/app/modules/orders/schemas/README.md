# Backend\app\modules\orders\schemas

## What This Folder Does
Sales orders request/response and sync/import schema contracts, including customer-only CSV imports.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Keep `SalesImportFileSource` and `SalesImportFileResponse` in sync with route behavior (for `SHIPSTATION_CUSTOMER_CSV`, customer counters are populated while order counters remain zero).
- `OrderDetail` continues to expose customer/shipping fields for API compatibility, but values are now derived from linked `Customer` data rather than persisted order snapshot columns.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
