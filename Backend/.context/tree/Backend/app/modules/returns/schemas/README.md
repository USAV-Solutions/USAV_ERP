# Backend\app\modules\returns\schemas

## What This Folder Does
Defines Pydantic request/response schemas for Returns list/detail endpoints, marketplace manual sync endpoints, and Zoho Sales Return validation/sync endpoints.

## Typical Contents
- Dashboard row/detail serializers.
- Sync request, per-platform result, and sync-status response models.
- Zoho validation line blockers, single-record sync, range sync, and Zoho status response models.

## Common Pitfalls
- Keep frontend `frontend/src/types/returns.ts` aligned with these schemas.
- `summary_counts` is part of the paginated list response because the Returns page needs status cards without a second endpoint.
- Return list/detail responses now include `zoho_salesreturn_id`, `zoho_salesreturn_number`, `zoho_sync_status`, `zoho_sync_error`, and `zoho_synced_at`; frontend rows should not infer syncability without calling the Zoho validation endpoint.
- Zoho validation line responses expose both `zoho_item_id` and `zoho_salesorder_item_id`; Sales Return create payloads need both IDs.
