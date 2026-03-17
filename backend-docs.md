# USAV Inventory Backend — Comprehensive Developer Documentation

---

## 1. BACKEND ARCHITECTURE & DATA FLOW

### Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| **Framework** | FastAPI | 0.128.0 |
| **Language** | Python | 3.12 |
| **Database** | PostgreSQL (async) | via asyncpg |
| **ORM** | SQLAlchemy 2.0 (async) | 2.0.46 |
| **Migrations** | Alembic | 1.18.1 |
| **Auth** | JWT (python-jose) + bcrypt (passlib) | — |
| **Validation** | Pydantic v2 + pydantic-settings | 2.12.5 |
| **HTTP Client** | httpx (async) | 0.28.1 |
| **Containerisation** | Docker (multi-stage) + Docker Compose | — |
| **Server** | Uvicorn (ASGI) | 0.40.0 |

### Core Responsibilities

This backend is a **RESTful API** implementing the **Hub & Spoke middleware architecture** for USAV product data. It serves as the **central authority** (the Hub) for:

1. **Product Catalog Management** — Two-layer product identification model (Engineering → Sales) with a structured SKU system (`{product_id}-{type}-{lci}-{color}-{condition}`).
2. **Inventory Tracking** — Physical unit-level stock management with serial numbers, location codes, cost basis, and status transitions.
3. **Multi-Platform Order Synchronisation** — Ingesting orders from Amazon, eBay (3 stores), and Ecwid via a "Safe Sync" state machine, with automatic SKU resolution and manual "Match & Learn" workflows.
4. **Zoho Inventory Bi-Directional Sync** — Two-way sync of items, contacts, and sales orders with echo-loop prevention through payload hashing and SQLAlchemy event listeners.
5. **User Management & Auth** — JWT-based authentication with role-based access control (ADMIN, WAREHOUSE_OP, SALES_REP, SYSTEM_BOT) and SeaTalk OAuth integration.

### Authentication

- **JWT Bearer Tokens** — Generated via `POST /api/v1/auth/token` (OAuth2-compatible form login).
- **Password hashing** — bcrypt via `passlib.context.CryptContext`.
- **Token claims** — `sub` (user ID), `role`, `exp`, `iat`, optional `username`.
- **Role-Based Access Control** — Enforced through FastAPI dependency injection. Pre-built dependencies: `CurrentUser`, `AdminUser`, `AdminOrSalesUser`, `AdminOrWarehouseUser`. Superusers bypass all role checks.
- **SeaTalk OAuth** — Alternative login flow using SeaTalk employee codes for first-party users (auto-provisions accounts on first login).

### Routing Architecture

```
app = FastAPI(lifespan=lifespan)

app.include_router(api_router,          prefix="/api/v1")     # Auth + Inventory
app.include_router(orders_router,       prefix="/api/v1")     # Orders module
app.include_router(sync_router,         prefix="/api/v1")     # Manual Zoho sync
app.include_router(zoho_webhooks_router)                      # Zoho webhooks (no prefix)
```

All authenticated routes use the `OAuth2PasswordBearer` scheme pointing to `/api/v1/auth/token`.

### Database Interaction Pattern

```
Request → FastAPI Route → Depends(get_db) → AsyncSession
                        → Depends(get_*_repo) → Repository(session)
                        → Repository method → SQLAlchemy query → PostgreSQL
                        → auto-commit on success / auto-rollback on exception
```

- Sessions are managed via `async_session_factory` and `get_db()` dependency.
- Connection pooling: configurable `pool_size` (default 5) + `max_overflow` (default 10), with `pool_pre_ping` and 1-hour recycle.
- The `BaseRepository` generic class provides CRUD, pagination, count, and multi-delete operations inherited by all domain repositories.
- Docker Compose defaults in this project currently disable automatic Zoho inbound/outbound sync loops via `ZOHO_AUTO_OUTBOUND_SYNC_ENABLED=false` and `ZOHO_AUTO_INBOUND_SYNC_ENABLED=false`.

---

## 2. DIRECTORY STRUCTURE

```
Backend/
├── Dockerfile                         # Multi-stage Docker build (Python 3.12-slim)
├── alembic.ini                        # Alembic migration configuration
├── requirements.txt                   # Pinned Python dependencies
├── TESTING.md                         # Testing guide
├── Inventory_API_Documentation.md     # Legacy API docs
│
├── app/
│   ├── main.py                        # FastAPI app factory, lifespan, router mounting
│   │
│   ├── core/
│   │   ├── config.py                  # Settings via pydantic-settings (.env)
│   │   ├── database.py                # Async SQLAlchemy engine, session factory, Base
│   │   └── security.py               # JWT creation/verification, bcrypt hashing
│   │
│   ├── api/
│   │   ├── __init__.py                # Main API router aggregator
│   │   ├── deps.py                    # Auth dependencies (get_current_user, RBAC)
│   │   └── routes/
│   │       ├── __init__.py            # Deprecated stub (routes moved to modules)
│   │       └── auth.py               # Legacy auth routes (now superseded by modules.auth)
│   │
│   ├── models/
│   │   ├── __init__.py                # Central model exports
│   │   ├── entities.py                # Core domain models (Product*, Inventory*, Customer)
│   │   └── user.py                    # User model with RBAC roles
│   │
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── __init__.py            # Exports auth_router
│   │   │   ├── routes.py             # Auth endpoints (login, SeaTalk OAuth, user CRUD)
│   │   │   └── schemas.py            # Token, User, SeaTalk, PaginatedResponse schemas
│   │   │
│   │   ├── inventory/
│   │   │   ├── __init__.py            # Module init
│   │   │   ├── models.py             # Re-exports from entities.py
│   │   │   ├── routes/
│   │   │   │   ├── __init__.py        # Router aggregator (12 sub-routers)
│   │   │   │   ├── families.py       # Product Family CRUD
│   │   │   │   ├── identities.py     # Product Identity CRUD + UPIS-H generation
│   │   │   │   ├── variants.py       # Product Variant CRUD + SKU generation
│   │   │   │   ├── bundles.py        # Bundle Component (BOM) management
│   │   │   │   ├── listings.py       # Platform Listing CRUD + sync status
│   │   │   │   ├── inventory.py      # Physical inventory management
│   │   │   │   ├── images.py         # Product image metadata + upload/delete + thumbnail backfill
│   │   │   │   ├── lookups.py        # Brand, Color, Condition, LCI routers
│   │   │   │   └── zoho.py           # Zoho sync operations (single/bulk/readiness)
│   │   │   └── schemas/
│   │   │       ├── __init__.py        # Central schema exports (60+ classes)
│   │   │       ├── bundles.py        # BundleComponent schemas
│   │   │       ├── families.py       # ProductFamily schemas
│   │   │       ├── identities.py     # ProductIdentity schemas
│   │   │       ├── variants.py       # ProductVariant schemas
│   │   │       ├── inventory.py      # InventoryItem + warehouse ops schemas
│   │   │       ├── listings.py       # PlatformListing schemas
│   │   │       ├── lookups.py        # Lookup table schemas (Brand, Color, etc.)
│   │   │       ├── pagination.py     # Generic PaginatedResponse
│   │   │       └── zoho.py           # Zoho sync request/response schemas
│   │   │
│   │   ├── orders/
│   │   │   ├── __init__.py            # Module docstring
│   │   │   ├── models.py             # Order, OrderItem, IntegrationState models
│   │   │   ├── routes.py             # Order CRUD, sync triggers, SKU resolution
│   │   │   ├── service.py            # OrderSyncService ("Safe Sync" engine)
│   │   │   ├── dependencies.py       # DI factories for repos + service
│   │   │   └── schemas/
│   │   │       ├── __init__.py        # Schema exports
│   │   │       ├── orders.py         # Order/OrderItem CRUD + match schemas
│   │   │       └── sync.py           # IntegrationState + SyncRequest/Response
│   │   │
│   │   ├── purchasing/
│   │   │   ├── __init__.py            # Module exports
│   │   │   ├── routes.py              # Vendor, purchase order, item match/delete/import endpoints
│   │   │   ├── service.py             # Purchase-item matching + receiving domain logic
│   │   │   ├── dependencies.py        # DI factories for purchasing repositories/service
│   │   │   └── schemas/
│   │   │       ├── __init__.py        # Schema exports
│   │   │       └── purchasing.py      # Vendor/PO/item request-response schemas
│   │   │
│   │   └── sync/
│   │       ├── __init__.py            # Module docstring
│   │       └── endpoints.py          # Manual Zoho force-sync (variant/order/customer)
│   │
│   ├── integrations/
│   │   ├── __init__.py                # Factory registration for all platform clients
│   │   ├── base.py                    # Abstract BasePlatformClient + ExternalOrder DTOs
│   │   ├── amazon/
│   │   │   ├── __init__.py
│   │   │   └── client.py             # Amazon SP-API client (skeleton)
│   │   ├── ebay/
│   │   │   ├── __init__.py
│   │   │   └── client.py             # eBay Trading/Fulfillment API client (full impl.)
│   │   ├── ecwid/
│   │   │   ├── __init__.py
│   │   │   └── client.py             # Ecwid API client (full implementation)
│   │   └── zoho/
│   │       ├── __init__.py
│   │       ├── client.py             # Zoho Inventory/Books API client
│   │       ├── sync_engine.py        # Two-way sync engine + SQLAlchemy listeners
│   │       ├── webhooks.py           # Webhook receiver endpoint + handler registry
│   │       └── security.py           # Payload hash generation (echo-loop prevention)
│   │
│   ├── repositories/
│   │   ├── __init__.py                # Central repository exports
│   │   ├── base.py                    # Generic BaseRepository[T] (CRUD + pagination)
│   │   ├── user/
│   │   │   └── __init__.py            # UserRepository
│   │   ├── product/
│   │   │   └── __init__.py            # ProductFamily/Identity/VariantRepository
│   │   ├── inventory/
│   │   │   └── __init__.py            # BundleComponent/PlatformListing repos
│   │   ├── purchasing/
│   │   │   ├── __init__.py            # Vendor/PurchaseOrder/PurchaseOrderItem repos
│   │   │   └── purchase_repository.py # Purchasing repository implementations
│   │   └── orders/
│   │       ├── __init__.py            # Export aggregation
│   │       ├── order_repository.py   # OrderRepository + OrderItemRepository
│   │       └── sync_repository.py    # SyncRepository (IntegrationState ops)
│   │
│   ├── schemas/
│   │   ├── __init__.py                # Re-exports from auth + inventory schemas
│   │   └── auth.py                    # Legacy auth schemas (now in modules/auth)
│   │
│   └── tasks/
│       ├── __init__.py
│       └── reconciliation.py          # Nightly Zoho reconciliation task
│
├── migrations/
│   ├── env.py                         # Alembic environment config
│   └── versions/
│       ├── 20260126_..._0001_initial_schema.py
│       ├── 0002_add_users.py
│       ├── 20260129_..._0003_add_lookup_tables.py
│       ├── 20260203_..._0004_add_seatalk_id.py
│       ├── 20260205_..._0005_add_orders.py
│       ├── 20260210_..._0006_add_integration_state.py
│       ├── 20260224_..._0007_add_variant_thumbnail_url.py
│       ├── 20260225_..._0008_add_variant_name.py
│       ├── 20260226_..._0009_add_customer_and_zoho_sync.py
│       ├── 20260303_..._0010_rename_order_table.py
│       ├── 20260307_..._0011_add_order_zoho_sync_status.py
│       ├── 20260310_..._0012_add_purchasing_module.py
│       └── 20260311_..._0013_add_shipping_status.py
│
├── scripts/
│   ├── backfill_variant_name_from_listings.py   # Populate variant_name from listings
│   ├── create_admin_user.sql                    # SQL to seed admin user
│   ├── generate_hash.py                         # bcrypt password hash utility
│   ├── import_csv_to_database.py               # CSV→API product import pipeline
│   └── test_api_manual.py                       # Manual API smoke tests
│
└── tests/
    ├── conftest.py                    # pytest fixtures (SQLite in-memory DB)
    ├── test_api.py                    # Comprehensive API endpoint test suite
    ├── integrations/
    │   └── test_parsers.py            # eBay/Ecwid JSON→ExternalOrder parser tests
    └── modules/
        └── orders/
            └── test_sync_service.py   # OrderSyncService unit tests (mocked repos)
```

