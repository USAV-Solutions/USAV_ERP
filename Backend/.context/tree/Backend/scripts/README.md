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
- `zoho_sync_q1_pos_with_receives_and_bills.py` defaults to `2026-01-01..2026-03-31`, processes only local purchase orders with `zoho_sync_status=DIRTY`, enforces PO relink order (`zoho_id` first, then Zoho `reference_number == po_number`), then materializes bill-first/receive-second dependencies from `Backend/misc/Bill.csv` and `Backend/misc/Purchase_Receive.csv`.
- `zoho_sync_q1_pos_with_receives_and_bills.py` `--dry-run` prints per-PO planned resolver/receive/bill actions and does not write; apply mode is idempotent by existing Zoho receive/bill numbers.
- `zoho_sync_q1_pos_with_receives_and_bills.py` supports `--limit` and `--offset` so operators can test tiny batches (for example 2 POs) before full-quarter runs.
- `zoho_sync_q1_pos_with_receives_and_bills.py` writes a JSON failure report after every run (default: `Backend/scripts/zoho_sync_q1_pos_with_receives_and_bills_failures.json`, override with `--failure-log`) capturing PO upload, bill, and receive failures plus run summary.
- `zoho_sync_q1_pos_with_receives_and_bills.py` now enriches bill payloads with PO-linked `line_items` from the current Zoho PO response (required by Zoho) and retries once with stripped `location_id`/`branch_id` when Zoho returns `code:27523` location-lock errors.
- `zoho_sync_q1_pos_with_receives_and_bills.py` creates purchase receives via Inventory API with `purchaseorder_id` in query params (in addition to payload) to satisfy Zoho PO-association validation (`code:9`).
- In bill-first mode, `zoho_sync_q1_pos_with_receives_and_bills.py` enriches receive line items with `bill_line_item_id` by mapping bill response lines (`purchaseorder_item_id` -> bill `line_item_id`), enabling receives after bill creation on Zoho-locked PO items.
- `zoho_sync_q1_pos_with_receives_and_bills.py` prints `[bill-debug]` and `[receive-debug]` payload/response logs only when `--debug` is passed.
- `zoho_resolve_delivery.py` fetches Zoho POs from Jan 1 to May 1 2026, parses received dates from notes and terms using regex and dateutil, saves a CSV report to `scripts/zoho_delivery_report.csv`, and then iterates over valid entries to create bills and receives sequentially, enriching bills with PO lines and receives with bill lines mapping.
- `po_comparison_report.py` compares POs between the local DB and Zoho in a given date range (assumes GMT-8 timezone by casting DB `created_at` appropriately), identifying missing POs on either side and highlighting received POs on Zoho that are not marked DELIVERED in the local DB. Outputs report to `Backend/misc/`.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
