# Zoho Two-Way Sync — System Summary

## Overview

The system implements a bidirectional sync engine between the USAV PostgreSQL database and Zoho Inventory/Books. It synchronizes three entity types:

| Local Entity | Zoho Entity | Key File(s) |
|---|---|---|
| `ProductVariant` | Item | `Backend/app/integrations/zoho/sync_engine.py` |
| `Customer` | Contact | `Backend/app/integrations/zoho/sync_engine.py` |
| `Order` | SalesOrder | `Backend/app/integrations/zoho/sync_engine.py` |

---

## Database Foundation

### Sync-Tracking Columns

Every synced entity carries these columns (via `ZohoSyncMixin` in `Backend/app/models/entities.py` or directly on `ProductVariant`):

| Column | Purpose |
|---|---|
| `zoho_id` / `zoho_item_id` | The Zoho-side record ID |
| `zoho_last_sync_hash` | SHA-256 hash of the last synced payload — used for **echo-loop prevention** and **skip-if-unchanged** |
| `zoho_last_synced_at` | Timestamp of last successful sync |
| `zoho_sync_error` | Error message from last failed attempt |
| `zoho_sync_status` | Enum: `PENDING`, `SYNCED`, `ERROR`, `DIRTY` |

### Echo-Loop Prevention Flag

Each entity has a **transient** (non-persisted) property `_updated_by_sync`. When set to `True`, it signals that the current write originated from an inbound sync — the SQLAlchemy event listener will skip re-enqueuing an outbound sync, breaking the loop.

---

## Data Flow: Two Directions

### OUTBOUND (USAV → Zoho) — Automatic

**Trigger:** SQLAlchemy `after_insert` / `after_update` event listeners, registered at app startup by `register_sync_listeners()` in `sync_engine.py`.

**Flow:**

1. A `ProductVariant`, `Customer`, or `Order` is **created or updated** in the database (via any API endpoint, import script, etc.).
2. SQLAlchemy fires the `after_insert` or `after_update` event.
3. The listener function checks `target._updated_by_sync`:
   - If `True` → **skip** (this write came from an inbound sync — no echo).
   - If `False` → enqueue a background task.
4. The enqueue helper (`_enqueue_variant_sync`, `_enqueue_customer_sync`, `_enqueue_order_sync`) calls `asyncio.create_task()` to schedule the outbound worker.
5. The outbound worker runs:

| Entity | Worker Function | What It Does |
|---|---|---|
| ProductVariant | `sync_variant_outbound(variant_id)` | Loads variant + identity + family + listings, builds payload via `variant_to_zoho_payload()`, hashes it, compares to `zoho_last_sync_hash`. If unchanged → skip. Otherwise calls `ZohoClient.sync_item()` (which does GET by SKU → create or update). Stores the returned `zoho_item_id`, updates hash/timestamp. |
| Customer | `sync_customer_outbound(customer_id)` | Builds payload via `customer_to_zoho_payload()`, hashes, compares. If customer has no `zoho_id` but has email → tries `get_contact_by_email()` first. Then creates or updates. Also handles `is_active` → calls `mark_contact_active/inactive`. On "already exists" error → resolves by email/name lookup. |
| Order | `sync_order_outbound(order_id)` | **Dependency-aware**: Checks if `Customer.zoho_id` exists — if not, triggers `sync_customer_outbound()` first. Checks if all line-item `ProductVariant.zoho_item_id` exist — if not, triggers `sync_variant_outbound()` for each. Then builds payload via `order_to_zoho_payload()`, does duplicate-check (scans existing salesorders by `reference_number`), creates or updates. |

**Zoho Client methods called:**

| Action | Client Method | API Call |
|---|---|---|
| Create item | `create_item()` | POST `/items` |
| Update item | `update_item()` | PUT `/items/{id}` |
| Find item by SKU | `get_item_by_sku()` | GET `/items?sku=...` |
| Smart create-or-update | `sync_item()` | Combines above |
| Create contact | `create_contact()` | POST `/contacts` |
| Update contact | `update_contact()` | PUT `/contacts/{id}` |
| Create sales order | `create_sales_order()` | POST `/salesorders` |
| Update sales order | `update_salesorder()` | PUT `/salesorders/{id}` |
| Soft-delete toggles | `mark_item_inactive/active()`, `mark_contact_inactive/active()` | POST `/items/{id}/inactive` etc. |

---

### INBOUND (Zoho → USAV) — Via Webhooks

**Trigger:** Zoho sends a POST to `/webhooks/zoho` (defined in `Backend/app/integrations/zoho/webhooks.py`).

**Flow:**

1. The endpoint parses the JSON body, extracts `event_type`, returns `200 OK` immediately.
2. The payload is dispatched to a background task via `FastAPI.BackgroundTasks`.
3. The `_dispatch_webhook()` function looks up the registered handler by `event_type`.

