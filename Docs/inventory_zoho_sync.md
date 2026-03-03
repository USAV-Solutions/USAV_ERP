### **Phase 1: Database & Model Preparation**

Before data can flow in both directions, the database must be able to track the state of the sync and prevent infinite "echo loops."

1. **Implement Soft Deletes:** Add an `is_active` (Boolean) column to your `ProductVariant` table. Update your API queries to filter out inactive items instead of hard-deleting rows.
2. **Add Sync Tracking Columns:**
* `zoho_item_id` (String): The primary key linking to Zoho.
* `zoho_last_sync_hash` (String): An MD5 hash of the payload sent to/received from Zoho. This is your primary defense against echo loops.
* `zoho_last_synced_at` (Datetime): Timestamp of the last successful sync.


3. **Add a "Sync Context" Flag:** Create a session-level flag or a transient attribute on your SQLAlchemy model (e.g., `_updated_by_sync = True`). This tells your database listeners: *"This update came from Zoho, do not push it back to Zoho."*

### **Phase 2: The Asynchronous Task Queue**

Two-way syncs cannot happen inside standard HTTP request cycles. You need a background worker to handle retries and rate limits.

1. **Choose a Broker:** Set up Redis and a Python task queue like Celery, ARQ (Async Redis Queue), or RQ.
2. **Configure Retries:** Configure the worker to automatically retry tasks with exponential backoff if Zoho returns a `429 Too Many Requests` or `5xx Server Error`.
3. **Define the Queues:** Create two distinct queues:
* `outbound_sync`: High priority (USAV -> Zoho).
* `inbound_sync`: Standard priority (Zoho -> USAV).



### **Phase 3: Outbound Sync (USAV ➔ Zoho)**

This pushes internal changes to Zoho instantly.

1. **The Trigger:** Attach SQLAlchemy `after_insert` and `after_update` event listeners to the `ProductVariant` model.
2. **The Filter (Echo Loop Prevention):** Inside the listener, check two things:
* Is `_updated_by_sync == True`? If yes, exit immediately.
* Generate a hash of the current item data (Name, SKU, Rate, Description, is_active). Does it match `zoho_last_sync_hash`? If yes, exit immediately (no actual data changed).


3. **Dispatch:** If the data is new, send the `variant_id` to the `outbound_sync` queue.
4. **The Worker:** The worker fetches the variant, formats the `JSONString` payload, calls `ZohoClient.sync_item()`, and upon success, updates the `zoho_last_sync_hash` and `zoho_last_synced_at` in the database.
* *Note on Deletions:* If `is_active == False`, the worker calls the Zoho endpoint to mark the item as `inactive`.



### **Phase 4: Inbound Sync (Zoho ➔ USAV)**

This captures changes made by users directly inside the Zoho UI.

1. **Configure Webhooks in Zoho:** In the Zoho Inventory settings, set up webhooks for `Item - Created`, `Item - Edited`, and `Item - Deleted/Inactive`. Point them to a new endpoint: `POST /api/v1/webhooks/zoho/items`.
2. **The Webhook Receiver:** * FastAPI receives the payload.
* Immediately dispatches the raw payload to the `inbound_sync` queue.
* Returns a `200 OK` to Zoho instantly. (Zoho will disable your webhook if it takes too long to respond).


3. **The Worker:**
* Parses the Zoho payload.
* Calculates the payload hash. Compares it against the database's `zoho_last_sync_hash`. If it matches, the worker terminates (this breaks the echo loop).
* Updates the `ProductVariant` in the database. **Crucially**, it injects the `_updated_by_sync = True` flag into the SQLAlchemy session so Phase 3 isn't triggered.
* Updates the `zoho_last_sync_hash` to the new value.



### **Phase 5: The Nightly Reconciliation (The Safety Net)**

Webhooks drop. Servers restart. Queues fail. You need a fallback to ensure perfect parity.

1. **The Cron Job:** Schedule a daily task (e.g., at 2:00 AM) using Celery Beat or a standard cron scheduler.
2. **The Fetch:** The job calls `GET /items?last_modified_time={last_24_hours}` via your `ZohoClient`.
3. **The Compare & Merge:** It loops through the returned items, comparing the `last_modified_time` of the Zoho item against the `updated_at` of your Postgres item.
* If Zoho is newer: Update Postgres.
* If Postgres is newer: Queue an outbound sync to Zoho.



---
