# Backend\app\modules\sync

## What This Folder Does
Cross-domain sync endpoints and orchestration hooks (especially Zoho force-sync).

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Sales-order force sync returns `202` only after persisting `zoho_sync_status=QUEUED`; it is not a Zoho success result. Poll `POST /sync/orders/status` for final `SYNCED` or `ERROR` status.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
