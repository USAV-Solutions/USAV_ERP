# Backend\app\integrations

## What This Folder Does
External system adapters and normalization clients (Amazon/eBay/Ecwid/Walmart/Zoho).

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Returning raw platform payloads instead of normalized dataclasses.
- Leaking secrets/tokens in logs.
- Inconsistent platform_name values causing sync mapping failures.

## Child Folders
- `amazon/`
- `ebay/`
- `ecwid/`
- `walmart/`
- `zoho/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