**Registered handlers** (set up in `Backend/app/main.py` during lifespan startup):

| Event Type | Handler |
|---|---|
| `item.created` | `process_item_inbound()` |
| `item.updated` | `process_item_inbound()` |
| `contact.created` | `process_contact_inbound()` |
| `contact.updated` | `process_contact_inbound()` |
| `salesorder.created` | `process_order_inbound()` |
| `salesorder.updated` | `process_order_inbound()` |

**Inbound worker logic:**

| Entity | Worker | Behavior |
|---|---|---|
| Item → ProductVariant | `process_item_inbound()` | Looks up variant by `zoho_item_id` or `full_sku`. Hashes incoming payload → if matches `zoho_last_sync_hash`, skip. Otherwise updates `variant_name`, `is_active` (maps Zoho `status`). Sets `_updated_by_sync = True` before commit. |
| Contact → Customer | `process_contact_inbound()` | Looks up by `zoho_id`. If not found → **creates a new Customer** locally from the Zoho data (via `zoho_contact_to_customer_fields()`). If found → hash-check → updates fields. Sets `_updated_by_sync = True`. |
| SalesOrder → Order | `process_order_inbound()` | Looks up by `zoho_id`. Only updates **status** (maps Zoho statuses like `draft`→`PENDING`, `shipped`→`SHIPPED`, `void`→`CANCELLED`). Does NOT overwrite line items. Sets `_updated_by_sync = True`. |

---

## Manual Sync Flow (Force Sync)

Exposed via `Backend/app/modules/sync/endpoints.py` under the `/api/v1/sync` prefix. **Requires admin authentication.**

| Endpoint | Method | Handler |
|---|---|---|
| `POST /sync/items/{variant_id}` | Force-sync a variant | Validates entity exists + is active, then calls `sync_variant_outbound()` via `BackgroundTasks` |
| `POST /sync/orders/{order_id}` | Force-sync an order | Validates entity exists, then calls `sync_order_outbound()` via `BackgroundTasks` |
| `POST /sync/customers/{customer_id}` | Force-sync a customer | Validates entity exists, then calls `sync_customer_outbound()` via `BackgroundTasks` |

All return **202 Accepted** immediately. The actual sync happens in the background using the **same outbound worker functions** as the automatic flow. The difference: manual sync is user-initiated and bypasses the SQLAlchemy event listener path (it calls the worker directly).

---

## Auto Sync vs Manual Sync — Key Differences

| Aspect | Auto Sync | Manual Sync (Force Sync) |
|---|---|---|
| **Trigger** | SQLAlchemy `after_insert`/`after_update` event listener | Admin user hits `POST /sync/{entity}/{id}` |
| **Entry point** | `_on_variant_after_write` / `_on_customer_after_write` / `_on_order_after_write` | `force_sync_item` / `force_sync_order` / `force_sync_customer` |
| **How it queues** | `asyncio.create_task()` (fire-and-forget in-process) | `FastAPI.BackgroundTasks.add_task()` |
| **Worker called** | Same: `sync_variant_outbound` / `sync_customer_outbound` / `sync_order_outbound` | Same |
| **Skip-if-unchanged** | Yes (hash comparison) | Yes (hash comparison — still applies) |
| **Echo-loop check** | Yes (`_updated_by_sync` flag) | N/A (not triggered from webhook path) |
| **Auth required** | No (automatic on any DB write) | Yes (AdminUser dependency) |
| **Validation** | None (any committed entity triggers it) | Checks entity exists; items must be `is_active` |

---

## Deletes (Soft-Delete Model)

Hard deletes are **forbidden**. The system uses soft-deletes:

- **USAV → Zoho:** When a `Customer` with `is_active=False` is synced outbound, `sync_customer_outbound()` calls `ZohoClient.mark_contact_inactive()`. When `is_active=True`, it calls `mark_contact_active()`.
- **Zoho → USAV:** When an inbound item webhook has `status: "inactive"`, `process_item_inbound()` sets `variant.is_active = False`. When `status: "active"`, it sets `is_active = True`.

---

## Echo-Loop Prevention (Critical Mechanism)

Prevents the infinite cycle: USAV updates record → pushes to Zoho → Zoho fires webhook → USAV updates record → pushes to Zoho → ...

**Two layers:**

1. **Payload Hash (`zoho_last_sync_hash`):** Every outbound push and inbound webhook hashes the payload using `generate_payload_hash()` (in `Backend/app/integrations/zoho/security.py`). If the hash matches what's stored, the operation is skipped entirely.

2. **Transient flag (`_updated_by_sync`):** All inbound handlers set `entity._updated_by_sync = True` before committing. The SQLAlchemy `after_update` listener checks this flag and exits early if it's `True`, preventing an outbound sync from being enqueued.

---

## Nightly Reconciliation (Fallback)

