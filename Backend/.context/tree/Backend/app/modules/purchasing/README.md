# Backend\app\modules\purchasing

## What This Folder Does
Purchase order domain: import pipelines, vendor workflows, receiving, matching, purchase-order/item mutation endpoints (including guarded deletes), and Zoho purchase-order-received-status delivery backfill.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Changing import-source behavior without updating schema enums and UI source selectors.
- Breaking source tagging used downstream in Zoho notes/reconciliation.
- Goodwill CSV imports are split by source (`goodwill_shipped` / `goodwill_open`) and map to different stored PO `source` values (`GOODWILL_SHIPPED` for shipped orders and `GOODWILL_PICKUP` for open orders); keep backend/frontend source lists aligned.
- Open-order Goodwill imports only ingest rows where `Status` is `View Order`; files missing the `Status` column are rejected for this import mode.
- Editing PO status transitions without test updates.
- Mixing dependency styles in route signatures; prefer `Annotated[..., Depends(...)]` and `Annotated[..., Query(...)]` for maintainable, consistent FastAPI typing.
- In Python signatures, non-default dependency params must come before optional/default query params to avoid `SyntaxError: parameter without a default follows parameter with a default`.
- Purchase-order deletes are blocked when any line item is already `RECEIVED`; frontend should surface API detail text for this guardrail.
- Purchase item `unit_price` now supports precision beyond 2 decimals; keep UI/editor inputs and import paths from coercing prices to cent precision when quantity-split totals require fractional cents.
- Purchase list endpoint supports approximate total search (`total_amount` with optional `total_amount_range`); frontend and backend must stay aligned on inclusive bounds (`total_amount - range` through `total_amount + range`).
- Delivery-status backfill (`POST /purchases/backfill-delivery-status`) scans Zoho purchase orders in the requested date window (defaults: `2026-01-01` through today) and marks local POs as `DELIVERED` only when Zoho `received_status` is `received`; it does not auto-downgrade orders with other statuses.

## Child Folders
- `schemas/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
