# Backend\app\modules\accounting

## What This Folder Does
Accounting API endpoints behind `ADMIN`/`ACCOUNTANT` access, including Purchase Order Reports data aggregation/report exports and bank statement conversion file processing.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Access is restricted to `ADMIN` and `ACCOUNTANT`; role wiring must remain aligned with auth token role values.
- Purchase Order report endpoint requires `start_date`, `end_date`, and valid `group_by` (`sku`, `week`, `month`, `quarter`, `year`, `source`, `vendor`).
- Export endpoint uses `file_type` (`csv` or `xlsx`) and returns attachment streams; keep filenames/content types aligned with client download logic.
- Bank conversion endpoint only accepts `.pdf` uploads and currently supports parser formats `boa_v1`, `boa_v2`, `boa_v3`, `amazon`, `apple`, and `chase`; `format_7` intentionally returns not implemented.
- Parser mismatch should return HTTP 400 with `Format does not match selected bank` so frontend can surface correct guidance.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