Defined in `Backend/app/tasks/reconciliation.py`. Catches dropped webhooks or failed background tasks.

**How it works:**

1. Fetches all items, contacts, and salesorders modified in Zoho in the last **25 hours** (via `list_items`/`list_contacts`/`list_salesorders` with `last_modified_time` filter).
2. For each Zoho record, finds the corresponding local record.
3. Hashes the Zoho payload and compares to `zoho_last_sync_hash`.
4. If hashes differ → compares `last_modified_time` (Zoho) vs `updated_at` (local):
   - **Zoho is newer** → enqueue inbound sync (`process_item_inbound`, etc.)
   - **Local is newer** → enqueue outbound sync (`sync_variant_outbound`, etc.)
   - **Fallback** (can't parse timestamps) → treats Zoho as source of truth (inbound)
5. If a Zoho record has no local match → creates it via inbound sync.

**Entry point:** `run_reconciliation()` — can be run as a standalone script (`python -m app.tasks.reconciliation`) or scheduled via cron/Celery Beat.

---

## Authentication & API Client

The `ZohoClient` (`Backend/app/integrations/zoho/client.py`) uses **OAuth2 refresh-token flow**:

- Tokens are cached class-wide (`_shared_access_token`) with a lock to prevent concurrent refreshes.
- Tokens auto-refresh 5 minutes before expiry (55-minute lifetime vs Zoho's 60-minute expiry).
- All payloads are sent as `data={"JSONString": json.dumps(payload)}` (URL-encoded format Zoho expects).
- Rate limiting (HTTP 429 or "too many requests" in 400 body) raises `RateLimitError` with `retry_after` seconds.
- On 401, automatically refreshes token and retries once.

---

## Complete Method Call Chains

### Example: A product variant is updated via the API

```
API endpoint updates ProductVariant in DB
  → SQLAlchemy after_update fires
    → _on_variant_after_write() checks _updated_by_sync (False)
      → _enqueue_variant_sync(variant_id)
        → asyncio.create_task(sync_variant_outbound(variant_id))
          → Loads variant with identity/family/listings
          → variant_to_zoho_payload() builds payload
          → generate_payload_hash() → compares with zoho_last_sync_hash
          → ZohoClient.sync_item(sku, name, rate, ...)
            → get_item_by_sku(sku) — if exists → update_item(), else → create_item()
          → Stores zoho_item_id, updates hash/timestamp/status
```

### Example: Zoho sends a contact webhook

```
POST /webhooks/zoho {event_type: "contact.updated", contact: {...}}
  → receive_zoho_webhook() returns 200 immediately
    → BackgroundTasks → _dispatch_webhook("contact.updated", payload)
      → process_contact_inbound(payload)
        → Extracts contact_data, zoho_contact_id
        → generate_payload_hash() → compares with zoho_last_sync_hash
        → zoho_contact_to_customer_fields() maps Zoho → Customer fields
        → Updates Customer, sets _updated_by_sync = True
        → Commits → after_update fires → sees _updated_by_sync=True → SKIPS outbound
```

### Example: An order is force-synced by an admin

```
POST /api/v1/sync/orders/42 (admin auth required)
  → force_sync_order() validates order exists
    → BackgroundTasks.add_task(sync_order_outbound, 42)
      → Loads Order with Customer + OrderItems + Variants
      → Dependency check: Customer.zoho_id missing?
        → Yes → sync_customer_outbound(customer_id) runs first
      → Dependency check: any Variant.zoho_item_id missing?
        → Yes → sync_variant_outbound(variant_id) for each
      → order_to_zoho_payload() builds SalesOrder payload
      → generate_payload_hash() → compares with zoho_last_sync_hash
      → ZohoClient.create_sales_order() or update_salesorder()
      → Stores zoho_id, updates hash/timestamp/status
```

---

## File Reference

| File | Purpose |
|---|---|
| `Backend/app/integrations/zoho/sync_engine.py` | Core sync engine: outbound workers, inbound handlers, payload mappers, SQLAlchemy event listeners |
| `Backend/app/integrations/zoho/client.py` | Zoho REST API client (OAuth2, all CRUD methods) |
| `Backend/app/integrations/zoho/webhooks.py` | Webhook receiver endpoint + dispatcher |
| `Backend/app/integrations/zoho/security.py` | Deterministic payload hashing (`generate_payload_hash`) |
| `Backend/app/modules/sync/endpoints.py` | Manual force-sync API endpoints |
| `Backend/app/tasks/reconciliation.py` | Nightly reconciliation task |
| `Backend/app/models/entities.py` | `ZohoSyncMixin`, `ZohoSyncStatus` enum, entity models |
| `Backend/app/modules/orders/models.py` | `Order` model with Zoho sync columns |
| `Backend/app/main.py` | App startup: registers listeners + webhook handlers |
