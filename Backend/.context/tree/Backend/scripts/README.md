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

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