---

## 3. FILE-BY-FILE DOCUMENTATION

---

### CORE APPLICATION

---

### `main.py` (Path: `app/main.py`)

* **Purpose:** FastAPI application factory — creates the app instance, configures middleware, registers lifespan events, mounts all routers, and defines health-check endpoints.
* **Dependencies & Links:**
  - Internal: `app.api` (api_router), `app.core.config` (settings), `app.core.database` (engine, close_db), `app.modules.orders.routes` (orders_router), `app.modules.sync.endpoints` (sync_router), `app.integrations.zoho.webhooks` (webhook router + handler registration), `app.integrations.zoho.sync_engine` (inbound processors + listener registration).
  - External: `fastapi`, `CORSMiddleware`.
* **Mechanism / Core Logic:**
  - **Lifespan handler** — On startup: logs config, calls `register_sync_listeners()` to attach SQLAlchemy event hooks, and registers 6 Zoho webhook handlers (item.created/updated, contact.created/updated, salesorder.created/updated). On shutdown: closes DB connections via `close_db()`.
  - **CORS** — Allows configured origins with credentials, all methods, and all headers.
  - **Global exception handler** — Catches unhandled exceptions and returns 500 with sanitised error messages (detailed in debug mode only).
  - **Health endpoints** — `GET /health` (simple JSON status), `GET /health/db` (tests DB connectivity with `SELECT 1`).
  - **Root endpoint** — `GET /` returns app name, version, documentation links.
  - **Router mounting** — `api_router` (auth + inventory) under `/api/v1`, `orders_router` under `/api/v1`, `sync_router` under `/api/v1`, `zoho_webhooks_router` at root level.
  - **Dev server** — `uvicorn` entry point on port 8080 with reload in debug mode.

---

### `config.py` (Path: `app/core/config.py`)

* **Purpose:** Centralised application configuration using `pydantic-settings`. All settings are loaded from environment variables with `.env` file fallback.
* **Dependencies & Links:**
  - External: `pydantic-settings.BaseSettings`, `pydantic.computed_field`.
  - Consumed by: virtually every module in the application.
* **Mechanism / Core Logic:**
  - `Settings(BaseSettings)` — Single dataclass-like config object with ~50 fields organised into sections:
    - **Application:** `app_name`, `app_version`, `debug`, `environment` (dev/staging/prod).
    - **Database:** `db_host`, `db_port`, `db_user`, `db_pass`, `db_name`, pool settings.
    - **API:** `api_prefix` (`/api/v1`), `cors_origins`.
    - **Auth:** `secret_key`, `algorithm` (HS256), `access_token_expire_minutes` (24h).
    - **SeaTalk OAuth:** `seatalk_app_id`, `seatalk_app_secret`, `seatalk_redirect_uri`.
    - **Zoho:** Client ID/secret, refresh token, org ID, API base URLs (Inventory + Books).
    - **Amazon SP-API:** Refresh token, client ID/secret, marketplace ID (default US).
    - **eBay:** Shared app ID/cert ID + per-store refresh tokens (Mekong, USAV, Dragon).
    - **Ecwid:** Store ID, secret, API base URL.
    - **Walmart:** Client ID/secret, API base URL (placeholder).
    - **Images:** `product_images_path` for Nginx-served product images.
  - **Computed fields:** `database_url` (asyncpg), `database_url_sync` (psycopg2 for Alembic).
  - **Caching:** `get_settings()` uses `@lru_cache` to ensure a single instance.

---

### `database.py` (Path: `app/core/database.py`)

* **Purpose:** Async SQLAlchemy engine, session factory, and declarative base configuration.
* **Dependencies & Links:**
  - Internal: `app.core.config` (settings for connection URL and pool params).
  - External: `sqlalchemy.ext.asyncio` (create_async_engine, AsyncSession, async_sessionmaker).
  - Consumed by: `app.api.deps.get_db`, all repositories, `main.py` (engine for health check, close_db).
* **Mechanism / Core Logic:**
  - `engine` — `create_async_engine` with asyncpg driver, connection pooling (configurable size/overflow), `pool_pre_ping=True`, 1-hour `pool_recycle`.
  - `async_session_factory` — `async_sessionmaker` bound to engine, `expire_on_commit=False`, no auto-flush/auto-commit.
  - `Base` — `declarative_base()` used by all SQLAlchemy models.
  - `get_db()` — Async generator dependency: yields session, commits on success, rolls back on exception, always closes.
  - `init_db()` — Creates all tables from metadata (dev/test only).
  - `close_db()` — Disposes engine (called at app shutdown).
  - Debug mode: optionally logs SQL queries via SQLAlchemy engine logger.

---

### `security.py` (Path: `app/core/security.py`)

* **Purpose:** Security utilities for password hashing and JWT token management.
* **Dependencies & Links:**
  - Internal: `app.core.config` (settings for secret_key, algorithm, token expiry).
  - External: `python-jose` (jwt), `passlib` (CryptContext with bcrypt).
  - Consumed by: `app.api.deps` (token validation), `app.modules.auth.routes` (login, password change).
* **Mechanism / Core Logic:**
  - `pwd_context` — bcrypt-based `CryptContext`.
  - `verify_password(plain, hashed)` — Verifies password against bcrypt hash.
  - `get_password_hash(password)` — Returns bcrypt hash of plaintext password.
  - `create_access_token(subject, role, expires_delta, extra_data)` — Builds JWT with claims `sub`, `role`, `exp`, `iat` plus optional extras, signed with HS256.
  - `decode_access_token(token)` — Decodes and validates JWT; returns payload dict or `None` on `JWTError`.

---

### `deps.py` (Path: `app/api/deps.py`)

* **Purpose:** FastAPI dependency injection functions for authentication and role-based access control.
* **Dependencies & Links:**
  - Internal: `app.core.database.get_db`, `app.core.security.decode_access_token`, `app.models` (User, UserRole).
  - External: `fastapi.security.OAuth2PasswordBearer`.
  - Consumed by: all authenticated route handlers across modules.
* **Mechanism / Core Logic:**
  - `oauth2_scheme` — `OAuth2PasswordBearer` pointing to `/api/v1/auth/token`, `auto_error=False`.
  - `get_current_user(token, db)` — Extracts user from JWT: decodes token → fetches user by ID from DB → validates active status → returns `User` ORM instance or raises 401/403.
  - `get_current_user_optional(token, db)` — Returns `None` for unauthenticated requests instead of raising.
  - `require_roles(*allowed_roles)` — Factory function returning a dependency that checks `current_user.role` against allowed roles. Superusers bypass.
  - **Pre-built role checkers:**
    - `require_admin` — ADMIN only.
    - `require_admin_or_sales` — ADMIN or SALES_REP.
    - `require_admin_or_warehouse` — ADMIN or WAREHOUSE_OP.
  - **Type aliases:** `CurrentUser`, `OptionalUser`, `AdminUser`, `AdminOrSalesUser`, `AdminOrWarehouseUser` — annotated types for clean route signatures.

---

### `__init__.py` (Path: `app/api/__init__.py`)

* **Purpose:** Main API router aggregator that combines all domain routers into a single `api_router`.
* **Dependencies & Links:**
  - Internal: `app.modules.auth` (auth_router), `app.modules.inventory.routes` (12 sub-routers: families, identities, variants, bundles, listings, inventory, images, zoho, brand, color, condition, lci).
* **Mechanism / Core Logic:**
  - Creates an `APIRouter()` instance and includes 13 sub-routers via `include_router()`.
  - Exported as `api_router` and mounted in `main.py` under `/api/v1`.

---

### `__init__.py` (Path: `app/api/routes/__init__.py`)

* **Purpose:** Deprecated routes module stub. Contains a docstring indicating all routes have been migrated to the `app.modules.*` package.
* **Dependencies & Links:** None.
* **Mechanism / Core Logic:** Exports an empty `__all__` list.

---

### `auth.py` (Path: `app/api/routes/auth.py`)

* **Purpose:** Legacy authentication route definitions. Superseded by `app.modules.auth.routes` but retained for reference.
* **Dependencies & Links:**
  - Internal: `app.api.deps`, `app.core.config`, `app.core.security`, `app.repositories.user`, `app.schemas`.
  - External: `httpx`, `fastapi`.
* **Mechanism / Core Logic:** Contains the original implementations of `/auth/token`, `/auth/me`, `/auth/me/change-password`, SeaTalk OAuth, and user management endpoints — identical in structure to the module-based replacements.

---

### MODELS

---

### `__init__.py` (Path: `app/models/__init__.py`)

* **Purpose:** Central export point for all SQLAlchemy models and enums. Imports from `entities.py`, `user.py`, and `modules.orders.models`.
* **Dependencies & Links:** Re-exports 30+ classes including all entity models, order models, enums, and the User model.
* **Mechanism / Core Logic:** Try/except blocks around imports with error logging for debugging import failures during app startup.

---

### `entities.py` (Path: `app/models/entities.py`)

* **Purpose:** Core SQLAlchemy ORM models implementing the USAV Two-Layer Identification Model and supporting domain tables.
* **Dependencies & Links:**
  - Internal: `app.core.database.Base`.
  - External: SQLAlchemy (full declarative mapping with PostgreSQL JSONB dialect).
  - Referenced by: all repositories, route handlers, sync engine, order service.
