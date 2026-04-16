# Purchasing Domain Branch

## Scope
- `app/modules/purchasing/`
- `app/repositories/purchasing/`
- `app/models/purchasing.py`

## What This Domain Does
- Manages purchase orders and vendors
- Imports from multiple source formats/APIs
- Supports item matching against internal variants
- Handles delivery/receiving and downstream Zoho sync concerns

## Core Rules
- Source-aware import behavior is first-class in this domain.
- File/API import source values drive both parsing and downstream source tagging.
- PO item matching state is meaningful for filtering and sync behavior; preserve status semantics.

## Naming Conventions
- `source` values use uppercase channel-like tags (`*_API`, `*_CSV`, `ZOHO_IMPORT`).
- Deliver/match/Zoho sync statuses are enum-backed and uppercase.

## Common Pitfalls
- Editing one source parser without updating shared import dispatch logic.
- Failing to propagate source metadata to records used by sync mapping/notes.
- Breaking filters (`item_match_status`, date range, source, sort) used by UI workflows.

## Reuse Guidance
- For new domain imports (e.g., sales-order parity), mirror purchasing patterns:
  - explicit source enum/request contracts
  - structured import responses
  - centralized dispatch by source

