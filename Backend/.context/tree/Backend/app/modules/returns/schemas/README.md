# Backend\app\modules\returns\schemas

## What This Folder Does
Defines Pydantic request/response schemas for Returns list/detail endpoints and manual sync endpoints.

## Typical Contents
- Dashboard row/detail serializers.
- Sync request, per-platform result, and sync-status response models.

## Common Pitfalls
- Keep frontend `frontend/src/types/returns.ts` aligned with these schemas.
- `summary_counts` is part of the paginated list response because the Returns page needs status cards without a second endpoint.