* **Mechanism / Core Logic:**

  **Enums (7):**
  - `IdentityType` — Product, B (Bundle), P (Part), K (Kit).
  - `PhysicalClass` — E (Electronics), C (Cover/Case), P (Peripheral), S (Speaker), W (Wire/Cable), A (Accessory).
  - `ConditionCode` — N (New), R (Refurbished); NULL = Used.
  - `ZohoSyncStatus` — PENDING, SYNCED, ERROR, DIRTY.
  - `PlatformSyncStatus` — PENDING, SYNCED, ERROR.
  - `InventoryStatus` — AVAILABLE, SOLD, RESERVED, RMA, DAMAGED.
  - `BundleRole` — Primary, Accessory, Satellite.
  - `Platform` — AMAZON, EBAY_MEKONG, EBAY_USAV, EBAY_DRAGON, ECWID.

  **Mixins (2):**
  - `TimestampMixin` — `created_at` + `updated_at` with server defaults and `onupdate`.
  - `ZohoSyncMixin` — `zoho_id`, `zoho_last_sync_hash`, `zoho_last_synced_at`, `zoho_sync_error` + transient `_updated_by_sync` flag for echo-loop prevention.

  **Lookup Tables (4):**
  - `Brand` — `id`, `name` (unique). Brand/manufacturer registry.
  - `Color` — `id`, `name`, `code` (2-char unique). Color index.
  - `Condition` — `id`, `name`, `code` (1-char unique). Condition index.
  - `LCIDefinition` — `id`, `product_id` (FK→ProductFamily), `lci_index` (1-99), `component_name`. Maps component indexes to names per family.

  **Core Product Tables (3):**
  - `ProductFamily` — PK: `product_id` (5-digit ECWID ID). Fields: `base_name`, `description`, `brand_id` (FK), dimensions (L×W×H), `weight`, `kit_included_products`. Relationships: `brand`, `identities` (cascade), `lci_definitions` (cascade).
  - `ProductIdentity` — PK: `id`. Fields: `product_id` (FK→Family), `type` (IdentityType enum), `lci` (Part only), `physical_class`, `generated_upis_h` (unique computed string like `00845-P-1`), `hex_signature` (immutable 32-bit HEX). Constraints: LCI required for Parts, null for others; unique per family+type+lci. Relationships: `family`, `variants` (cascade), `bundle_children`/`bundle_parents`.
  - `ProductVariant` — PK: `id`. Fields: `identity_id` (FK), `color_code`, `condition_code`, `full_sku` (unique, e.g. `00845-P-1-WY-N`), `variant_name`, `zoho_item_id`, `thumbnail_url`, `zoho_sync_status`, `zoho_last_synced_at`, `is_active`, `zoho_last_sync_hash`, `zoho_sync_error`. Relationships: `identity`, `listings` (cascade), `inventory_items` (cascade). Unique constraint on identity+color+condition.

  **Composition Tables (1):**
  - `BundleComponent` — PK: `id`. Fields: `parent_identity_id` (FK→Identity), `child_identity_id` (FK→Identity), `quantity_required`, `role` (BundleRole). Constraints: no self-reference, unique parent+child, positive quantity. Relationships: `parent`, `child`.

  **External Sync Tables (1):**
  - `PlatformListing` — PK: `id`. Fields: `variant_id` (FK), `platform` (Platform enum), `external_ref_id`, `listed_name`, `listed_description`, `listing_price`, `sync_status`, `last_synced_at`, `sync_error_message`, `platform_metadata` (JSONB). Unique per variant+platform. Relationships: `variant`.

  **Inventory Tables (1):**
  - `InventoryItem` — PK: `id`. Fields: `serial_number` (unique), `variant_id` (FK), `status` (InventoryStatus), `location_code`, `cost_basis` (≥0), `notes`, `received_at`, `sold_at`. Composite index on variant+status. Relationship: `variant`.

  **Customer (1):**
  - `Customer` — PK: `id`. Uses `ZohoSyncMixin` + `TimestampMixin`. Fields: `name`, `email`, `phone`, `company_name`, address fields (line1/2, city, state, postal_code, country), `is_active`. Relationship: `orders`.

---

### `user.py` (Path: `app/models/user.py`)

* **Purpose:** SQLAlchemy model for user accounts with role-based access control.
* **Dependencies & Links:**
  - Internal: `app.core.database.Base`.
  - Referenced by: `app.api.deps`, `app.modules.auth`, `app.repositories.user`.
* **Mechanism / Core Logic:**
  - `UserRole` enum — ADMIN (full access), WAREHOUSE_OP (inventory operations), SALES_REP (pricing/descriptions), SYSTEM_BOT (sync worker only).
  - `User` model — Table `users`. Fields: `id`, `username` (unique, indexed), `email`, `seatalk_id` (unique, indexed), `hashed_password`, `full_name`, `role` (default WAREHOUSE_OP), `is_active`, `is_superuser`, `last_login`, `created_at`, `updated_at`. Indexed on `role` and `is_active`.

---

### MODULES

---

### AUTH MODULE

---

### `__init__.py` (Path: `app/modules/auth/__init__.py`)

* **Purpose:** Auth module package initializer. Exports `auth_router`.
* **Dependencies & Links:** `app.modules.auth.routes`.
* **Mechanism / Core Logic:** Single import + export.

---

### `routes.py` (Path: `app/modules/auth/routes.py`)

* **Purpose:** Authentication and user management API endpoints.
* **Dependencies & Links:**
  - Internal: `app.api.deps` (AdminUser, CurrentUser), `app.core.config`, `app.core.security`, `app.repositories.user.UserRepository`, `app.modules.auth.schemas`.
  - External: `httpx` (for SeaTalk API calls), `fastapi`.
* **Mechanism / Core Logic:**

  **Authentication Endpoints:**
  - `POST /auth/token` — OAuth2 form login. Validates username/password, updates `last_login`, returns JWT `Token`.
  - `GET /auth/me` — Returns current user info as `UserResponse`.
  - `POST /auth/me/change-password` — Verifies current password, updates hash. Accepts `PasswordChange` body.

  **SeaTalk OAuth Endpoints:**
  - Uses internal `_seatalk_token_cache` for app access token caching.
  - `_get_seatalk_app_token()` — Fetches/caches SeaTalk app access token.
  - `_generate_unique_username()` — Generates unique usernames from email/name/seatalk_id with 4-strategy fallback and collision avoidance.
  - SeaTalk callback endpoint — Exchanges auth code for employee info, auto-provisions user on first login (SALES_REP role), returns JWT.

  **User Management (Admin-Only):**
  - `GET /auth/users` — Paginated user list with role and active filters.
  - `POST /auth/users` — Create user (validates unique username/email, bcrypt-hashes password).
  - `GET /auth/users/{id}` — Get user by ID.
  - `PATCH /auth/users/{id}` — Update user fields (re-hashes password if changed).
  - `DELETE /auth/users/{id}` — Delete user (prevents self-deletion).

---

### `schemas.py` (Path: `app/modules/auth/schemas.py`)

* **Purpose:** Pydantic v2 schemas for authentication, users, and SeaTalk OAuth.
* **Dependencies & Links:**
  - Internal: `app.models.UserRole`.
  - External: `pydantic` (BaseModel, ConfigDict, Field, field_validator).
* **Mechanism / Core Logic:**
  - `BaseSchema` — Config: `from_attributes=True`, `str_strip_whitespace=True`, `use_enum_values=True`.
  - **Token schemas:** `Token` (access_token + token_type), `TokenData` (decoded claims).
  - **User schemas:** `UserBase` (username pattern `^[a-zA-Z0-9_.]+$`, 3-50 chars), `UserCreate` (password ≥8 chars with validator), `UserUpdate` (all optional), `UserResponse` (excludes password), `UserInDB` (internal, includes hashed_password).
  - **Login schemas:** `LoginRequest`, `PasswordChange` (with `new_password_confirm` match validator).
  - **SeaTalk schemas:** `SeaTalkEmployee`, `SeaTalkAppTokenResponse`, `SeaTalkCodeResponse`, `SeaTalkCallbackRequest`.
  - **Pagination:** `PaginatedResponse` — generic wrapper with `total`, `skip`, `limit`, `items`.

---

### INVENTORY MODULE

---

### `__init__.py` (Path: `app/modules/inventory/__init__.py`)

* **Purpose:** Inventory module package init. Documents module scope (Families, Identities, Variants, Bundles, Listings, Inventory Items).
* **Dependencies & Links:** `app.modules.inventory.routes`, `app.modules.inventory.schemas`.
* **Mechanism / Core Logic:** Exports `routes` and `schemas` sub-modules.

---

### `models.py` (Path: `app/modules/inventory/models.py`)

* **Purpose:** Re-exports all inventory-related models and enums from `app.models.entities` to provide a module-local namespace.
* **Dependencies & Links:** `app.models.entities` (18 classes).
* **Mechanism / Core Logic:** Pure re-export with `__all__` listing.

---

### `__init__.py` (Path: `app/modules/inventory/routes/__init__.py`)

* **Purpose:** Aggregates 12 sub-routers into a combined `inventory_module_router` and exports individual routers for the API aggregator.
* **Dependencies & Links:**
  - Internal: `bundles.py`, `families.py`, `identities.py`, `variants.py`, `listings.py`, `inventory.py`, `images.py`, `lookups.py`, `zoho.py`.
* **Mechanism / Core Logic:** Each sub-module defines its own `APIRouter` with a prefix and tag. This file imports and re-exports all 12 routers (including 4 lookup routers from `lookups.py`).

---

### `families.py` (Path: `app/modules/inventory/routes/families.py`)

* **Purpose:** Product Family CRUD API endpoints.
* **Dependencies & Links:**
  - Internal: `app.repositories.product.ProductFamilyRepository`, inventory schemas.
  - External: `fastapi`.
* **Mechanism / Core Logic:**
  - `GET /families` — Paginated list with optional name search (case-insensitive).
  - `POST /families` — Creates family. Auto-generates `product_id` by finding max existing ID + 1 if not provided.
  - `GET /families/{product_id}` — Returns family with loaded identities.
  - `PUT /families/{product_id}` / `PATCH /families/{product_id}` — Update family fields.
  - `DELETE /families/{product_id}` — Cascade delete (removes all child identities/variants/etc.).

---

### `identities.py` (Path: `app/modules/inventory/routes/identities.py`)

* **Purpose:** Product Identity (Layer 1) CRUD with automatic UPIS-H string and hex signature generation.
* **Dependencies & Links:**
  - Internal: `app.repositories.product` (ProductFamilyRepository, ProductIdentityRepository), `app.models.entities.IdentityType`, inventory schemas.
* **Mechanism / Core Logic:**
  - `GET /identities` — List with optional `product_id` filter.
  - `POST /identities` — Validates family exists; for type=P, validates LCI is provided; generates `generated_upis_h` string (e.g. `00845-P-1`) and `hex_signature` (CRC32 of UPIS-H).
  - `GET /identities/{id}` — Returns identity with loaded variants.
  - `GET /identities/upis/{upis_h}` — Lookup by UPIS-H string.
  - `PUT/PATCH /identities/{id}` — Only `physical_class` is updatable after creation (identity is quasi-immutable).
  - `DELETE /identities/{id}` — Cascade delete.

---

### `variants.py` (Path: `app/modules/inventory/routes/variants.py`)

* **Purpose:** Product Variant (Layer 2) CRUD with automatic full SKU generation and soft-delete archival semantics.
* **Dependencies & Links:**
  - Internal: `app.repositories.product` (ProductIdentityRepository, ProductVariantRepository), `app.models.entities.ZohoSyncStatus`, inventory schemas.
