### **Module Specification: Order Synchronization & SKU Resolution**


### **1. Module Overview**

The goal of this module is to ingest orders from external platforms (Amazon, eBay, Ecwid), identify which internal inventory item (`PRODUCT_VARIANT`) corresponds to the sold item, and "teach" the system to recognize that relationship automatically in the future.

---

### **2. Database Integration Points**

* **Reads:** `PRODUCT_VARIANT` (to find items), `PLATFORM_LISTING` (to check for existing links).
* **Writes:** `PLATFORM_LISTING` (creating new links), `ORDER_TABLE` (updating status).

---

### **3. Functional Requirements (FR)**

#### **FR-01: Order Synchronization (The Trigger)**

* **Action:** User clicks "Sync Now".
* **System Logic:**
1. Fetch order JSON from API (Amazon/eBay/Ecwid) for timeframe `[Last Sync Time]` to `[Current Time]`.
2. **The Auto-Match Logic:** For each incoming order item, the system queries the `PLATFORM_LISTING` table:
* `SELECT variant_id FROM PLATFORM_LISTING WHERE external_ref_id = [Incoming Platform Item ID]`


3. **Result:**
* If Match Found: Tag order status as **SKU_AUTO_ASSIGNED**.
* If No Match: Tag order status as **SKU_UNASSIGNED**.





#### **FR-02: Order List View (The Dashboard)**

* **Display:** A table listing all synced orders.


* **Columns:** Order Date, Order Number, Platform, External Item title, Status, USAV SKU, Quantity, Ship by Date, Condition, Tracking Number, Note.

#### **FR-03: Review Auto-Assigned SKU (Validation)**

* **Input:** User selects an order with status **SKU_AUTO_ASSIGNED**.
* **Interface:** Display the "Incoming Item Name" side-by-side with the "Matched Internal Variant".
* **Actions:**
* **Confirm:** Validates the link. Order moves to Fulfillment flow.
* **Reject/Mark as Unassigned:** User clicks "Wrong Match". System removes the link for this specific order and changes status to **SKU_UNASSIGNED**. (Triggers the "Mark As Unassigned" path in flowchart).



#### **FR-04: Manual Matching (Search)**

* **Input:** User selects an order with status **SKU_UNASSIGNED**.
* **Interface:** A "Match SKU" modal/panel opens.
* **Search Function:**
* Search Bar queries `PRODUCT_FAMILY.base_name` and `PRODUCT_VARIANT.full_sku`.


* **Results Grid:** Displays `Base Name`, `Condition`, `Color`, `Full SKU`, `Current Inventory Count`.


---

### **4. User Interface (UI) Requirements**

#### **Screen A: The Order Grid**

* **Filter Tabs:** [All] | [Unassigned (Action Needed)] | [Auto-Assigned (Review)] | [Completed]
* **Action Column:** Button labeled "Resolve" (for Unassigned) or "Verify" (for Auto-Assigned).

#### **Screen B: The Resolution Modal (Split View)**

This modal appears when clicking "Resolve".

| **Left Side (The Ask)** | **Right Side (The Answer)** |
| --- | --- |
| **Incoming Order Data** | **Internal SKU Search** |
| Platform: eBay | Search Bar: `[ Type here... ]` |
| Item: "iPhone 12 Pro Max - Broken Screen" | **Results:** |
| Ext ID: `12345-eBay` | 1. iPhone 12 Pro Max (Space Gray, Used) |
| Price: $400 | 2. iPhone 12 Pro Max (Silver, New) |
|  | **[Button: Assign Selected]** |
|  | *Link: Can't find it? [Create New Product]* |

---

### **5. Logic Validation Table**

| Incoming Status | User Action | System Update | Next Step |
| --- | --- | --- | --- |
| **New Order** | Sync | Check `PLATFORM_LISTING` | Display in List |
| **Unassigned** | Search -> Select Variant | Insert into `PLATFORM_LISTING`; Update Order | Ready for Allocation |
| **Unassigned** | Search -> Create New | Insert `PRODUCT_VARIANT`; Insert `PLATFORM_LISTING` | Ready for Allocation |
| **Auto-Assigned** | Review -> Confirm | No DB Change (Link confirmed) | Ready for Allocation |
| **Auto-Assigned** | Review -> Reject | Remove temp link in view | Return to Unassigned |
