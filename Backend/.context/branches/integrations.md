# Integrations Branch

## Scope
- `app/integrations/`
- Platform adapters: Amazon, eBay, Ecwid, Walmart, Zoho
- `app/integrations/base.py`

## What This Layer Does
- Encapsulates external API mechanics (auth, request/response handling)
- Normalizes external payloads into internal dataclasses used by domains

## Strict Rules
- All platform clients should implement `BasePlatformClient` contract.
- Keep platform names stable and uppercase (`platform_name` property).
- External parsing should happen in client layer, not in route/service handlers.
- Log external API debug clearly, but never log secrets.

## Naming Conventions
- Normalized dataclasses:
  - `ExternalOrder`
  - `ExternalOrderItem`
  - `StockUpdate`
  - `StockUpdateResult`
- Client class names: `<Platform>Client`

## Common Pitfalls
- Returning platform-specific payload shape directly into services.
- Inconsistent `platform_name` values (breaks sync-state mapping).
- Implementing partial client methods without graceful fallback behavior.

## Extension Checklist (New Platform)
- Create `app/integrations/<platform>/client.py`
- Implement base interface methods
- Register in `app/integrations/__init__.py`
- Wire client creation in domain route/module
- Add enum/migration/type updates where needed