* **Mechanism / Core Logic:**
  - `GET /variants/search` — Typeahead search by product name or SKU substring.
  - `GET /variants` — List with optional filters: `identity_id`, `is_active`, `zoho_sync_status`.
  - `POST /variants` — Validates identity exists; auto-generates `full_sku` from identity's UPIS-H + color + condition (e.g. `00845-P-1-WY-N`). Sets `zoho_sync_status=PENDING`.
  - `GET /variants/{id}` — Returns variant with loaded platform listings.
  - `GET /variants/sku/{full_sku}` — SKU-based lookup.
  - `PUT/PATCH /variants/{id}` — Updates mutable variant fields (`variant_name`, `color_code`, `condition_code`, `is_active`). If color/condition changes, the API validates identity-level uniqueness and recomputes `full_sku`.
  - Local variant edits mark `zoho_sync_status=DIRTY` (except initial pending variants without a Zoho item), so Zoho outbound sync can reconcile edits.
  - `DELETE /variants/{id}` — Soft-delete archive: sets `is_active=false`, renames SKU to `D-{old_sku}` (collision-safe suffix fallback), and clears `color_code`/`condition_code` to free identity+color+condition reuse.
  - `POST /variants/{id}/deactivate` — Soft-delete (sets `is_active=False`).
  - `GET /variants/pending-sync/zoho` — Returns all variants where `zoho_sync_status != SYNCED`.

---

### `bundles.py` (Path: `app/modules/inventory/routes/bundles.py`)

* **Purpose:** Bundle Component (Bill of Materials) management endpoints.
* **Dependencies & Links:**
  - Internal: `app.repositories.inventory.BundleComponentRepository`, `app.repositories.product.ProductIdentityRepository`, inventory schemas.
* **Mechanism / Core Logic:**
  - `GET /bundles` — List with optional `parent_identity_id` filter.
  - `POST /bundles` — Create component link. Validates: parent and child identities exist, no duplicate parent+child, no self-reference.
  - `GET /bundles/{id}` — Get component with parent/child UPIS-H details.
  - `GET /bundles/parent/{id}/components` — Get all components in a bundle/kit.
  - `GET /bundles/child/{id}/bundles` — Get all bundles that contain a given component.
  - `PATCH /bundles/{id}` — Update `quantity_required` or `role`.
  - `DELETE /bundles/{id}` — Remove component from bundle.

---

### `listings.py` (Path: `app/modules/inventory/routes/listings.py`)

* **Purpose:** Platform Listing CRUD with sync status tracking.
* **Dependencies & Links:**
  - Internal: `app.repositories.inventory.PlatformListingRepository`, `app.repositories.product.ProductVariantRepository`, `app.models.entities` (Platform, PlatformSyncStatus), inventory schemas.
* **Mechanism / Core Logic:**
  - `GET /listings` — List with optional platform and sync status filters.
  - `POST /listings` — Create listing (one per variant per platform). Validates variant exists.
  - `GET /listings/{id}` — Get listing by ID.
  - `GET /listings/platform/{platform}/ref/{ref_id}` — Lookup by external reference ID (used for auto-matching).
  - `PUT/PATCH /listings/{id}` — Update with automatic sync status tracking.
  - `DELETE /listings/{id}` — Delete listing.
  - `GET /listings/pending` — All listings with `sync_status=PENDING`.
  - `GET /listings/errors` — All listings with `sync_status=ERROR`.
  - `POST /listings/{id}/mark-synced` — Set status to SYNCED with timestamp.
  - `POST /listings/{id}/mark-error` — Set status to ERROR with error message.

---

### `inventory.py` (Path: `app/modules/inventory/routes/inventory.py`)

* **Purpose:** Physical inventory item management with warehouse operations.
* **Dependencies & Links:**
  - Internal: `app.repositories.inventory`, `app.repositories.product.ProductVariantRepository`, `app.models.entities.InventoryStatus`, inventory schemas.
* **Mechanism / Core Logic:**
  - `GET /inventory` — List with filters: `variant_id`, `status`, `location_code`.
  - `POST /inventory` — Create item (validates variant exists).
  - `GET /inventory/{id}` — Get by ID.
  - `GET /inventory/serial/{serial_number}` — Lookup by serial number.
  - `PUT/PATCH /inventory/{id}` — Update fields.
  - `DELETE /inventory/{id}` — Delete item.
  - `POST /inventory/{id}/reserve` — Status transition AVAILABLE → RESERVED.
  - `POST /inventory/{id}/sell` — Status transition → SOLD with `sold_at` timestamp.
  - `GET /inventory/summary/{variant_id}` — Count by status (available/sold/reserved/rma/damaged/total).
  - `GET /inventory/value/total` — Calculate total inventory cost basis.
  - `POST /inventory/receive` — Warehouse receive operation: resolves variant by full_sku, creates item with `received_at` timestamp, serial number, location, cost.

---

### `images.py` (Path: `app/modules/inventory/routes/images.py`)

* **Purpose:** Product image metadata/file serving, upload/delete management, and thumbnail backfill from the filesystem-based image repository.
* **Dependencies & Links:**
  - Internal: `app.models.entities` (ProductVariant, ProductIdentity, ZohoSyncStatus), inventory schemas.
  - Filesystem: `/mnt/product_images/` hierarchical directory.
* **Mechanism / Core Logic:**
  - Images are written by backend routes and stored on disk under `/mnt/product_images/{generated_upis_h}/{full_sku}/listing-{n}/img-{index}.{ext}`.
  - In production, Nginx serves stored files directly at `/product-images/*`; uploads still go through backend API routes.
  - `_get_variant_context(db, sku)` — Resolves a SKU to variant metadata needed for path resolution.
  - `_find_variant_dir(context)` — Determines the filesystem path for a variant's images.
  - `_get_best_listing(variant_dir)` — Selects the listing folder with the most images.
  - `_sorted_images(listing_path)` — Returns images sorted lexicographically, filtering by supported formats.
  - `_resolve_or_backfill_thumbnail_url(db, sku)` — Computes thumbnail URL and backfills `thumbnail_url` column in DB on first access.
  - `_ensure_listing_dir(context, listing_index)` — Ensures destination listing folder exists before writes.
  - `_recompute_thumbnail_url(db, context, mark_sync_dirty=False)` — Recomputes and persists thumbnail URL after image mutations; can also mark variant Zoho sync as DIRTY.
  - `GET /images/{sku}` — Returns image metadata (paths, count, thumbnail URL) for a given SKU.
  - `GET /images/{sku}/thumbnail` — Resolves thumbnail and redirects to direct static `/product-images/...` URL.
  - `GET /images/{sku}/file/{filename}` — Serves a specific image from the best listing.
  - `GET /images/batch/thumbnails` — Batch thumbnail URL resolution for multiple SKUs.
  - `POST /images/{sku}/upload` — Multipart upload (`files[]`, `listing_index`, `replace`) that writes files to disk; thumbnail recompute marks variant Zoho sync DIRTY.
  - `DELETE /images/{sku}/listing/{listing_index}/file/{filename}` — Deletes one image and recomputes thumbnail (marks Zoho sync DIRTY).
  - `POST /images/{sku}/listing/{listing_index}/clear` — Deletes all images in listing and recomputes thumbnail (marks Zoho sync DIRTY).
  - `POST /images/debug/backfill-thumbnails` / `GET /images/debug/counters` — Admin/debug maintenance endpoints.

---

### `lookups.py` (Path: `app/modules/inventory/routes/lookups.py`)

* **Purpose:** CRUD endpoints for lookup/reference tables (Brand, Color, Condition, LCI Definition).
* **Dependencies & Links:**
  - Internal: `app.models.entities` (Brand, Color, Condition, LCIDefinition), inventory schemas.
* **Mechanism / Core Logic:**
  - **4 separate routers**, each providing:
    - `GET /brands` (or `/colors`, `/conditions`, `/lci-definitions`) — List with optional name/code search.
    - `POST ...` — Create with uniqueness validation (name, code).
    - `GET .../{id}` — Get by ID.
    - `PATCH .../{id}` — Update.
    - `DELETE .../{id}` — Delete.
  - LCI definitions also support filtering by `product_id`.

---

### `zoho.py` (Path: `app/modules/inventory/routes/zoho.py`)

* **Purpose:** Zoho Inventory synchronisation endpoints for bulk/single item sync with image upload, composite item creation, and readiness validation.
* **Dependencies & Links:**
  - Internal: `app.models.entities` (ProductVariant, ProductIdentity), `app.integrations.zoho.client.ZohoClient`, inventory schemas.
* **Mechanism / Core Logic:**
  - `_ZohoSyncJobState` — In-memory job state tracker for long-running bulk syncs (status, progress counts, current SKU, cancel flag, error history).
  - `_load_target_variants(db, data)` — Loads variants for sync (optionally filtered, force-resync, or unsynced-only).
  - `_resolve_sync_image_paths(variant)` — Determines which image files exist on disk for a variant.
  - `_build_item_payload(variant)` — Constructs Zoho Inventory item payload from variant data.
  - Standard/composite sync paths prefer updating existing linked Zoho IDs first (`preferred_item_id`) and attempt to inactivate old Zoho records when linkage changes.
  - **Endpoints:**
    - `POST /zoho/sync-single` — Synchronises a single variant to Zoho (create/update) with optional image upload and composite item handling.
    - `POST /zoho/sync-bulk` — Queues async bulk sync as a background task. Returns `job_id` for polling.
    - `GET /zoho/sync-progress/{job_id}` — Returns current progress of a bulk sync job.
    - `POST /zoho/sync-readiness` — Validates a set of variants for Zoho readiness: checks required fields, image availability, composite prerequisites. Returns per-variant readiness report with severity levels (READY, WARNING, BLOCKED).

---

### INVENTORY MODULE — SCHEMAS

---

### `__init__.py` (Path: `app/modules/inventory/schemas/__init__.py`)

* **Purpose:** Central export point for 60+ Pydantic inventory schemas.
* **Dependencies & Links:** Imports from all schema sub-modules.
* **Mechanism / Core Logic:** Re-exports all schema classes and provides `__all__` list.

---

### `bundles.py` (Path: `app/modules/inventory/schemas/bundles.py`)

* **Purpose:** Pydantic schemas for bundle component CRUD.
* **Dependencies & Links:** Pydantic BaseModel with `from_attributes=True`.
* **Mechanism / Core Logic:**
  - `BundleComponentBase` — `quantity_required` (≥1), `role` (PRIMARY/ACCESSORY/SATELLITE).
  - `BundleComponentCreate` — Extends base with `parent_identity_id`, `child_identity_id`.
  - `BundleComponentUpdate` — All fields optional.
  - `BundleComponentResponse` — Full response with `id`, timestamps.
  - `BundleComponentWithDetails` — Includes `parent_upis_h`, `child_upis_h` strings.

---

### `families.py` (Path: `app/modules/inventory/schemas/families.py`)

* **Purpose:** Pydantic schemas for product family operations.
* **Dependencies & Links:** Pydantic BaseModel.
* **Mechanism / Core Logic:**
  - `ProductFamilyBase` — `base_name`, `description`, `brand_id` (optional FK), `dimension_length/width/height`, `weight`, `kit_included_products`.
  - `ProductFamilyCreate` — Extends base with optional `product_id` (auto-generated if omitted).
  - `ProductFamilyUpdate` — All fields optional.
  - `ProductFamilyResponse` — Includes brand details, timestamps.
  - `ProductFamilyWithIdentities` — Adds `identities_count`.

