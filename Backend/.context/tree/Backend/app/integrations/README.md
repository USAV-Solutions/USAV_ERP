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
- `ExternalOrder` now carries optional `customer_phone`, `customer_company`, and `customer_source`; adapters should fill these when payloads include them.
- `ExternalOrder` shipping contract now includes `ship_address_line3`; adapters that expose a third street line should populate it, while adapters without support should leave it `None`.

## Child Folders
- `amazon/`
- `ebay/`
- `ecwid/`
- `walmart/`
- `zoho/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
