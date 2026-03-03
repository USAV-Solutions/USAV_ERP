# USAV Inventory System — Comprehensive Functional Summary

**Generated:** February 27, 2026  
**System Version:** 1.0.0  
**Architecture:** Hub & Spoke Middleware  
**Backend:** Python 3 / FastAPI / SQLAlchemy (async) / PostgreSQL 16  
**Frontend:** React / TypeScript / Vite / MUI  

---

## Table of Contents

1. [Inventory Management](#1-inventory-management)
2. [Product Listing Management](#2-product-listing-management)
3. [Order List Management](#3-order-list-management)
4. [Zoho Synchronization](#4-zoho-synchronization)
5. [Infrastructure & Deployment](#5-infrastructure--deployment)

---

## 1. Inventory Management

### 1.1 Architecture Philosophy

The system follows a **Hub & Spoke** model:

- **Hub (this system):** The single source of truth for product identity, physical inventory counts, and catalog data.
- **Spokes (Zoho, Amazon, eBay, Ecwid):** Downstream consumers that receive data updates. Sync direction is always `Internal DB → External Platform`.

### 1.2 Core Database Schema (Two-Layer Identification Model)

The schema implements a proprietary **UPIS-H (Unique Product Identity Signature – Human Readable)** specification with two distinct layers.

#### Layer 1 — Product Identity (The "Engineering" Layer)

| Table | Purpose | Key Fields |
|---|---|---|
| `product_family` | High-level grouping (e.g., "Bose 201 Series"). The 5-digit Ecwid product ID is the namespace root. | `product_id` (PK, 0–99999), `base_name`, `brand_id` (FK → `brand`), `description`, dimensions (`length`, `width`, `height`), `weight` |
| `product_identity` | Defines **what an item IS**. Immutable once created. | `product_id` (FK), `type` (Product / Bundle / Part / Kit), `lci` (Local Component Index, 1–99, required only for Parts), `generated_upis_h` (unique computed string, e.g. `00845-P-1`), `hex_signature` (immutable 32-bit HEX encoding) |

**Key constraints:**
- `UNIQUE(product_id, type, lci)` prevents duplicate identities.
- `lci` must be `NULL` for non-Part types (enforced via `CHECK` constraint).
- `hex_signature` is immutable: if product identity changes, a new row must be created.

#### Layer 2 — Product Variant (The "Sales" Layer)

| Table | Purpose | Key Fields |
|---|---|---|
| `product_variant` | Sellable configurations (Color + Condition) of an Identity. One Identity → Many Variants. | `identity_id` (FK), `color_code` (2-char, e.g. `BK`, `WY`), `condition_code` (`N` = New, `R` = Repair, `NULL` = Used), `full_sku` (unique, e.g. `00845-P-1-WY-N`), `variant_name`, `thumbnail_url`, `zoho_item_id`, `zoho_sync_status`, `is_active` (soft-delete) |

**Full SKU formula:** `{product_id}-{type}-{lci}-{color_code}-{condition_code}`

#### Lookup Tables

| Table | Purpose |
|---|---|
| `brand` | Brand/Manufacturer names (e.g., "Bose", "USAV Solutions") |
| `color` | Color names + 2-character codes (e.g., "Black" → `BK`) |
| `condition` | Condition names + 1-character codes (e.g., "New" → `N`) |
| `lci_definition` | Maps LCI numbers to component names per product family (e.g., LCI 1 = "Motherboard") |

#### Composition Table

| Table | Purpose | Key Fields |
|---|---|---|
| `bundle_component` | Bill of Materials for Bundles (type `B`) and Kits (type `K`). Links Identity ↔ Identity, not Variant. | `parent_identity_id`, `child_identity_id`, `quantity_required`, `role` (Primary / Accessory / Satellite) |

Self-referencing bundles are blocked via a `CHECK` constraint.

### 1.3 Physical Inventory Tracking

| Table | Purpose | Key Fields |
|---|---|---|
| `inventory_item` | Tracks individual physical units. Each row = one physical item in the warehouse. | `serial_number` (unique, optional), `variant_id` (FK), `status` (AVAILABLE / SOLD / RESERVED / RMA / DAMAGED), `location_code` (warehouse bin, e.g. `A1-S2`), `cost_basis` (acquisition cost for COGS), `received_at`, `sold_at` |

**Inventory status lifecycle:**
```
AVAILABLE → RESERVED → SOLD
              ↓
           DAMAGED / RMA
```

**Key API operations:**
- `POST /inventory/{id}/reserve` — Atomically moves AVAILABLE → RESERVED.
- `POST /inventory/{id}/sell` — Moves AVAILABLE or RESERVED → SOLD, stamps `sold_at`.
- `POST /inventory/{id}/release` — Moves RESERVED → AVAILABLE.
- `POST /inventory/{id}/rma` — Moves any status → RMA.
- `POST /inventory/receive` — Bulk-create inventory items for a variant (batch receiving).
- `POST /inventory/move` — Relocate items to a different `location_code`.
- `POST /inventory/audit` — Batch audit: set items to new status/location en masse.

**Summary endpoint:** `GET /inventory/summary` returns per-variant stock counts grouped by status, plus total portfolio valuation from `cost_basis`.

### 1.4 Data Deduplication Logic

Deduplication is enforced at **multiple layers**:

1. **Schema-level uniqueness constraints:**
   - `product_family.product_id` is the single PK (no two families share an Ecwid ID).
   - `product_identity` has `UNIQUE(product_id, type, lci)` — prevents creating the same Part twice under the same family.
   - `product_variant` has `UNIQUE(identity_id, color_code, condition_code)` — prevents duplicate sellable configs.
   - `platform_listing` has `UNIQUE(variant_id, platform)` — one listing per variant per platform.
   - `inventory_item.serial_number` is globally unique.

2. **Application-level deduplication for platform listings:**
   - When syncing orders, the system checks `platform_listing.external_ref_id` against the incoming item's platform ID, SKU, and item title (ILIKE fuzzy match) to avoid creating duplicate listings.
   - The "Match & Learn" workflow (`POST /orders/items/{id}/match` with `learn=true`) upserts a `platform_listing` row so the system auto-recognizes the same external product in future syncs.

3. **Cross-platform identity resolution:**
   - All external platforms map back to the same `product_variant` via the `platform_listing` table. Multiple external references (eBay Item ID, Amazon ASIN, Ecwid Product ID) can all point to one variant, effectively deduplicating the same physical product across sales channels.

---

## 2. Product Listing Management

### 2.1 Platform Listing Model

The `platform_listing` table acts as the **outbox pattern** for managing external platform data:

| Field | Description |
|---|---|
| `variant_id` | FK to internal `product_variant` |
| `platform` | Enum: `AMAZON`, `EBAY_MEKONG`, `EBAY_USAV`, `EBAY_DRAGON`, `ECWID` |
| `external_ref_id` | The ID on the remote platform (Zoho Item ID, ASIN, eBay Item ID, Ecwid Product ID) |
| `listed_name` | Product title as it appears on the platform |
| `listed_description` | Platform-specific description |
| `listing_price` | Platform-specific price |
| `sync_status` | `PENDING` → `SYNCED` → `ERROR` |
| `platform_metadata` | JSONB blob for platform-specific fields (e.g., Amazon Bullet Points, eBay Category ID) |

### 2.2 Listing API Workflows

| Endpoint | Action |
|---|---|
| `POST /api/v1/listings` | Create a new platform listing (triggers PENDING status) |
| `PUT/PATCH /api/v1/listings/{id}` | Update listing data. Setting `sync_status=SYNCED` auto-timestamps `last_synced_at`. |
| `GET /api/v1/listings/pending` | Fetch all listings needing sync (workers poll this) |
| `GET /api/v1/listings/errors` | Fetch listings with failed sync attempts |
| `POST /api/v1/listings/{id}/mark-synced` | Acknowledge successful external push |
| `GET /api/v1/listings/platform/{platform}/ref/{external_ref_id}` | Reverse-lookup: find internal variant from an external ID |

### 2.3 Sales Channel Integrations

All integrations implement the `BasePlatformClient` abstract interface, which standardizes:

```
authenticate()
fetch_orders(since, until, status) → List[ExternalOrder]
get_order(order_id) → ExternalOrder
update_stock(updates) → List[StockUpdateResult]
update_tracking(order_id, tracking, carrier) → bool
health_check() → bool
```

#### eBay (3 Stores)

- **Stores:** Mekong, USAV, Dragon — each has its own OAuth2 refresh token, all share a single eBay App ID and Cert ID.
- **Auth:** OAuth2 refresh token → access token exchange (2-hour expiry, auto-refreshed 5 minutes before expiry).
- **Order Fetch:** eBay Fulfillment API (`GET /sell/fulfillment/v1/order`) with date-range and status filters. Paginated at 200 orders/page.
- **Stock Push:** eBay Inventory API (`PUT /sell/inventory/v1/inventory_item/{sku}`) — *skeleton, not yet fully implemented.*
- **Tracking Update:** eBay Fulfillment API (`POST /sell/fulfillment/v1/order/{orderId}/shipping_fulfillment`) — *skeleton.*
- **Data Normalization:** `_convert_order()` maps eBay's JSON (pricing summary, fulfillment instructions, line items) to the standardized `ExternalOrder` dataclass.

#### Ecwid

- **Auth:** Simple Bearer token (store ID + access token).
- **Order Fetch:** Ecwid API (`GET /api/v3/{store_id}/orders`) with Unix timestamp range, payment status, and fulfillment status filters. Paginated at 100 orders/page. Handles HTTP 429 rate limits with 60-second backoff.
- **Stock Push:** `PUT /api/v3/{store_id}/products/{product_id}` to set `quantity`. Finds product by keyword search on SKU first. *Fully implemented.*
- **Tracking Update:** `PUT /api/v3/{store_id}/orders/{order_id}` with tracking number and carrier. *Fully implemented.*
- **Helper methods:** `fetch_daily_orders(date)`, `fetch_new_orders(fulfillment_status, payment_status, hours_back)`, `fetch_orders_since_last_sync()`.

#### Amazon

- **Auth:** SP-API with LWA (Login with Amazon) token exchange — *skeleton implementation, not yet connected to live API.*
- **All operations** (`fetch_orders`, `update_stock`, `update_tracking`) are stubbed with placeholder returns.
- **Data model** and `_convert_order()` logic are written and ready for SP-API integration.

### 2.4 Product Image Management

Product images are stored on the filesystem at `/mnt/product_images/` (Docker volume-mounted from the host).

**Directory structure:**
```
/mnt/product_images/
  └── {generated_upis_h}/           (e.g., 00845-P-1)
      └── {full_sku}/               (e.g., 00845-P-1-BK-N)
          ├── listing-0/
          │   ├── image1.jpg
          │   └── image2.jpg
          └── listing-1/
              └── image1.jpg
```

**Image selection logic ("Best Listing"):**
1. For each variant SKU directory, scan all `listing-{n}/` sub-directories.
2. Count image files (`.jpg`, `.jpeg`, `.png`, `.webp`) in each listing.
3. The listing with the most images is selected as the "best" listing.
4. Within that listing, images are sorted lexicographically; the first is the **thumbnail**.
5. The thumbnail URL is cached in `product_variant.thumbnail_url` for fast access.

**Serving strategy:**
- **Nginx direct serving** (production): `/product-images/` path is aliased to `/mnt/product_images/` with 1-day cache headers. Bypasses Python entirely.
- **API fallback**: `GET /api/v1/images/sku/{sku}` returns the image list and thumbnail URL via Python (used for metadata/gallery views).
- **Batch thumbnail computation**: `POST /api/v1/images/batch-thumbnails` pre-computes and stores thumbnail URLs for all variants.

---

## 3. Order List Management

### 3.1 Order Data Model

| Table | Purpose |
|---|---|
| `order` | Top-level order header imported from an external platform. Contains customer info, shipping address, financials, tracking, and raw platform data (JSONB). |
| `order_item` | Individual line items within an order. This is the **SKU-matching workspace**: `variant_id` starts `NULL` and gets populated via auto-match or manual match. |
| `integration_state` | One row per platform. Tracks the sync heartbeat: `current_status` (IDLE / SYNCING / ERROR), `last_successful_sync` (anchor timestamp), `last_error_message`. |

**Order status lifecycle:**
```
PENDING → PROCESSING → READY_TO_SHIP → SHIPPED → DELIVERED
                                          ↓
                                     CANCELLED / REFUNDED / ON_HOLD / ERROR
```

**Order item status lifecycle:**
```
UNMATCHED → MATCHED → ALLOCATED → SHIPPED
                          ↓
                      CANCELLED
```

### 3.2 The "Safe Sync" Engine (Order Ingestion)

The sync service (`OrderSyncService.sync_platform()`) implements a state-aware, idempotent ingestion workflow:

**Step 1 — Acquire Sync Lock:**
- Sets `integration_state.current_status` from `IDLE` → `SYNCING` for the target platform.
- If the platform is already `SYNCING` or in `ERROR`, the sync is rejected (prevents concurrent syncs).

**Step 2 — Calculate Fetch Window:**
- Reads `last_successful_sync` from `integration_state`.
- Subtracts a **10-minute overlap buffer** to catch orders that arrived during the previous sync's execution.
- If never synced before, defaults to January 1, 2026.

**Step 3 — Fetch Orders from External Platform:**
- Calls `client.fetch_orders(since=fetch_since)` on the platform-specific adapter (eBay, Ecwid, etc.).
- Each adapter normalizes its response into `List[ExternalOrder]` (a standard dataclass with customer, shipping, financial, and item data).

**Step 4 — Idempotent Ingestion:**
- For each `ExternalOrder`:
  - **Deduplication check:** `UNIQUE(platform, external_order_id)` constraint ensures orders are never double-inserted. The service also checks via `order_repo.get_by_external_id()` before insert.
  - Creates the `Order` row and all `OrderItem` rows.
  - Handles race conditions via `IntegrityError` catch.

**Step 5 — Auto-Match Items:**
For each `OrderItem`, the system attempts to automatically link it to an internal `product_variant` using a **three-tier fallback cascade**:

1. **External Item ID match:** Looks up `platform_listing.external_ref_id` matching the item's `platform_item_id`.
2. **External SKU match:** Falls back to looking up `platform_listing.external_ref_id` matching the item's `platform_sku`.
3. **Name match (fuzzy):** Falls back to `platform_listing.listed_name ILIKE '%{item_title}%'` for a case-insensitive substring match.

If any tier matches, the item is set to `MATCHED` with the corresponding `variant_id`. Otherwise, it remains `UNMATCHED`.

**Step 6 — Commit State:**
- On success: sets `integration_state.current_status` = `IDLE`, updates `last_successful_sync` to now.
- On failure: rolls back the transaction, sets `current_status` = `ERROR`, stores the error message.

**Admin Range Sync:**
- `POST /orders/sync/range` allows administrators to fetch orders within a custom date range without acquiring a sync lock or updating the anchor. Useful for backfilling historical orders.

### 3.3 SKU Resolution (Manual Matching)

| Endpoint | Action |
|---|---|
| `POST /orders/items/{item_id}/match` | **Match & Learn:** Links an order item to a `variant_id`. If `learn=true` (default), also upserts a `platform_listing` row so future items from the same external product auto-match. |
| `POST /orders/items/{item_id}/confirm` | Confirms an auto-matched item (no data change, status stays `MATCHED`). |
| `POST /orders/items/{item_id}/reject` | Rejects a bad auto-match: resets `variant_id` to `NULL` and status to `UNMATCHED`. Does not delete the `platform_listing` row. |

**The "Learn" mechanism in detail:**
When a manual match is made with `learn=true`:
1. Determine the `entity_platform` from the order's platform.
2. Check if a `platform_listing` already exists for the `variant_id` + `platform`. If so, enrich it with any missing `external_ref_id`, `listed_name`, or `listing_price`.
3. If no listing exists, also check by `external_ref_id` to avoid duplicate ref conflicts.
4. Create a new `PlatformListing` row mapping the variant to the platform with the item's external identifiers and name/price.
5. All operations are wrapped in `IntegrityError` catches for safe concurrency.

### 3.4 Order Dashboard API

| Endpoint | Description |
|---|---|
| `GET /orders` | Paginated order list with filters: `platform`, `status`, `item_status` (e.g., show only orders with UNMATCHED items), `search` (free-text). |
| `GET /orders/{id}` | Full order detail with all line items, matched variant data, and allocated inventory. |
| `PATCH /orders/{id}` | Update order status and/or processing notes. |
| `GET /orders/sync/status` | Dashboard overview: per-platform sync states + aggregate counters (total orders, total unmatched items, total matched items). |
| `POST /orders/sync/{platform}/reset` | Force-reset a stuck platform from ERROR/SYNCING back to IDLE. |

### 3.5 Order Item Image Handling

Order item images are **not** pulled separately from platforms. The eBay and Ecwid adapters include image URLs within the raw order item data stored in `order_item.item_metadata` (JSONB). The frontend reads these URLs directly for display in the order processing UI.

---

## 4. Zoho Synchronization

### 4.1 Overview

Zoho integration targets **Zoho Inventory** (item catalog and stock) and **Zoho Books** (financial). The USAV system is the **master**; Zoho is a downstream consumer.

### 4.2 Authentication

- **Method:** OAuth2 refresh token flow.
- **Token exchange:** `POST https://accounts.zoho.com/oauth/v2/token` with `client_id`, `client_secret`, `refresh_token`.
- **Token lifetime:** 1 hour; auto-refreshed 5 minutes before expiry.
- **Credentials:** `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_ORGANIZATION_ID` (env vars).

### 4.3 Data Payloads & API Calls

#### Standard Item Sync (`/items`)

Pushes a `product_variant` as a Zoho inventory item.

**Payload construction (`_build_item_payload`):**
```json
{
  "name": "<sanitized variant_name or base_name + SKU>",
  "sku": "<full_sku>",
  "description": "<family.description>",
  "product_type": "goods",
  "item_type": "inventory",
  "rate": "<listing_price from platform_listing, or 0>",
  "unit": "qty",
  "status": "active|inactive",
  "weight": "<family.weight>",
  "length": "<family.dimension_length>",
  "width": "<family.dimension_width>",
  "height": "<family.dimension_height>"
}
```

- **Create:** `POST /inventory/v1/items` with `JSONString` form data.
- **Update:** `PUT /inventory/v1/items/{zoho_item_id}` with `JSONString` form data.
- **Upsert logic:** `sync_item()` first calls `get_item_by_sku()` to check existence, then creates or updates accordingly.

#### Composite Item Sync (`/compositeitems`)

Pushes Bundles (type `B`) and Kits (type `K`) as Zoho composite items.

**Additional payload:** `component_items` array containing `{ "item_id": "<zoho_item_id>", "quantity": <qty> }` for each child component (looked up from `bundle_component` table → child variant's `zoho_item_id`).

- **Create:** `POST /inventory/v1/compositeitems`
- **Update:** `PUT /inventory/v1/compositeitems/{composite_item_id}`
- **Dependency ordering:** Non-composite variants are synced first so their `zoho_item_id` values are available when building composite payloads.

#### Image Upload

- **Endpoint:** `POST /inventory/v1/items/{zoho_item_id}/images`
- **Payload:** multipart file upload (`image` field).
- **Image resolution:** Uses the "Best Listing" algorithm (see §2.4). Falls back to cached thumbnail if no listing images exist.
- **All images** in the best listing folder are uploaded (not just the thumbnail).

#### Stock Adjustment

- **Endpoint:** `POST /inventory/v1/inventoryadjustments`
- **Payload:** Inventory adjustment with `line_items[].item_id`, `quantity_adjusted`, and optional `warehouse_id`.
- **Trigger:** Called when stock levels change in the USAV system.

#### Sales Order Forwarding

- **Endpoint:** `POST /inventory/v1/salesorders`
- **Payload:** Standard Zoho sales order JSON.
- **Status:** Method exists in the client but is not yet wired to an automated workflow.

### 4.4 Sync Triggers & Workflows

#### Single-Item Sync (On-Demand)
- **Trigger:** `POST /api/v1/zoho/sync/items/{variant_id}`
- **Who:** Admin user only.
- **Behavior:** Syncs one variant immediately. Respects `force_resync`, `include_images`, `include_composites` flags. Blocked if a bulk job is running.

#### Bulk Sync (Synchronous)
- **Trigger:** `POST /api/v1/zoho/sync/items`
- **Who:** Admin user only.
- **Behavior:** Queries all active variants where `zoho_sync_status IN (PENDING, DIRTY)` (or all if `force_resync=true`). Processes non-composite items first (populating `zoho_item_id`), then composite items. Limited by `limit` parameter.

#### Bulk Sync (Background Job)
- **Start:** `POST /api/v1/zoho/sync/items/start`
- **Progress:** `GET /api/v1/zoho/sync/items/progress` — returns live counters (`total_target`, `total_processed`, `total_success`, `total_failed`, `current_sku`).
- **Stop:** `POST /api/v1/zoho/sync/items/stop` — sets `cancel_requested=true`, job stops after the current item finishes.
- **Concurrency guard:** Only one bulk sync job can run at a time (in-memory `_JOB_LOCK`).

#### Readiness Report
- **Endpoint:** `POST /api/v1/zoho/sync/readiness`
- **Returns:** Per-variant diagnostic report listing missing fields (`identity`, `family`, `name`, `sku`, `bundle_components`) and warnings (`no_platform_listing_price`, `listing_price_is_zero`, `best_listing_and_thumbnail_missing_for_image_upload`). Categorizes each variant as `ok`, `warning`, or `error`.

### 4.5 Sync Status Tracking

Each `product_variant` row tracks its Zoho state:

| Field | Meaning |
|---|---|
| `zoho_sync_status` | `PENDING` (never synced), `SYNCED` (up-to-date), `ERROR` (last sync failed), `DIRTY` (local changes need push) |
| `zoho_item_id` | The Zoho item ID returned after successful create/update |
| `zoho_last_synced_at` | Timestamp of last successful sync |

When a variant's data changes locally, its status should be set to `DIRTY` to flag it for the next bulk sync run.

---

## 5. Infrastructure & Deployment

### 5.1 Hosting Environment

The system is deployed on a **self-hosted Proxmox virtualization environment**. Docker containers run on a Linux VM within the Proxmox cluster.

### 5.2 Docker Compose Architecture

The entire stack is orchestrated via a single `docker-compose.yml` with Docker Compose **profiles** for environment separation:

| Service | Container | Profile | Port | Description |
|---|---|---|---|---|
| PostgreSQL 16 | `usav_db` | *(always on)* | 5432 | `postgres:16-alpine` image. Named volume `postgres_data`. Health checks via `pg_isready`. |
| FastAPI Backend (prod) | `usav_backend` | `prod` | 8080 | Built from `Backend/Dockerfile`. Read-only mount of `/mnt/product_images`. |
| FastAPI Backend (dev) | `usav_backend_dev` | `dev` | 8080 | Same image but with `--reload` flag and source code volume-mounted for hot reload. |
| React Frontend (prod) | `usav_frontend` | `prod` | 3636 | Nginx serving static build. Proxies `/api/` to backend. Serves product images directly. |
| React Frontend (dev) | `usav_frontend_dev` | `dev` | 3636 | Vite dev server with HMR. Source code volume-mounted. |
| Database Migrations | `usav_migrations` | `migrate` | — | Runs `alembic upgrade head` once and exits. |
| Automatic Backups | `usav_backup` | *(always on)* | — | `prodrigestivill/postgres-backup-local` image. Daily schedule, 7-day/4-week/6-month retention. |
| pgAdmin | `usav_pgadmin` | `tools` | 5050 | Optional database management UI. |

### 5.3 Networking & Volumes

- **Network:** All services share a single bridge network (`usav_network`).
- **Volumes:**
  - `postgres_data` — Persistent database storage.
  - `pgadmin_data` — pgAdmin configuration.
  - `/mnt/product_images` — Host-mounted product image directory (read-only in containers).
  - `./backups` — Bind-mount for database backup files.

### 5.4 Database Migrations

- **Tool:** Alembic (async-compatible).
- **Strategy:** Sequential versioned migration files in `Backend/migrations/versions/`.
- **Current migrations:**
  1. `0001_initial_schema` — Core product tables, platform listings, inventory items.
  2. `0002_add_users` — User authentication tables.
  3. `0003_add_lookup_tables` — Brand, Color, Condition, LCI Definition.
  4. `0004_add_seatalk_id` — SeaTalk SSO integration fields.
  5. `0005_add_orders` — Order and OrderItem tables.
  6. `0006+` — Integration state, variant_name backfill, etc.

- **Execution:** `docker compose --profile migrate up migrations` runs once against the healthy database.

### 5.5 Authentication & Authorization

- **Method:** JWT Bearer tokens.
- **Login:** `POST /api/v1/auth/token` with username/password (OAuth2-compatible form).
- **Token:** HS256-signed JWT with `user_id`, `role`, `username` claims. 24-hour expiry.
- **Roles:** `admin` and standard user. Admin-only routes use an `AdminUser` dependency.
- **SSO:** SeaTalk OAuth integration for team login (app_id, app_secret, redirect URI configured via env vars).
- **Password:** bcrypt hashed. Change-password endpoint available.

### 5.6 Nginx Reverse Proxy (Production Frontend)

The production frontend container runs Nginx with:

| Location | Target | Caching |
|---|---|---|
| `/api/` | `proxy_pass http://backend:8080/api/` | None |
| `/health` | `proxy_pass http://backend:8080/health` | None |
| `/product-images/` | `alias /mnt/product_images/` (static file serving) | 1-day `Cache-Control` |
| `/api/v1/images/` | `proxy_pass http://backend:8080/api/v1/images/` (metadata) | 1-day proxy cache |
| `/` | SPA `try_files $uri /index.html` | — |
| Static assets (`.js`, `.css`, etc.) | Local dist files | 1-year immutable cache |

Gzip compression is enabled for text-based assets.

### 5.7 CI/CD & Deployment Workflow

Currently, deployment is **manual via Docker Compose commands**:

```bash
# Production
docker compose --profile prod up -d --build

# Development
docker compose --profile dev up -d

# Migrations only
docker compose --profile migrate up migrations

# Full reset (WARNING: drops data)
docker compose down -v && docker compose --profile prod up -d
```

The system does not currently have an automated CI/CD pipeline. Deployments are triggered by SSH-ing into the Proxmox VM and running Docker Compose commands directly.

### 5.8 Backup Strategy

- **Automated:** The `usav_backup` container runs `pg_dump` on a daily cron schedule.
- **Retention:** 7 daily + 4 weekly + 6 monthly backups.
- **Storage:** Backups are written to the `./backups` bind-mount on the host filesystem.
- **Manual restore:** Load a backup file via `psql` or `pg_restore` in the `usav_db` container.

### 5.9 Environment Configuration

All configuration is driven by environment variables (loaded from `.env` in development):

| Category | Key Variables |
|---|---|
| Database | `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME` |
| API | `API_PREFIX` (`/api/v1`), `CORS_ORIGINS`, `SECRET_KEY` |
| Zoho | `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_ORGANIZATION_ID` |
| eBay | `EBAY_APP_ID`, `EBAY_CERT_ID`, `EBAY_REFRESH_TOKEN_MEKONG/_USAV/_DRAGON`, `EBAY_SANDBOX` |
| Ecwid | `ECWID_STORE_ID`, `ECWID_SECRET` |
| Amazon | `AMAZON_CLIENT_ID`, `AMAZON_CLIENT_SECRET`, `AMAZON_REFRESH_TOKEN` |
| SeaTalk SSO | `SEATALK_APP_ID`, `SEATALK_APP_SECRET`, `SEATALK_REDIRECT_URI` |
| Images | `PRODUCT_IMAGES_PATH` (default: `/mnt/product_images`) |

---

## Appendix: API Route Summary

| Prefix | Module | Key Endpoints |
|---|---|---|
| `/api/v1/auth` | Authentication | `POST /token`, `GET /me`, `POST /me/change-password`, SeaTalk SSO flow |
| `/api/v1/families` | Product Families | CRUD, search by name |
| `/api/v1/identities` | Product Identities | CRUD, auto-generate UPIS-H and hex signature |
| `/api/v1/variants` | Product Variants | CRUD, search by name/SKU, filter by Zoho sync status |
| `/api/v1/bundles` | Bundle Components | CRUD, query components/parents |
| `/api/v1/listings` | Platform Listings | CRUD, pending/error queues, lookup by external ref |
| `/api/v1/inventory` | Physical Inventory | CRUD, reserve/sell/release/RMA, receive/move/audit, summary |
| `/api/v1/images` | Product Images | SKU image gallery, thumbnail, batch compute |
| `/api/v1/zoho` | Zoho Sync | Single/bulk/background sync, progress, stop, readiness report |
| `/api/v1/orders` | Order Management | Sync (safe + range), CRUD, match/confirm/reject items, dashboard |
| `/api/v1/brands` | Brand Lookup | CRUD |
| `/api/v1/colors` | Color Lookup | CRUD |
| `/api/v1/conditions` | Condition Lookup | CRUD |
| `/api/v1/lci-definitions` | LCI Lookup | CRUD |