---

### `identities.py` (Path: `app/modules/inventory/schemas/identities.py`)

* **Purpose:** Pydantic schemas for product identity CRUD.
* **Dependencies & Links:** Pydantic BaseModel.
* **Mechanism / Core Logic:**
  - `ProductIdentityBase` — `type` (IdentityType), `lci` (1-99, Parts only), `physical_class`.
  - `ProductIdentityCreate` — Adds `product_id`.
  - `ProductIdentityUpdate` — Only `physical_class` (quasi-immutable identity).
  - `ProductIdentityResponse` — Adds `generated_upis_h`, `hex_signature`, timestamps.
  - `ProductIdentityWithVariants` — Adds `variants_count`.

---

### `variants.py` (Path: `app/modules/inventory/schemas/variants.py`)

* **Purpose:** Pydantic schemas for product variant operations.
* **Dependencies & Links:** Pydantic BaseModel.
* **Mechanism / Core Logic:**
  - `ProductVariantBase` — `variant_name`, `color_code` (2-char), `condition_code` (N/R), `is_active`.
  - `ProductVariantCreate` — Adds `identity_id`.
  - `ProductVariantUpdate` — All fields optional.
  - `ProductVariantResponse` — Adds `full_sku`, `zoho_item_id`, `thumbnail_url`, `zoho_sync_status`, timestamps.
  - `ProductVariantWithListings` — Adds `listings_count`.

---

### `inventory.py` (Path: `app/modules/inventory/schemas/inventory.py`)

* **Purpose:** Pydantic schemas for inventory items and warehouse operations.
* **Dependencies & Links:** Pydantic BaseModel.
* **Mechanism / Core Logic:**
  - `InventoryItemBase` — `serial_number`, `status`, `location_code`, `cost_basis`, `notes`.
  - `InventoryItemCreate` / `InventoryItemUpdate` — Standard CRUD schemas.
  - `InventoryItemResponse` — Adds `received_at`, `sold_at`, timestamps.
  - `InventoryItemWithVariant` — Adds `full_sku` for display context.
  - `InventorySummary` — Status counts: `available`, `sold`, `reserved`, `rma`, `damaged`, `total`.
  - **Warehouse operation schemas:** `InventoryReceiveRequest/Response` (serial, sku, location, cost → confirmation with timestamp), `InventoryMoveRequest/Response` (serial, new_location → previous/new location with moved_at), `InventoryAuditItem/Response` (audit result list).

---

### `listings.py` (Path: `app/modules/inventory/schemas/listings.py`)

* **Purpose:** Pydantic schemas for platform listings.
* **Dependencies & Links:** Pydantic BaseModel.
* **Mechanism / Core Logic:**
  - `PlatformListingBase` — `platform`, `external_ref_id`, `listed_name`, `listed_description`, `listing_price`.
  - `PlatformListingCreate` — Adds `variant_id`.
  - `PlatformListingUpdate` — All fields optional.
  - `PlatformListingResponse` — Adds `sync_status`, `last_synced_at`, `sync_error_message`, `platform_metadata` (JSONB dict), timestamps.

---

### `lookups.py` (Path: `app/modules/inventory/schemas/lookups.py`)

* **Purpose:** Pydantic schemas for lookup tables (Brand, Color, Condition, LCI Definition).
* **Dependencies & Links:** Pydantic BaseModel.
* **Mechanism / Core Logic:**
  - Each lookup type (Brand, Color, Condition, LCIDefinition) has Create/Update/Response schemas.
  - Brand: `name` (string).
  - Color: `name` + `code` (2-char).
  - Condition: `name` + `code` (1-char).
  - LCIDefinition: `product_id`, `component_name`, `lci_index` (auto-assignable).

---

### `pagination.py` (Path: `app/modules/inventory/schemas/pagination.py`)

* **Purpose:** Generic paginated response wrapper.
* **Dependencies & Links:** Pydantic BaseModel.
* **Mechanism / Core Logic:**
  - `PaginatedResponse` — `total` (int), `skip` (int), `limit` (int), `items` (list).

---

### `zoho.py` (Path: `app/modules/inventory/schemas/zoho.py`)

* **Purpose:** Zoho sync operation request/response schemas.
* **Dependencies & Links:** Pydantic BaseModel.
* **Mechanism / Core Logic:**
  - `ZohoBulkSyncRequest` / `ZohoSingleSyncRequest` — `include_images`, `include_composites`, `force_resync`, `limit`.
  - `ZohoBulkSyncItemResult` — Per-variant result: `variant_id`, `sku`, `action` (created/updated), `success`, `zoho_sync_status`, `image_uploaded`, `composite_synced`, `message`.
  - `ZohoBulkSyncResponse` — Aggregate: `started_at`, `finished_at`, `total_processed/success/failed`, `items` list.
  - `ZohoReadinessRequest` — `include_images`, `include_composites`, `only_unsynced`, `limit`.
  - `ZohoReadinessItem` — Per-variant: `variant_id`, `sku`, `identity_type`, `ready`, `severity` (READY/WARNING/BLOCKED), `missing_fields`, `warnings`.
  - `ZohoReadinessResponse` — Aggregate: `total_checked`, `ready_count`, `blocked_count`, `warning_only_count`, `items`.
  - `ZohoSyncProgressResponse` — Job status: `job_id`, `status`, timestamps, counts, `current_sku`, `cancel_requested`, `last_error`.

---

### ORDERS MODULE

---

### `__init__.py` (Path: `app/modules/orders/__init__.py`)

* **Purpose:** Orders module docstring documenting scope (order ingestion, integration state tracking, auto-matching, manual SKU resolution).
* **Dependencies & Links:** None.
* **Mechanism / Core Logic:** Module-level documentation only.

---

### `models.py` (Path: `app/modules/orders/models.py`)

* **Purpose:** SQLAlchemy ORM models for the orders domain.
* **Dependencies & Links:**
  - Internal: `app.core.database.Base`, `app.models.entities` (TimestampMixin, ZohoSyncMixin, ZohoSyncStatus).
  - Referenced by: order routes, service, repositories, sync engine.
* **Mechanism / Core Logic:**

  **Enums (5):**
  - `OrderPlatform` — AMAZON, EBAY_MEKONG, EBAY_USAV, EBAY_DRAGON, ECWID, ZOHO, MANUAL.
  - `OrderStatus` — PENDING, PROCESSING, READY_TO_SHIP, SHIPPED, DELIVERED, CANCELLED, REFUNDED, ON_HOLD, ERROR.
  - `ShippingStatus` — PENDING, ON_HOLD, CANCELLED, PACKED, SHIPPING, DELIVERED.
  - `OrderItemStatus` — UNMATCHED, MATCHED, ALLOCATED, SHIPPED, CANCELLED.
  - `IntegrationSyncStatus` — IDLE, SYNCING, ERROR.

  **IntegrationState** — Table `integration_state`. One row per platform. Fields: `platform_name` (unique), `last_successful_sync`, `current_status` (IDLE/SYNCING/ERROR), `last_error_message`. Used as the sync lock for the Safe Sync algorithm.

  **Order** — Table `orders`. Uses `ZohoSyncMixin`. Fields: `platform`, `external_order_id` (unique per platform), `external_order_number`, `status`, `shipping_status`, `zoho_sync_status`, `customer_id` (FK→Customer), denormalised `customer_name/email`, full shipping address, financials (`subtotal_amount`, `tax_amount`, `shipping_amount`, `total_amount`, `currency`), timestamps (`ordered_at`, `shipped_at`), tracking (`tracking_number`, `carrier`), `platform_data` (JSONB raw data), `processing_notes`, `error_message`. Relationships: `customer`, `items`.

  **OrderItem** — Table `order_item`. Fields: `order_id` (FK→Order), `external_item_id`, `external_sku`, `external_asin`, `variant_id` (FK→ProductVariant, nullable = SKU matching workspace), `allocated_inventory_id` (FK→InventoryItem), `status` (UNMATCHED→MATCHED→ALLOCATED→SHIPPED), `item_name`, `quantity`, `unit_price`, `total_price`, `item_metadata` (JSONB), `matching_notes`. Relationships: `order`, `variant`, `allocated_inventory`.

---

### `routes.py` (Path: `app/modules/orders/routes.py`)

* **Purpose:** Order API endpoints covering synchronization, CRUD, and SKU resolution.
* **Dependencies & Links:**
  - Internal: `app.modules.orders.dependencies` (DI factories), `app.modules.orders.service.OrderSyncService`, `app.modules.orders.schemas.*`, `app.integrations.*` (platform clients), `app.core.config`.
  - External: `fastapi`.
* **Mechanism / Core Logic:**

  **Platform Client Factory:**
  - `_build_platform_clients()` — Instantiates all configured platform clients from environment variables: AmazonClient, EbayClient (×3 stores), EcwidClient. Only builds clients whose credentials are set.

  **Sync Endpoints:**
  - `POST /orders/sync` — Triggers Safe Sync for one or all platforms. Returns per-platform `SyncResponse` (new orders, auto-matched items, skipped duplicates, errors).
  - `POST /orders/sync/range` — Admin-only historical date range sync (no lock acquisition).
  - `GET /orders/sync/status` — Dashboard: all platform states + aggregate item counters (total orders, unmatched, matched).
  - `POST /orders/sync/{platform_name}/reset` — Force-reset a stuck platform from ERROR/SYNCING to IDLE.

  **Order CRUD:**
  - `GET /orders` — Paginated dashboard with filters: platform, status, item_status (e.g. UNMATCHED), free-text search.
  - `GET /orders/{order_id}` — Full order detail with all line items.
  - `PATCH /orders/{order_id}` — Update order status and/or processing notes.
  - `PATCH /orders/{order_id}/shipping` — Update shipping/fulfilment status (with optional tracking/carrier/notes) and mark Zoho sync dirty when shipping status changes.

  **SKU Resolution:**
  - `POST /orders/items/{item_id}/match` — Manual "Match & Learn": links order item → product variant. If `learn=True` (default), also creates a `PlatformListing` row for future auto-matching.
  - `POST /orders/items/{item_id}/confirm` — Confirms an auto-assigned match.
  - `POST /orders/items/{item_id}/reject` — Rejects a bad match, resets to UNMATCHED.

---

### `service.py` (Path: `app/modules/orders/service.py`)

* **Purpose:** Order Sync Service — the "Safe Sync" engine orchestrating order ingestion from external platforms.
* **Dependencies & Links:**
  - Internal: `app.integrations.base` (BasePlatformClient, ExternalOrder), `app.models.entities` (Platform, PlatformListing, Customer), `app.modules.orders.models`, `app.repositories.*` (SyncRepository, OrderRepository, OrderItemRepository, PlatformListingRepository).
