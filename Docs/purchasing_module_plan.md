**Objective:** To align the current Vietnam team's `inventory_system` deployment with the proposed Receiving & Inventory System architecture, ensuring a reliable workflow that eliminates the "gray zone" between receiving and stock availability.

---

## 1. System Overview: `inventory_system`
Currently, we have developed and deployed a custom internal application (temporarily named `inventory_system`) that can be accessed through seatalk. Rather than relying solely on Zoho as the single source of truth, our architecture utilizes a **co-source-of-truth model** bridging our system and Zoho. 

**Key Capabilities & Features:**
* **Two-Way Synchronization:** The system currently handles two-way syncing for inventory items, and is being actively expanded to include two-way synchronization for both purchasing orders and sales orders.
* **Automated Order Tracking:** It automatically pulls order data and tracking information from sources like eBay and Ecwid, with active development to pull Amazon orders via Zoho's native integration.

---

## 2. Justification
While the proposed plan suggests Zoho handles all PO creation, our current implementation splits the workload to maximize automation capabilities.

### System Responsibilities
* **`inventory_system`:** Handles the Creation, Read, Update, and Deletion (CRUD) of items, vendors, orders, and purchases.
* **Zoho:** Takes over downstream responsibilities, specifically the receiving workflow at the dock, accounting (matching bills to POs), and reporting.

### Why CRUD Lives in `inventory_system`
The primary driver for this architecture is **automation speed and tracking number acquisition**. Most of our current purchasing sources do not allow for autonomous, direct syncing straight into Zoho. By routing creation through our system, we can capture tracking numbers as soon as they are available and bypass manual entry limitations.

---

## 3. Daily Workflow & Syncing
To ensure data remains accurate across both systems, the daily operational flow operates as follows:

1.  **Automated Import:** Every morning (Vietnam time), orders from our primary connected sources (Ebay_Mekong, Ebay_Purchasing, 1 Amazon, 1 Goodwill, 1 Aliexpress) are automatically imported into `inventory_system`.
2.  **Manual Matching:** The Sales Team (AJAX) manually reviews and matches the products to ensure data integrity.
3.  **Zoho Sync:** Once matched and verified, these purchase orders are pushed to Zoho on the same day, keeping the systems aligned for the receiving team.

---

## 4. SKU System Alignment
The proposed strategy of assigning a single, master internal SKU to every item is fully supported and already in progress. 

* We have implemented a brand-new SKU system across both `inventory_system` and Zoho. 
* While it is loosely inspired by the Ecwid structure, it is a distinct, standalone mapping system. 
* *Reference:* Please refer to Quang's SKU system documentation for the complete mapping rules and conventions.

---

## 5. Identified Bottlenecks & Required US Collaboration
As we scale this deployment, the Vietnam team is tracking two major issues resulting in "unfound" orders. Resolving these requires established workflows with the US team:

### Issue 1: Complex & Confusing Item Matching
* **The Problem:** Approximately 10% of "unfound" orders contain items that are highly confusing or difficult for the Vietnam team to accurately identify and match during the morning creation process.
* **Action Plan:** Establish a dedicated, rapid-response communication channel. The Vietnam team will flag these specific cases here, requiring the US team to help identify the items in a timely manner so the PO can be synced.

### Issue 2: "Off-Grid" Purchasing Sources
* **The Problem:** A significant number of purchase orders originate outside our currently automated scope (the specific eBay, Amazon, Goodwill, and Aliexpress accounts mentioned above). These orders are often lost in email threads or simply not flagged for manual creation, meaning no PO exists in Zoho when the physical box arrives.
* **Action Plan:** * Onboard the US team to the `inventory_system` UI.
    * Shift the responsibility of manual purchase creation for these "off-grid" sources to the US team.
    * Implement standard communication protocols for one-off purchases to ensure they are logged into the system prior to physical delivery.