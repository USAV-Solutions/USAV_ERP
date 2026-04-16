# Orders Domain Branch (Sales Orders)

## Scope
- `app/modules/orders/`
- `app/repositories/orders/`
- Related sync endpoints in `app/modules/sync/`

## What This Domain Does
- Imports/syncs sales orders from external sources
- Deduplicates orders by `(platform, external_order_id)`
- Auto-matches order items to internal variants via platform listings
- Supports manual match/confirm/reject workflows
- Tracks sync state and Zoho sync readiness/status

## Core Workflow Pattern
1. Build platform client(s)
2. Fetch external orders
3. Normalize to `ExternalOrder` / `ExternalOrderItem`
4. Ingest through `OrderSyncService`
5. Persist header/items + matching status + source metadata

## Strict Rules
- Keep `OrderPlatform` and platform mapping dictionaries synchronized.
- Ingestion source should be explicit (`*_API`, `CSV_GENERIC`, etc.) for traceability.
- New import flows should reuse `OrderSyncService` (do not duplicate ingest logic).
- Filter/sort additions in routes must be mirrored in repository and frontend API client.

## Naming Conventions
- Status enums are uppercase (`PENDING`, `MATCHED`, etc.).
- Sync-state platform keys are uppercase (`ECWID`, `EBAY_USAV`, etc.).
- Source labels are uppercase snake-like strings (`EBAY_USAV_API`, `CSV_GENERIC`).

## Common Pitfalls
- Adding a new platform but missing:
  - enum value
  - service mapping (`_PLATFORM_MAP`, `_ORDER_TO_ENTITY_PLATFORM`)
  - integration_state seed/migration
  - frontend platform labels/types
- Returning list responses without the new required fields (e.g., `source`).
- Introducing filters only in route layer but not repository query.

## Validation Checklist
- Sync/import endpoints work for single platform and bulk/all paths
- Dedupe counts and auto-match counts remain accurate
- List endpoint supports platform/status/item/source/date/zoho/sort/search combinations