* **Mechanism / Core Logic:**

  **Safe Sync Workflow (`sync_platform()`):**
  1. **Acquire sync lock** — `IntegrationState.IDLE → SYNCING` (atomic via SyncRepository).
  2. **Calculate fetch window** — `last_successful_sync - 10 minutes` buffer (or default to 2026-01-01 for first sync).
  3. **Fetch orders** — Calls `client.fetch_orders(since=fetch_since)` on the external adapter.
  4. **Ingest idempotently** — For each `ExternalOrder`, checks for existing order via `platform + external_order_id` unique constraint. Skips duplicates silently.
  5. **Auto-match items** — For each order item: looks up `PlatformListing` by `(platform, external_ref_id)` or `(platform, external_sku)`. If found, links `variant_id` and sets status to MATCHED.
  6. **Commit & release lock** — On success: `SYNCING → IDLE`, updates `last_successful_sync`. On failure: `SYNCING → ERROR` with error message.

  **Admin Range Sync (`sync_platform_range()`):**
  - Same ingestion logic but with caller-supplied date range. No lock acquisition or anchor update. Deduplication still applies.

  **SKU Resolution Methods:**
  - `match_item(item_id, variant_id, learn, notes)` — Manual match. If `learn=True`, creates PlatformListing for future auto-matching.
  - `confirm_item(item_id, notes)` — Confirms an auto-match (keeps status MATCHED).
  - `reject_item(item_id)` — Clears `variant_id`, resets to UNMATCHED.

  **Platform Mapping:**
  - `_PLATFORM_MAP` — Maps integration names (e.g. "AMAZON") to `OrderPlatform` enum values.
  - `_ORDER_TO_ENTITY_PLATFORM` — Maps `OrderPlatform` to `entities.Platform` for listing lookups.

---

### `dependencies.py` (Path: `app/modules/orders/dependencies.py`)

* **Purpose:** FastAPI dependency injection factories for the orders module.
* **Dependencies & Links:**
  - Internal: `app.core.database.get_db`, `app.repositories.inventory.PlatformListingRepository`, `app.repositories.orders.*` (OrderRepository, OrderItemRepository, SyncRepository), `app.modules.orders.service.OrderSyncService`.
* **Mechanism / Core Logic:**
  - `get_sync_repo(db)` → `SyncRepository(db)`
  - `get_order_repo(db)` → `OrderRepository(db)`
  - `get_order_item_repo(db)` → `OrderItemRepository(db)`
  - `get_listing_repo(db)` → `PlatformListingRepository(db)`
  - `get_order_sync_service(db, sync_repo, order_repo, order_item_repo, listing_repo)` → Fully-wired `OrderSyncService`.

---

### ORDER SCHEMAS

---

### `orders.py` (Path: `app/modules/orders/schemas/orders.py`)

* **Purpose:** Pydantic schemas for order CRUD, item details, and SKU matching operations.
* **Dependencies & Links:** Pydantic BaseModel, order model enums.
* **Mechanism / Core Logic:**
  - `CustomerBrief` — `id`, `name`, `email`, `phone`, `company_name`.
  - `OrderItemBrief` — External identifiers (`external_item_id`, `external_sku`, `external_asin`), `item_name`, `quantity`, `unit_price`, `total_price`, `status`, `variant_id`, resolved `variant_sku`, `matching_notes`.
  - `OrderItemDetail` — Extends brief with `allocated_inventory_id`, `item_metadata`, timestamps.
  - `OrderItemMatchRequest` — `variant_id` (int), `learn` (bool, default True), `notes` (optional).
  - `OrderItemConfirmRequest` — `notes` (optional).
  - `OrderBrief` — Summary: `id`, `platform`, IDs, `status`, `zoho_sync_status`, `customer_name`, `customer` (optional CustomerBrief), `total_amount`, `currency`, `ordered_at`, timestamps, `item_count`, `unmatched_count`.
  - `OrderDetail` — Full: adds shipping address fields, financial breakdown, tracking info, `items` list, `processing_notes`, `error_message`.
  - `OrderCreate` — Manual order creation: `external_order_id`, `customer_name`, `customer_email`, `total_amount`, `currency`, `notes`.
  - `OrderStatusUpdate` — `status` (OrderStatus), `notes` (optional).
  - `OrderListResponse` — Paginated: `total`, `skip`, `limit`, `items` (list of OrderBrief).

---

### `sync.py` (Path: `app/modules/orders/schemas/sync.py`)

* **Purpose:** Integration state and sync operation schemas.
* **Dependencies & Links:** Pydantic BaseModel, order model enums.
* **Mechanism / Core Logic:**
  - `IntegrationStateResponse` — `id`, `platform_name`, `last_successful_sync`, `current_status` (IDLE/SYNCING/ERROR), `last_error_message`, `updated_at`.
  - `SyncRequest` — `platform` (optional; omit for all platforms).
  - `SyncRangeRequest` — `platform` (optional), `since` (datetime), `until` (datetime).
  - `SyncResponse` — Per-platform result: `platform`, `new_orders`, `new_items`, `auto_matched`, `skipped_duplicates`, `errors` (list of strings), `success` (bool).
  - `SyncStatusResponse` — Dashboard overview: `platforms` (list of IntegrationStateResponse), `total_orders`, `total_unmatched_items`, `total_matched_items`.

---

### PURCHASING MODULE

---

### `routes.py` (Path: `app/modules/purchasing/routes.py`)

* **Purpose:** Purchasing APIs for vendor management, purchase orders, line-item match workflows, receiving, and imports.
* **Dependencies & Links:**
  - Internal: `app.modules.purchasing.service.PurchasingService`, purchasing repositories, `app.integrations.zoho.client.ZohoClient`, `app.repositories.product.ProductVariantRepository`.
  - External: `fastapi`, `sqlalchemy`.
