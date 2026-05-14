# Backend\scripts

## What This Folder Does
One-off operational scripts for backfills, cleanup, reconciliation, and migrations support.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Reusing script-only assumptions in production request paths.
- Running destructive scripts without dry-run guardrails.
- Leaving script output formats undocumented for future operators.
- Zoho bill backfills can fail with `code:36510` when PO has un-billed purchase receives; retry with receive-linked bill lines (`receive_item_id`) instead of PO-only line mapping.
- Source backfill scripts should treat `GOODWILL_SHIPPED` as the canonical shipped Goodwill PO source value; normalize legacy shipped-source rows upstream before running source-based reconciliation.
- `zoho_po_resync_orchestrator.py` enforces explicit `--start-date/--end-date`; do not assume calendar-quarter defaults when running deletes or reconciliations.
- In orchestrator stages, write operations require `--apply`; dry-run remains default even for delete/reconcile flows.
- `zoho_po_resync_orchestrator.py` uses Zoho Inventory bill/payment endpoints (not Zoho Books), matching orgs without Books permissions.
- `zoho_po_resync_orchestrator.py` delete stage skips payments and uses CSV IDs in the provided date window, deleting purchase receives first and bills second; it attempts bulk-delete in chunks (`--delete-bulk-size`, default 200) with single-delete fallback if bulk endpoint behavior is unavailable.
- `zoho_po_resync_orchestrator.py` sync-apply stage now upserts each PO and then materializes receives/bills from CSV metadata (date, due_date, receive_number/bill_number, notes/reference) while building line_items from the current Zoho PO lines (CSV SKU/Product IDs are ignored); reruns are idempotent by existing receive/bill numbers.
- `zoho_sync_q1_pos_with_receives_and_bills.py` defaults to `2026-01-01..2026-03-31`, enforces PO relink order (`zoho_id` first, then Zoho `reference_number == po_number`), syncs the PO, then creates missing receives/bills from `Backend/misc/Purchase_Receive.csv` and `Backend/misc/Bill.csv` using current Zoho PO line items.
- `zoho_sync_q1_pos_with_receives_and_bills.py` `--dry-run` prints per-PO planned resolver/receive/bill actions and does not write; apply mode is idempotent by existing Zoho receive/bill numbers.
- `zoho_sync_q1_pos_with_receives_and_bills.py` supports `--limit` and `--offset` so operators can test tiny batches (for example 2 POs) before full-quarter runs.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
