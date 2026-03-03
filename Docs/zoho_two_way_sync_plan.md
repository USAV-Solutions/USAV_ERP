# ZOHO TWO-WAY SYNC IMPLEMENTATION

**Context:** You are tasked with implementing a robust, asynchronous two-way synchronization engine between a custom FastAPI/SQLAlchemy/Postgres backend and Zoho Inventory.

**Current State:** The system currently has a manual, one-way "create" sync for products (USAV -> Zoho). This existing API client logic should be preserved and wrapped into the new asynchronous queue architecture.

**Architecture Rules:**

1. **Async First:** All database operations (SQLAlchemy 2.0) and HTTP requests (`httpx`) must be asynchronous.
2. **Queue-Based:** No synchronous API calls to Zoho inside HTTP request-response cycles or database transactions. Use a background task queue (assume Redis + ARQ or Celery).
3. **Echo-Loop Prevention:** Mandatory use of payload hashing (`zoho_last_sync_hash`) and transient SQLAlchemy flags (`_updated_by_sync`) to prevent infinite webhook loops.
4. **Soft Deletes:** Hard deletes are forbidden. Use `is_active` booleans mapped to Zoho's `inactive` status.
5. **Strict Dependencies:** An `Order` cannot be synced to Zoho unless its linked `Customer` AND all of its constituent `ProductVariant` line items already have their respective Zoho IDs.

Please execute the implementation in the following sequential phases.

---

### PHASE 1: Database & Model Foundation

**Goal:** Prepare the database schema to track synchronization state and introduce the Customer entity.

1. **Create a `ZohoSyncMixin`:**
* Create a SQLAlchemy mixin to be inherited by `ProductVariant`, `Customer`, and `Order` models.
* Add columns: `zoho_id` (String, nullable, indexed), `zoho_last_sync_hash` (String, nullable), `zoho_last_synced_at` (DateTime, nullable), `zoho_sync_error` (Text, nullable).
* Implement a transient `_updated_by_sync` boolean property (not mapped to DB) to bypass outbound syncs during webhook processing.


2. **Implement the `Customer` Model:**
* Create a `Customer` table storing standard contact information (Name, Email, Phone, Address, `is_active`).
* Inherit the `ZohoSyncMixin`.


3. **Update the `Order` Model:**
* Add a foreign key linking `Order` to `Customer`.
* Ensure `ProductVariant` has an `is_active` (Boolean, default=True) column for soft deletes.



### PHASE 2: Core Engine & Security

**Goal:** Build the unified utilities that Items, Customers, and Orders will share.

1. **Hash Generator (`app/integrations/zoho/security.py`):**
* Write a deterministic hashing function `generate_payload_hash(payload: dict) -> str` using hashlib (MD5 or SHA256). It must sort dictionary keys before hashing.


2. **Zoho API Client Refactor (`app/integrations/zoho/client.py`):**
* Retain the existing one-way item creation logic.
* Ensure all `POST` and `PUT` methods use the `data={"JSONString": json.dumps(payload)}` format (URL-encoded).
* Implement missing methods: `update_item`, `create_contact`, `update_contact`, `create_salesorder`, `update_salesorder`, and status endpoint toggles (e.g., `mark_inactive`).


3. **Webhook Router (`app/integrations/zoho/webhooks.py`):**
* Create a FastAPI router with a single `POST /webhooks/zoho` endpoint.
* Parse the `event_type` from the Zoho payload and instantly enqueue it to the Redis broker, returning `200 OK`.



### PHASE 3: Item & Customer (Entity) Sync

**Goal:** Implement the bidirectional data flow for base entities (`ProductVariant` <-> `Item`, `Customer` <-> `Contact`).

1. **Outbound Sync (SQLAlchemy -> Queue -> Zoho):**
* Write SQLAlchemy `after_insert` and `after_update` event listeners for `ProductVariant` and `Customer`.
* *Logic:* If `_updated_by_sync == True`, exit. Hash relevant fields. Compare to `zoho_last_sync_hash`. If match, exit. Else, enqueue the respective task (`sync_item_outbound` or `sync_customer_outbound`).
* *Worker Task:* Fetch entity. Call `ZohoClient`. Update `zoho_last_sync_hash` and `zoho_last_synced_at` on success. (Note: Refactor the existing manual item sync into this worker).


2. **Inbound Sync (Zoho Webhook -> Queue -> SQLAlchemy):**
* *Worker Task:* `process_entity_inbound_task(payload, entity_type)`.
* Hash payload -> Check against DB -> If match, exit.
* Update local database. **CRITICAL:** Set `entity._updated_by_sync = True` before committing the session. Update `zoho_last_sync_hash`.



### PHASE 4: Order Sync & List Pulling

**Goal:** Implement the complex bidirectional data flow for `Order` <-> `SalesOrder`.

1. **Order Outbound Sync (Dependency Aware):**
* Write SQLAlchemy listeners for `Order`. Enqueue `sync_order_outbound_task(order_id)`.
* *Worker Task:* Fetch the `Order`, eagerly loading the `Customer` and all `OrderItem`s.
* *Dependency Check:* * If `Customer.zoho_id` is missing, pause order sync, trigger `sync_customer_outbound`, and requeue the order task with a delay.
* If any `ProductVariant.zoho_id` is missing, pause order sync, trigger `sync_item_outbound` for those items, and requeue.


* *Mapper:* Translate USAV Order + Customer data into Zoho SalesOrder JSON. Calculate hash. Push via `ZohoClient`. Update tracking columns.


2. **Order Inbound Sync & List Pulling Updates:**
* *Webhook Worker:* `process_order_inbound_task(payload)`. Apply Echo Loop prevention. Update local order status (e.g., Draft -> Shipped).
* *Order List Pulling Update:* Modify the existing order fetching logic (the function retrieving orders for the frontend/admin panel) to properly join and serialize the new `Customer` information, ensuring contact details are always visible on the order list.



### PHASE 5: Fallback Reconciliation

**Goal:** Catch dropped webhooks or failed queue jobs.

1. **Nightly Sync Script (`app/tasks/reconciliation.py`):**
* Write a Celery Beat/Cron script.
* Fetch items, contacts, and salesorders from Zoho modified in the last 24 hours (`GET /{endpoint}?last_modified_time=...`).
* Compare Zoho's `last_modified_time` against Postgres' `updated_at`. Force enqueue sync tasks to resolve discrepancies.