* **Mechanism / Core Logic:**
  - `GET/POST/PATCH /vendors...` — Vendor list/create/update endpoints.
  - `GET/POST /purchases...` + `GET /purchases/{po_id}` — Purchase order list/create/detail endpoints.
  - `GET /purchases` supports server-side order-date controls: `date_sort=asc|desc`, `order_date_from=YYYY-MM-DD`, `order_date_to=YYYY-MM-DD`.
  - `POST /purchases/{po_id}/items` — Add a purchase order line item.
  - `POST /purchases/items/{item_id}/match` — Manually match a PO line item to a product variant.
  - `DELETE /purchases/items/{item_id}` — Delete a PO line item; rejects deletion for `RECEIVED` items.
  - `POST /purchases/{po_id}/mark-delivered` — Receive PO items into inventory and mark PO delivered.
  - `POST /purchases/import/zoho` — Bulk vendor + PO import from Zoho.
  - `POST /purchases/import/zoho/random-one` — Random single PO import for test validation, with fallback probing across pages when the selected page has no results.
  - `POST /purchases/import/file?source={goodwill|amazon|aliexpress}` — Source-based file import:
    - `source=goodwill` — Goodwill CSV parser (legacy columns: Order #, Item Id, Item, Quantity, Price, Date, Tracking #, Tax, Shipping, Handling).
    - `source=amazon` — Amazon CSV parser grouped by `Order ID`; deduplicates repeated split-payment rows and excludes all rows where `Account User` is `Dragonhn` (personal purchases).
    - `source=aliexpress` — AliExpress JSON parser expecting an array of orders with `orderId`, `items[]`, `seller`, and `priceData` fields.
  - Legacy compatibility endpoint `POST /purchases/import/goodwill-csv` remains available and delegates to the source-based file importer.

---

### SYNC MODULE

---

### `endpoints.py` (Path: `app/modules/sync/endpoints.py`)

* **Purpose:** Manual "Force Sync" endpoints for on-demand Zoho synchronisation.
* **Dependencies & Links:**
  - Internal: `app.api.deps.AdminUser`, `app.core.database.get_db`, `app.integrations.zoho.sync_engine` (sync_variant_outbound, sync_order_outbound, sync_po_outbound, sync_customer_outbound), `app.models.entities` (Customer, ProductVariant), `app.models.purchasing.PurchaseOrder`, `app.modules.orders.models.Order`.
  - External: `fastapi.BackgroundTasks`.
* **Mechanism / Core Logic:**
  - All endpoints require ADMIN role.
  - All return `202 Accepted` immediately; actual work runs as FastAPI background tasks.
  - `POST /sync/items/{variant_id}` — Queues outbound Zoho sync for a ProductVariant. Validates variant exists and is active.
  - `POST /sync/orders/{order_id}` — Queues outbound Zoho sync for an Order. Background worker handles dependency checks (Customer/Variant Zoho IDs).
  - `POST /sync/purchases/{po_id}` — Queues outbound Zoho sync for a PurchaseOrder. Validates PO exists, has items, and all line items are matched before queueing.
  - `POST /sync/customers/{customer_id}` — Queues outbound Zoho sync for a Customer.

---

### INTEGRATIONS

---

### `__init__.py` (Path: `app/integrations/__init__.py`)

* **Purpose:** Package init that imports all platform clients and registers them with the `PlatformClientFactory`.
* **Dependencies & Links:** `app.integrations.base`, `app.integrations.amazon.client`, `app.integrations.ebay.client`, `app.integrations.ecwid.client`.
* **Mechanism / Core Logic:** Registers factory entries for AMAZON, EBAY_MEKONG, EBAY_USAV, EBAY_DRAGON, ECWID.

---

### `base.py` (Path: `app/integrations/base.py`)

* **Purpose:** Abstract base class and data transfer objects defining the integration contract for all platform clients.
* **Dependencies & Links:** Python `abc.ABC`, `dataclasses`.
* **Mechanism / Core Logic:**

  **Dataclasses (4):**
  - `ExternalOrder` — Normalised order: platform IDs, customer info, shipping address, financials, timestamps, items list, raw_data.
  - `ExternalOrderItem` — Normalised item: platform IDs (item_id, sku, asin), title, quantity, prices, raw_data.
  - `StockUpdate` — SKU + quantity for outbound stock pushes.
  - `StockUpdateResult` — Success/failure per SKU.

  **Abstract Class:**
  - `BasePlatformClient(ABC)` — Contract methods:
    - `platform_name` (property) — Platform identifier string.
    - `authenticate()` — API authentication.
    - `fetch_orders(since, until, status)` → `List[ExternalOrder]`.
    - `get_order(order_id)` → `Optional[ExternalOrder]`.
    - `update_stock(updates)` → `List[StockUpdateResult]`.
    - `update_tracking(order_id, tracking_number, carrier)` → `bool`.
    - `health_check()` — Defaults to calling `authenticate()`.

  **Factory:**
  - `PlatformClientFactory` — Registry pattern: `register(name, cls)`, `create(name, **kwargs)`.

---

### `client.py` (Path: `app/integrations/amazon/client.py`)

* **Purpose:** Amazon SP-API client skeleton providing placeholder implementations.
* **Dependencies & Links:** `app.integrations.base` (BasePlatformClient, ExternalOrder, ExternalOrderItem, StockUpdate, StockUpdateResult).
* **Mechanism / Core Logic:**
  - `AmazonClient(BasePlatformClient)` — Constructor takes `refresh_token`, `client_id`, `client_secret`, `marketplace_id`.
  - All methods (`authenticate`, `fetch_orders`, `get_order`, `update_stock`, `update_tracking`) contain placeholder logic with TODO comments for SP-API integration.
  - `_convert_order(data)` — Skeleton converter from Amazon order JSON to `ExternalOrder`.

---

### `client.py` (Path: `app/integrations/ebay/client.py`)

* **Purpose:** Fully implemented eBay Trading/Fulfillment API client supporting 3 stores.
* **Dependencies & Links:** `app.integrations.base`, `httpx`.
* **Mechanism / Core Logic:**
  - `EbayClient(BasePlatformClient)` — Constructor: `store_name` (MEKONG/USAV/DRAGON), `app_id`, `cert_id`, `refresh_token`, `sandbox`.
  - `authenticate()` / `_refresh_access_token()` — OAuth2 token refresh with retry logic and DNS re-resolution for eBay CDN issues.
  - `_get_access_token()` — Returns cached token, refreshing if expired.
  - `fetch_orders(since, until, status)` — Paginated order fetching via eBay Fulfillment API with date/status filtering.
  - `fetch_daily_orders(date)` — Convenience wrapper for single-day fetches.
  - `get_order(order_id)` — Single order retrieval.
  - `update_stock(updates)` — Stock level updates via eBay Inventory API.
  - `update_tracking(order_id, tracking_number, carrier)` — Shipment tracking via Fulfillment API.
  - `_convert_order(data)` — Converts eBay JSON → `ExternalOrder` with address parsing, line item extraction, and price computation.

---

### `client.py` (Path: `app/integrations/ecwid/client.py`)

* **Purpose:** Complete Ecwid e-commerce API client for order retrieval and inventory management.
* **Dependencies & Links:** `app.integrations.base`, `httpx`.
* **Mechanism / Core Logic:**
  - `EcwidClient(BasePlatformClient)` — Constructor: `store_id`, `access_token`, optional `api_base_url`.
  - `authenticate()` — Validates API access via store profile fetch.
  - `test_connection()` — Returns connection status and store info.
  - `fetch_orders(since, until, status)` — Date/status-filtered order retrieval with pagination.
  - `fetch_daily_orders(date)`, `fetch_orders_since_last_sync()`, `fetch_new_orders()` — Convenience wrappers.
  - `get_order(order_id)` — Single order fetch.
  - `update_stock(updates)` — Inventory level updates.
  - `update_tracking(order_id, tracking_number, carrier)` — Tracking information updates.
  - `_parse_ecwid_order(data)` — Converts Ecwid JSON → `ExternalOrder` with Unix timestamp parsing.
  - Error handling: automatic retry for rate limits (429), timeouts, and HTTP errors.

---

### `client.py` (Path: `app/integrations/zoho/client.py`)

* **Purpose:** Comprehensive Zoho Inventory/Books API client with OAuth2, shared token caching, and full CRUD capabilities.
* **Dependencies & Links:** `app.core.config.settings`, `httpx`.
* **Mechanism / Core Logic:**
  - `ZohoClient` — Constructor: optional credentials (defaults from settings).
  - **Authentication:** `_ensure_access_token()` / `_refresh_access_token()` — Shared class-level token cache with asyncio lock for thread safety.
  - **Generic request:** `_request(method, url, **kwargs)` — Authenticated requests with automatic token refresh and rate-limit error detection (`RateLimitError` custom exception).
  - **Item operations:** `create_item()`, `update_item()`, `get_item_by_sku()`, `sync_item()` (upsert by SKU with optional `preferred_item_id` update-first behavior), `upload_item_image()`, `mark_item_inactive/active()`, `list_items()`.
  - **Composite items:** `create_composite_item()`, `update_composite_item()`, `get_composite_item_by_sku()`, `sync_composite_item()` (supports `preferred_item_id`).
  - **Stock:** `update_stock()`, `get_stock_level()`.
  - **Sales orders:** `create_sales_order()`, `update_salesorder()`, `get_salesorder()`, `list_salesorders()`, `confirm_salesorder()`.
  - **Sales order fulfilment:** `create_package()`, `list_packages()`, `create_shipment_order()`, `list_shipment_orders()`, `mark_shipment_delivered()`.
  - **Contacts:** `create_contact()`, `update_contact()`, `get_contact()`, `get_contact_by_email()`, `list_contacts()`, `mark_contact_inactive/active()`.
  - **Purchase orders:** `create_purchase_order()`, `update_purchase_order()`, `get_purchase_order()`, `list_purchase_orders()`.
  - **Health:** `health_check()`.

---

### `sync_engine.py` (Path: `app/integrations/zoho/sync_engine.py`)

* **Purpose:** Two-way Zoho sync engine with echo-loop prevention and SQLAlchemy event listener integration.
* **Dependencies & Links:**
  - Internal: `app.core.database.async_session_factory`, `app.integrations.zoho.client` (ZohoClient, RateLimitError), `app.integrations.zoho.security.generate_payload_hash`, `app.models.entities` (Customer, ProductVariant, ZohoSyncStatus), `app.modules.orders.models` (Order, OrderItem, OrderStatus).
* **Mechanism / Core Logic:**

  **Payload builders:**
  - `variant_to_zoho_payload(variant)` — Builds Zoho item dict from ProductVariant (name, SKU, description, rate, etc.).
  - `customer_to_zoho_payload(customer)` — Builds Zoho contact dict from Customer.
  - `order_to_zoho_payload(order, customer_zoho_id, line_items)` — Builds Zoho SalesOrder dict with dependency-aware line items.
  - `_sanitize_shipping_address(order)` — Trims address fields to Zoho character limits.

  **Outbound sync workers (run as background tasks):**
  - `sync_variant_outbound(variant_id)` — Opens fresh session, loads variant, builds payload, computes SHA-256 hash, skips if hash matches `zoho_last_sync_hash` (echo prevention). Creates or updates Zoho item. Updates variant with `zoho_item_id`, `zoho_sync_status=SYNCED`, `zoho_last_sync_hash`.
  - `sync_customer_outbound(customer_id)` — Same pattern for Customer → Zoho Contact.
  - `sync_order_outbound(order_id)` — Dependency-aware: ensures Customer has `zoho_id`, ensures all matched OrderItem variants have `zoho_item_id`. If dependencies missing, syncs them first. Then creates/updates Zoho SalesOrder.

  **Inbound webhook processors:**
  - `process_item_inbound(payload)` — Receives Zoho item webhook, finds matching ProductVariant by `zoho_item_id`, applies relevant field updates, sets `_updated_by_sync=True` to prevent echo.
  - `process_contact_inbound(payload)` — Same pattern for contacts → Customer.
  - `process_order_inbound(payload)` — Applies Zoho SalesOrder changes to local Order.

  **SQLAlchemy event listeners:**
  - `_on_variant_after_write()` — Fires on `after_insert` / `after_update` for ProductVariant. Checks `_updated_by_sync` flag; if False, enqueues `sync_variant_outbound` as background task.
  - `_on_customer_after_write()` — Same for Customer.
  - `_on_order_after_write()` — Same for Order.
  - `register_sync_listeners()` — Called at startup to attach all event listeners.

  **Echo-loop prevention:** Each sync direction computes a SHA-256 hash of the payload. Outbound skips if local hash matches. Inbound sets `_updated_by_sync=True` so the SQLAlchemy `after_update` listener doesn't re-enqueue an outbound sync.

---

### `webhooks.py` (Path: `app/integrations/zoho/webhooks.py`)

* **Purpose:** Lightweight Zoho webhook receiver with async handler dispatch.
* **Dependencies & Links:** `fastapi` (APIRouter, BackgroundTasks).
* **Mechanism / Core Logic:**
  - `_handlers: dict[str, Callable]` — Module-level registry mapping Zoho event types to async handler functions.
  - `register_webhook_handler(event_type, handler)` — Adds handler to registry.
  - `_dispatch_webhook(payload)` — Extracts event type from payload, calls matching handler.
  - `POST /webhooks/zoho` — Receives Zoho webhook POST. Returns `200 OK` immediately. Enqueues `_dispatch_webhook` as a background task.

---

### `security.py` (Path: `app/integrations/zoho/security.py`)

* **Purpose:** Payload hash generation for Zoho sync echo-loop prevention.
* **Dependencies & Links:** Python `hashlib`.
* **Mechanism / Core Logic:**
  - `generate_payload_hash(payload: dict) -> str` — Serialises payload dict to canonical JSON, computes SHA-256 hex digest. Used by both outbound and inbound sync paths to detect no-op updates.

---

### REPOSITORIES

---

### `base.py` (Path: `app/repositories/base.py`)

* **Purpose:** Generic repository base class implementing common CRUD operations via the Repository pattern.
* **Dependencies & Links:**
  - Internal: `app.core.database.Base`.
  - External: `sqlalchemy` (select, func, delete, AsyncSession).
  - Extended by: all domain-specific repositories.
* **Mechanism / Core Logic:**
  - `BaseRepository(Generic[ModelType])` — Accepts `model` class and `session` via constructor.
  - `get(id)` — Primary key lookup via `session.get()`.
  - `get_by_field(field_name, value)` — Dynamic field-based lookup.
  - `get_multi(skip, limit, order_by, filters)` — Paginated list with dynamic field filtering.
  - `count(filters)` — Count with optional filters.
  - `create(obj_in: dict)` — Instantiate model, add, flush, refresh.
  - `update(db_obj, obj_in: dict)` — Set attributes, flush, refresh.
  - `delete(id)` — Delete by PK.
  - `delete_multi(ids)` — Bulk delete via `DELETE ... WHERE pk IN (...)`.
  - `exists(id)` — Boolean existence check.

---

### `__init__.py` (Path: `app/repositories/user/__init__.py`)

* **Purpose:** User-specific repository with query methods beyond basic CRUD.
* **Dependencies & Links:**
  - Internal: `app.models` (User, UserRole), `app.repositories.base.BaseRepository`.
* **Mechanism / Core Logic:**
  - `UserRepository(BaseRepository[User])`:
    - `get_by_username(username)` — Query by unique username.
    - `get_by_email(email)` — Query by email.
    - `get_by_seatalk_id(seatalk_id)` — Query by SeaTalk employee code.
    - `get_active_users(skip, limit)` — Paginated active user list.
    - `get_by_role(role, skip, limit)` — Filter by UserRole.
    - `username_exists(username)` — Boolean uniqueness check.
    - `email_exists(email)` — Boolean uniqueness check.

---

### `__init__.py` (Path: `app/repositories/product/__init__.py`)

* **Purpose:** Product domain repositories for families, identities, and variants.
* **Dependencies & Links:**
  - Internal: `app.models.entities` (ProductFamily, ProductIdentity, ProductVariant, IdentityType), `app.repositories.base.BaseRepository`.
* **Mechanism / Core Logic:**
  - `ProductFamilyRepository(BaseRepository[ProductFamily])`:
    - `get_max_product_id()` — Find highest existing product_id (for auto-increment).
    - `get_with_identities(product_id)` — Eager-load identities relationship.
    - `search_by_name(query, skip, limit)` — Case-insensitive `ILIKE` search on `base_name`.
  - `ProductIdentityRepository(BaseRepository[ProductIdentity])`:
    - `get_by_upis_h(upis_h)` — Lookup by UPIS-H signature string.
    - `get_with_variants(id)` — Eager-load variants relationship.
    - `get_by_family(product_id, skip, limit)` — Filter identities by family.
    - `get_next_lci(product_id)` — Find max LCI for Parts in a family + 1.
  - `ProductVariantRepository(BaseRepository[ProductVariant])`:
    - Inherits all CRUD from BaseRepository.

---

### `__init__.py` (Path: `app/repositories/inventory/__init__.py`)

* **Purpose:** Repositories for bundle components, platform listings, and inventory items.
* **Dependencies & Links:**
  - Internal: `app.models.entities` (BundleComponent, InventoryItem, Platform, PlatformListing), `app.repositories.base.BaseRepository`.
* **Mechanism / Core Logic:**
  - `BundleComponentRepository(BaseRepository[BundleComponent])`:
    - `get_bundle_components(parent_identity_id)` — All components in a bundle.
    - `get_bundles_containing(child_identity_id)` — All bundles containing a component.
    - `component_exists(parent_identity_id, child_identity_id)` — Dedup check.
  - `PlatformListingRepository(BaseRepository[PlatformListing])`:
    - `get_by_variant_platform(variant_id, platform)` — Lookup by variant + platform.
    - `get_by_external_ref(platform, external_ref_id)` — Lookup by platform + external ID (used for auto-matching in order sync).

---

### `order_repository.py` (Path: `app/repositories/orders/order_repository.py`)

* **Purpose:** Order and OrderItem repositories for dashboard views, detail pages, and status tracking.
* **Dependencies & Links:**
  - Internal: `app.modules.orders.models` (Order, OrderItem, OrderItemStatus, OrderPlatform, OrderStatus), `app.repositories.base.BaseRepository`.
* **Mechanism / Core Logic:**
  - `OrderRepository(BaseRepository[Order])`:
    - `get_with_items(order_id)` — Load order with items and customer relationships.
    - `get_by_external_id(platform, external_order_id)` — Idempotent ingestion dedup lookup.
    - `list_orders(skip, limit, platform, status, item_status, search)` — Complex paginated query with optional filters for platform, order status, item-level status (e.g. items.status == UNMATCHED), and free-text search across order ID, customer name, and customer email.
  - `OrderItemRepository(BaseRepository[OrderItem])`:
    - `get_unmatched(skip, limit)` — Items needing SKU resolution.
    - `get_matched(skip, limit)` — Successfully matched items.
    - `count_by_status()` — `GROUP BY status` aggregation for dashboard counters.

---

### `sync_repository.py` (Path: `app/repositories/orders/sync_repository.py`)

* **Purpose:** IntegrationState management for the Safe Sync algorithm's state machine.
* **Dependencies & Links:**
  - Internal: `app.modules.orders.models` (IntegrationState, IntegrationSyncStatus), `app.repositories.base.BaseRepository`.
* **Mechanism / Core Logic:**
  - `SyncRepository(BaseRepository[IntegrationState])`:
    - `get_by_platform(platform_name)` — Get single platform state.
    - `get_all_states()` — Get all platform sync states.
    - `acquire_sync_lock(platform_name)` — Atomic `IDLE → SYNCING` transition. Auto-creates IntegrationState row if first sync. Returns `False` if already SYNCING/ERROR.
    - `release_sync_success(platform_name, sync_timestamp)` — `SYNCING → IDLE`, updates `last_successful_sync`.
    - `release_sync_error(platform_name, error_message)` — `SYNCING → ERROR`, stores error message.
    - `reset_to_idle(platform_name)` — Admin reset: any state → IDLE, clears error.

---

### TASKS

---

### `reconciliation.py` (Path: `app/tasks/reconciliation.py`)

* **Purpose:** Nightly Zoho reconciliation task that catches dropped webhooks by comparing Zoho's `last_modified_time` against local `updated_at`.
* **Dependencies & Links:**
  - Internal: `app.core.database.async_session_factory`, `app.integrations.zoho.client.ZohoClient`, `app.integrations.zoho.sync_engine` (inbound processors + outbound sync functions).
* **Mechanism / Core Logic:**
  - `_reconcile_items(zoho, since)` — Paginated fetch of Zoho items modified since `since`. For each item: finds matching ProductVariant by `zoho_item_id`. If variant is stale (Zoho modified after local update), re-enqueues inbound sync. If variant is newer, re-enqueues outbound sync.
  - `_reconcile_contacts(zoho, since)` — Same pattern for Customer ↔ Zoho Contact.
  - `_reconcile_salesorders(zoho, since)` — Same pattern for Order ↔ Zoho SalesOrder.
  - `run_reconciliation()` — Main entry point. Calculates `since` as 25 hours ago (covers daily + buffer). Runs all three reconciliation functions. Returns summary stats dict (items/contacts/orders checked + re-synced counts).

---

### SCRIPTS

---

### `backfill_variant_name_from_listings.py` (Path: `scripts/backfill_variant_name_from_listings.py`)

* **Purpose:** One-time backfill script that populates `product_variant.variant_name` from the shortest `platform_listing.listed_name`.
* **Dependencies & Links:** Direct SQLAlchemy session with `app.core.database`.
* **Mechanism / Core Logic:**
  - Scans all active ProductVariants.
  - For each, collects non-null `listed_name` values from associated PlatformListings.
  - Selects shortest name (tie-break alphabetically).
  - Updates `variant_name` if different from current value.
  - Reports `BackfillStats`: scanned, updated, skipped_no_listing_name, unchanged.

---

### `generate_hash.py` (Path: `scripts/generate_hash.py`)

* **Purpose:** CLI utility for generating bcrypt password hashes.
* **Dependencies & Links:** `passlib.context.CryptContext`.
* **Mechanism / Core Logic:**
  - `get_password_hash(password)` — Returns bcrypt hash.
  - `generate_hash_interactive()` — Interactive prompt mode.
  - `generate_hash_cli(password)` — Argument-based mode.
  - Validates password length (8-72 chars).

---

### `import_csv_to_database.py` (Path: `scripts/import_csv_to_database.py`)

* **Purpose:** Bulk product import pipeline parsing CSV files and populating the database via API endpoints.
* **Dependencies & Links:** `httpx`, `csv`, API endpoints.
* **Mechanism / Core Logic:**
  - `CSVRow` — Dataclass representing a parsed CSV row.
  - `ProductGroup` — Container for grouped product data (family, identities, variants, parts, bundles).
  - `APIClient` — HTTP client with authentication that calls API endpoints for families, identities, variants, listings, bundles, and LCI definitions.
  - `CSVImporter` — Main orchestrator: `load_csv()` parses and groups rows, `process_groups()` iterates groups and calls APIClient methods.
  - Handles automatic UPIS-H generation, LCI assignment, bundle component extraction, and deduplication.

---

### `test_api_manual.py` (Path: `scripts/test_api_manual.py`)

* **Purpose:** Manual API smoke test script for endpoint validation outside of pytest.
* **Dependencies & Links:** `httpx`.
* **Mechanism / Core Logic:**
  - `APITester` — Configurable HTTP client with logging.
  - `make_request(method, endpoint, json_data, expected_status, test_name)` — Generic request with status assertion.
  - Test methods for auth, families, identities — run sequentially and report pass/fail.

---

### `create_admin_user.sql` (Path: `scripts/create_admin_user.sql`)

* **Purpose:** SQL script to seed an initial admin user directly into the database.
* **Dependencies & Links:** Direct PostgreSQL execution.
* **Mechanism / Core Logic:** `INSERT INTO users` with pre-hashed bcrypt password, ADMIN role, `is_superuser=True`.

---

### TESTS

---

### `conftest.py` (Path: `tests/conftest.py`)

* **Purpose:** pytest configuration and fixtures for test database setup.
* **Dependencies & Links:**
  - Internal: `app.core.database` (Base, get_db), `app.main` (app).
  - External: `pytest`, `pytest-asyncio`, SQLAlchemy.
* **Mechanism / Core Logic:**
  - `event_loop()` — Session-scoped asyncio event loop fixture.
  - `test_db()` — Creates SQLite in-memory async engine, runs `Base.metadata.create_all`, yields, then drops all tables.
  - `db_session` — Per-test `AsyncSession` with `async_session_factory` bound to test engine.
  - `override_get_db()` — Dependency override injecting test session into FastAPI's `get_db`.

---

### `test_api.py` (Path: `tests/test_api.py`)

* **Purpose:** Comprehensive API endpoint test suite covering all major CRUD operations.
* **Dependencies & Links:**
  - Internal: `app.main.app`, schemas.
  - External: `httpx.AsyncClient`, `pytest`.
* **Mechanism / Core Logic:**
  - 8 test classes covering:
    - `TestAuthentication` — User creation, login flow, current user retrieval.
    - `TestProductFamilies` — Family CRUD with search.
    - `TestProductIdentities` — Identity creation (standard + Part with LCI).
    - `TestProductVariants` — Variant creation and listing.
    - `TestBundleComponents` — BOM relationship creation.
    - `TestPlatformListings` — Listing CRUD.
    - `TestInventoryItems` — Inventory item creation.
    - `TestErrorHandling` — Invalid input validation (404s, 422s).

---

### `test_parsers.py` (Path: `tests/integrations/test_parsers.py`)

* **Purpose:** Unit tests validating eBay and Ecwid JSON → ExternalOrder conversion logic.
* **Dependencies & Links:**
  - Internal: `app.integrations.ebay.client.EbayClient`, `app.integrations.ecwid.client.EcwidClient`, `app.integrations.base` (ExternalOrder, ExternalOrderItem).
* **Mechanism / Core Logic:**
  - Provides realistic JSON fixtures (`EBAY_ORDER_JSON`, `ECWID_ORDER_JSON`).
  - `TestEbayParser` — Tests: header extraction, shipping address parsing, pricing computation, line item conversion, timestamp handling, error handling for malformed data.
  - `TestEcwidParser` — Tests: header extraction, address parsing, pricing, item conversion, Unix timestamp parsing, error handling.

---

### `test_sync_service.py` (Path: `tests/modules/orders/test_sync_service.py`)

* **Purpose:** Unit tests for `OrderSyncService` with fully mocked repositories and platform clients.
* **Dependencies & Links:**
  - Internal: `app.modules.orders.service.OrderSyncService`, `app.integrations.base` (ExternalOrder, ExternalOrderItem).
  - External: `unittest.mock` (AsyncMock, patch).
* **Mechanism / Core Logic:**
  - Helper factories: `_make_external_order()`, `_make_order_item()`, `_make_order()`, `_make_session()`, `_make_service()`.
  - `TestSyncPlatform` — Tests: successful lock acquisition, order ingestion, deduplication (skipped duplicates), auto-matching via PlatformListing, error handling (lock failure, adapter exception), multi-order batch processing, state transition verification.

---

### `Dockerfile` (Path: `Dockerfile`)

* **Purpose:** Multi-stage Docker build for the backend API container.
* **Dependencies & Links:** `python:3.12-slim`, `libpq-dev` (build), `libpq5` (runtime).
* **Mechanism / Core Logic:**
  - **Builder stage:** Installs build deps, creates venv, installs all pip dependencies.
  - **Production stage:** Copies venv from builder, copies app source, exposes port 8080, runs via Uvicorn with 4 workers and `--proxy-headers` for reverse proxy support.

---

*Document generated: 2026-03-11*
