# Backend Architecture Map

## Purpose
USAV Inventory Backend is a FastAPI + SQLAlchemy service that manages:
- Product catalog and inventory
- External platform integrations (eBay, Ecwid, Walmart, Amazon, Zoho)
- Sales orders and purchase orders
- Sync workflows between internal records and external systems

This file is the **root node**. Read this first, then open only relevant branch docs.

## Top-Level Tree
```text
Backend/
├─ app/
│  ├─ main.py                  # FastAPI app bootstrapping + router mounting
│  ├─ api/                     # Shared API deps + top-level route composition
│  ├─ core/                    # Settings, DB session setup, security/jwt helpers
│  ├─ models/                  # SQLAlchemy ORM entities
│  ├─ repositories/            # Data access layer per domain
│  ├─ integrations/            # External API clients + normalization
│  ├─ modules/
│  │  ├─ auth/                 # Authentication endpoints + auth schemas
│  │  ├─ inventory/            # Catalog/listing/inventory workflows
│  │  ├─ orders/               # Sales order ingestion + matching + sync state
│  │  ├─ purchasing/           # PO imports, receiving, matching, vendor flows
│  │  └─ sync/                 # Outbound sync endpoints (Zoho force-sync, etc.)
│  ├─ schemas/                 # Shared/base schemas
│  └─ tasks/                   # Background/maintenance task logic
├─ migrations/                 # Alembic revisions
├─ scripts/                    # One-off operational scripts
├─ tests/                      # Integration + module tests
└─ .context/                   # Agent context docs (this folder)
```

## Read Path For Agents
1. Read this file.
2. Pick branches by task:
   - API/auth work: `branches/api-auth.md`
   - Inventory/catalog/listings: `branches/inventory-domain.md`
   - Sales orders: `branches/orders-domain.md`
   - Purchasing/PO: `branches/purchasing-domain.md`
   - Integrations/client behavior: `branches/integrations.md`
   - Schema/migration changes: `branches/data-model-migrations.md`
   - Tests/verification: `branches/testing-playbook.md`

## Global Guardrails
- Respect layering: `routes -> service/domain logic -> repository -> models`.
- Keep enums aligned across:
  - ORM models
  - Pydantic schemas
  - frontend TS types
  - Alembic enum migrations
- For new ingestion/import features, reuse existing normalization + ingestion pipelines (avoid duplicate logic).
- Prefer additive migrations and backward-compatible defaults when possible.
- Do not couple scripts with request-path code unless intentionally shared.

