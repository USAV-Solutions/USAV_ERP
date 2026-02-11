### **Module Specification: Order Synchronization & SKU Resolution**

**Module ID:** MOD-002-ORD
**Related Procedure:** USAV-P005 / USAV-P003

### **1. Module Overview**

**Goal:**
To ingest orders from external platforms (Amazon, eBay, Ecwid) reliably using a **state-aware synchronization engine**, identify which internal inventory item (`PRODUCT_VARIANT`) corresponds to the sold item, and "teach" the system to automate this recognition for future orders.

**Target Users:**

* **Order Specialist:** Reviews incoming orders, resolves unassigned SKUs, and confirms auto-matches.
* **Warehouse Manager:** Monitors the flow of orders ready for allocation.

**Core Workflow:**

1. **Smart Ingest:** System checks the `INTEGRATION_STATE` log to determine the exact timestamp of the last successful sync for each platform.
2. **Fetch & Deduplicate:** Fetches orders from that timestamp (minus a safety buffer) and filters out duplicates.
3. **Auto-Match:** System links external Platform IDs to internal Variant IDs using `PLATFORM_LISTING`.
4. **Resolve & Learn:** Users manually match exceptions; the system saves these matches to automate future handling.

---

### **2. Database Schema Requirements**

#### **A. New Table: `INTEGRATION_STATE` (The Sync Memory)**

* *Purpose:* Tracks the "heartbeat" of each platform integration to ensure no orders are missed and to prevent redundant scanning.
* *Key Fields:*
* `platform_name` (PK) - Enum: 'Amazon', 'eBay', 'Ecwid'
* `last_successful_sync` (TIMESTAMP) - The crucial anchor for the next fetch.
* `current_status` (Enum: 'IDLE', 'SYNCING', 'ERROR') - Used to lock the "Sync" button in UI.
* `last_error_message` (TEXT) - Debugging info if a sync fails.



#### **B. New Table: `ORDER_HEADER**`

* *Purpose:* Stores the top-level details of a customer's order.
* *Key Fields:*
* `id` (PK)
* `platform_order_id` (e.g., "114-1234567-12345")
* `platform` (Enum: Amazon, eBay, Ecwid)
* `order_date`
* `total_amount`
* `sync_status` (Pending, Processed)


* **Crucial Constraint:** `UNIQUE(platform, platform_order_id)`
* *Reason:* Since our sync logic will overlap timeframes (to be safe), this DB constraint prevents duplicate orders from being created.



#### **C. New Table: `ORDER_ITEM**`

* *Purpose:* Individual line items; the workspace for SKU matching.
* *Key Fields:*
* `id` (PK)
* `order_id` (FK)
* `external_ref_id` (Raw Platform ID)
* `external_title`
* `quantity`
* `variant_id` (FK to `PRODUCT_VARIANT`)
* `sku_status` (Enum: **UNASSIGNED**, **AUTO_ASSIGNED**, **CONFIRMED**)



---

### **3. API Endpoints Specification**

#### **Category: Synchronization (System Action)**

| Method | Endpoint | Description |
| --- | --- | --- |
| **POST** | `/api/orders/sync` | **The Smart Trigger:** <br>

<br>1. Checks `INTEGRATION_STATE` for `last_successful_sync`.<br>

<br>2. Sets UI status to 'SYNCING'.<br>

<br>3. Fetches orders with a **10-minute overlap buffer**.<br>

<br>4. Inserts orders (ignoring duplicates via DB constraint).<br>

<br>5. Updates `INTEGRATION_STATE` timestamp only on success.<br>

<br>6. Returns count of *new* orders. |

#### **Category: Read & Dashboard (User View)**

| Method | Endpoint | Description |
| --- | --- | --- |
| **GET** | `/api/orders` | **The Dashboard:** Retrieves paginated orders. Includes filters for `sku_status` to help users focus on "UNASSIGNED" items. |
| **GET** | `/api/orders/{id}` | **Order Detail:** Full view of header and line items. |

#### **Category: Resolution & Matching (User Action)**

| Method | Endpoint | Description |
| --- | --- | --- |
| **GET** | `/api/products/search` | **The Search Tool:** Queries `PRODUCT_FAMILY` and `PRODUCT_VARIANT` by name/SKU/Color/Condition. |
| **POST** | `/api/orders/{item_id}/match` | **The Fix & Learn:** Updates `ORDER_ITEM` with a `variant_id` AND inserts a row into `PLATFORM_LISTING` to teach the Auto-Match engine. |
| **POST** | `/api/orders/{item_id}/confirm` | **The Verification:** Confirms `AUTO_ASSIGNED` matches. |
| **POST** | `/api/orders/{item_id}/reject` | **The Correction:** Rejects a bad match, resetting status to `UNASSIGNED`. |

#### **Category: Creation (Exception Handling)**

| Method | Endpoint | Description |
| --- | --- | --- |
| **POST** | `/api/products/create-match` | **The Shortcut:** Creates a new `PRODUCT_VARIANT` and immediately links it to the order item. |

---

### **4. Implementation Logic: The "Safe Sync" Workflow**

This logic must be implemented in the Backend service handling `/api/orders/sync`.

1. **Read State:**
* Query `INTEGRATION_STATE`. If `current_status` == 'SYNCING', abort (prevent double-clicks).
* Else, Set `current_status` = 'SYNCING'.
* Read `last_successful_sync`.


2. **Calculate Window:**
* `start_time` = `last_successful_sync` **minus 10 minutes**. (Safety buffer for API consistency).


3. **Fetch:**
* Call External APIs using `start_time`.


4. **Ingest & Deduplicate:**
* Iterate through fetched orders.
* Try to Insert into `ORDER_HEADER`.
* *Catch Exception:* If `UniqueViolation` (duplicate ID), skip this order (it was already synced in the overlap window).
* If New: Run **Auto-Match Logic** (Check `PLATFORM_LISTING`) -> Insert `ORDER_ITEM`.


5. **Update State:**
* If all successful: Update `INTEGRATION_STATE` set `last_successful_sync` = NOW(), `current_status` = 'IDLE'.
* If failed: Set `current_status` = 'ERROR', log message.



---

### **5. Overall Implementation Plan**

1. **Database Migration:**
* Create `INTEGRATION_STATE`, `ORDER_HEADER`, `ORDER_ITEM`.
* Seed `INTEGRATION_STATE` with default timestamps (e.g., start of year) for Amazon, eBay, Ecwid.


2. **Backend - State Manager:**
* Implement the "Safe Sync" logic (Read State -> Buffer -> Fetch -> Update State).


3. **Backend - Adapters:**
* Write specific API adapters for Amazon, eBay, Ecwid to normalize their JSON into our DB structure.


4. **Backend - Matching Logic:**
* Implement the "Match & Learn" endpoints (`/match`, `/confirm`).


5. **Frontend - Order Grid:**
* UI with "Sync Now" button that disables itself when `status === 'SYNCING'`.
* Visual badges for `SKU_UNASSIGNED` (Red) vs `AUTO_ASSIGNED` (Green).


6. **Frontend - Resolution Modal:**
* Split-view modal (Incoming Data vs. Internal Search).
