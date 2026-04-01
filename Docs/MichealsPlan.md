Critical Assumptions
Before diving in, here are the assumptions underpinning this design:

You have access to Zoho Inventory + Zoho Books + Zoho Procurement (the full Operations stack), and optionally Zoho Flow or Deluge scripting.
You're able to print barcode labels from a thermal printer (e.g., Zebra or Dymo) at the receiving station.
A USB/Bluetooth barcode scanner is available at the receiving desk for scanning tracking numbers and item labels.
Integrations to marketplaces (eBay, Amazon, Mercari, etc.) will use a middleware such as Zoho Flow, Linnworks, or a similar multi-channel connector — not hand-built API code.
Ecwid is treated as a storefront only going forward, not the system of record.
"FBA Returns" means items Amazon sends back to your warehouse (unfulfillable or customer-return units).
The team is comfortable with Zoho's UI but not Deluge/scripting — automation should be mostly workflow-rule-based with minimal custom code.
You are currently NOT using Zoho's Purchase Receive module consistently — that is part of what we're fixing.
SKU normalization is a one-time migration project followed by ongoing discipline — it is not fully automated on day one.
Physical warehouse has basic shelf/bin labeling or is willing to add it in Phase 2.


Section 1 — Executive Summary (Copy-paste for Outlook)
Subject: New Receiving & Inventory System — What's Changing and Why
Team,
We've been running into a consistent problem: when boxes arrive and we open them, we don't have a reliable way to match what's in the box to the Purchase Order that was supposed to be there. This causes inventory errors, missed billing, and items sitting in a gray zone between "received" and "available to sell." Starting soon, we're making a few coordinated changes to fix this for good.
Zoho Inventory will become our single source of truth. That means every product, every PO, every stock level, and every receiving event lives in Zoho — not in Ecwid, not in a spreadsheet, not in anyone's head. Ecwid will still be our storefront (customers still shop there), but it will pull its data from Zoho rather than the other way around. The same goes for eBay, Amazon, Mercari, and Walmart — they'll sync from Zoho, not the other way around.
Every product will get one internal SKU. Right now, the same physical item might have different IDs on eBay, Amazon, Ecwid, and our vendor invoice. Going forward, every item in our catalog will have a master internal ID (e.g., ELEC-00142) and a mapping table that translates all the outside marketplace IDs to that internal number. When a box arrives with an Amazon ASIN on it, the team will look it up and find the matching internal SKU in seconds.
The new receiving process has four clear steps. (1) When we create a PO in Zoho, we immediately enter the vendor's expected tracking number(s) as a Shipment record. (2) When boxes arrive, we scan each tracking number — this updates the Shipment to "arrived." (3) During unboxing, we scan or look up each item against the PO and enter quantities received using Zoho's Purchase Receive feature. (4) Once all items are confirmed, Zoho automatically updates inventory and pushes stock levels to all sales channels. Any mismatches — wrong quantities, unknown items, damaged goods — go into an exceptions queue so nothing falls through the cracks.
For day-to-day work, the biggest change is at the receiving desk. Instead of manually updating Zoho after the fact, you'll update Zoho during unboxing. It takes about the same amount of time but creates a permanent, accurate record that ties the physical box to the PO and to the inventory update. A laminated quick-reference card will be posted at the receiving station so nobody has to memorize the steps.
We'll roll this out in phases over the next 2–3 months so nothing breaks overnight. Phase 1 starts with cleaning up product data and assigning internal SKUs. Training will happen before each phase goes live. Questions? Reach out to [manager name] or reply to this thread.

Section 2 — System Architecture & Source of Truth Decision
Which System Owns What
DomainSource of TruthRationaleProduct catalog & internal SKUsZoho InventoryCentral, already integrated with POs and receiving; Ecwid's catalog is too lightweight for multi-channel operationsPurchase Orders & receivingZoho Inventory / ProcurementNative PO → Purchase Receive → Bill matching flow; no duplicate data entryInventory availability (real-time)Zoho InventoryStock adjustments, receives, and sales orders all post here first; all channels pull from this poolFinancials & bill matchingZoho Books (linked to Inventory)POs in Inventory create bills that flow directly to Books for paymentMarketplace listingsEach marketplace's native UI (seeded from Zoho)Listing content, pricing, and images are managed per-channel but stock levels sync back from ZohoStorefront listingsEcwid (seeded from Zoho)Ecwid remains the customer-facing store but is not an authoritative record for stock or product data
Why Zoho Inventory (Not Ecwid) as SoT
The core reason is integration depth. Zoho Inventory has native Purchase Order creation, Purchase Receive, Bill matching, multi-warehouse support, and marketplace/Ecwid connectors built in. Ecwid was designed as a shopping cart, not an inventory backbone — its "product catalog" lacks the vendor mapping, PO linkage, and receiving workflow that a 5-person receiving team needs. Moving the SoT to Zoho Inventory eliminates the current double-entry problem and gives you one screen to see whether a PO is open, partially received, or closed.
Integration Architecture
Vendors / Marketplaces (source product)
         ↓  (PO created in Zoho)
┌────────────────────────────────────────────┐
│           ZOHO INVENTORY (SoT)             │
│  Products · POs · Receives · Stock Levels  │
└────────┬──────────────────┬────────────────┘
         │ push stock       │ push stock
    ┌────▼────┐        ┌────▼──────────────────┐
    │  Ecwid  │        │  Marketplaces          │
    │(storefront)│     │  eBay · Amazon · Mercar│
    └─────────┘        │  Walmart · Shopify     │
                       └───────────────────────┘
Sync rules:

Zoho → Ecwid: two-way for stock levels; one-way (Zoho → Ecwid) for product data
Zoho → Marketplaces: one-way stock push (Zoho is authoritative); marketplace orders pull into Zoho as Sales Orders
Marketplace → Zoho: Sales Order sync only (not product data)
FBA: Amazon FBA inventory is tracked separately in Amazon Seller Central; Zoho tracks what was shipped to FBA as an outbound transfer, not as available stock


Section 3 — Data Model & ID Strategy
Internal SKU Format
Every item gets a master internal SKU following this format:
[CATEGORY]-[5-digit-sequence]
Examples: ELEC-00142, PHONE-00023, TABLET-00087
The SKU is assigned once in Zoho Inventory when the item is first created. It never changes — even if the item is relisted, repriced, or sold on a new channel. External marketplace IDs are recorded in a mapping table, not in the SKU itself.
Schema Tables
Items (Product Catalog)
FieldTypeExampleinternal_skuText (PK)PHONE-00023item_nameTextApple iPhone 12 64GB BlackcategoryTextSmartphonebrandTextApplemodelTextiPhone 12conditionEnumUsed – Goodunit_cost_avgCurrency$142.00reorder_pointInteger2activeBooleantrue
ItemChannelMapping (The Rosetta Stone)
FieldTypeExamplemapping_idUUID (PK)m-0041internal_skuFK → ItemsPHONE-00023channelEnumeBay, Amazon, Mercari, Walmart, Ecwid, Shopify, FBA, Vendorexternal_idTextB09G9BT59J (ASIN)external_skuTextAPL-IP12-64-BLKnotesTextLegacy SKU from old Ecwid systemactiveBooleantrue
PurchaseOrders
FieldTypeExamplepo_numberText (PK)PO-2025-0311vendor_nameTextGoodwill Outlet Portlandpo_dateDate2025-03-11expected_deliveryDate2025-03-15statusEnumOpen, Partial, Received, Closedtotal_valueCurrency$840.00notesTextBulk lot – 12 units mixed phones
PurchaseOrderLines
FieldTypeExamplepo_line_idUUID (PK)pol-0842po_numberFK → POsPO-2025-0311internal_skuFK → ItemsPHONE-00023vendor_item_refTextGW-LOT-2234qty_orderedInteger4unit_costCurrency$70.00qty_receivedInteger3 (updated on receive)statusEnumPending, Partial, Received
Shipments / Boxes
FieldTypeExampleshipment_idUUID (PK)shp-0188po_numbersFK list → POsPO-2025-0311tracking_numberText1Z999AA10123456784carrierEnumUPS, USPS, FedEx, Amazonexpected_arrivalDate2025-03-15arrival_dateDate2025-03-15 (set on scan)statusEnumIn Transit, Arrived, Processing, Donebox_countInteger2notesTextTwo boxes, same tracking
PurchaseReceives
FieldTypeExamplereceive_idUUID (PK)rec-0299po_numberFK → POsPO-2025-0311shipment_idFK → Shipmentsshp-0188receive_dateDate2025-03-15received_byTextJordanstatusEnumDraft, Confirmed, Exception
PurchaseReceiveLines
FieldTypeExamplereceive_line_idUUIDrcl-1042receive_idFK → Receivesrec-0299po_line_idFK → POLinespol-0842internal_skuFK → ItemsPHONE-00023qty_receivedInteger3qty_rejectedInteger1rejection_reasonTextScreen crackedbin_locationTextSHELF-A3
How a Single Physical Item Travels Through the System

PO Line created → PHONE-00023 on PO-2025-0311, qty 4 ordered, vendor ref GW-LOT-2234
Shipment created → tracking 1Z999AA1... linked to PO-2025-0311, status In Transit
Box arrives → tracking scanned at dock, Shipment status → Arrived, arrival date stamped
Unboxing → item scanned/identified as PHONE-00023, Purchase Receive created, qty 3 accepted + 1 rejected (cracked screen), bin location SHELF-A3 recorded
Receive confirmed → PO Line qty_received = 3, PO status → Partial (still expecting 1 more)
Inventory updated → PHONE-00023 on-hand qty +3 in Zoho Inventory
Stock synced → Zoho pushes updated availability to eBay, Ecwid, Amazon FBM, Mercari, Walmart
Bill created → Zoho Books auto-creates a draft bill against the PO for 3 units × $70

Handling Legacy SKU Mismatches
For the migration, create a mapping spreadsheet with four columns: old_ecwid_sku, old_ebay_sku, old_amazon_asin, new_internal_sku. Import this into the ItemChannelMapping table. Any old SKU that can't be matched to an existing item gets flagged as needs_review and addressed in a weekly cleanup session during Phase 1. Going forward, a new item is never listed on any channel without first being created in Zoho Inventory with its internal SKU.

Section 4 — Receiving & PO Matching SOP (Step-by-Step)
Phase A: Before Shipment Leaves Vendor
Step 1 — Create PO in Zoho Inventory

Go to Zoho Inventory → Purchases → Purchase Orders → New PO
Select or create the vendor
Add line items using internal SKUs; include vendor's item reference number in the "Vendor Part #" field
Set expected delivery date
Submit for approval (if your workflow requires it)

Step 2 — Create Shipment Record

Once vendor confirms shipment, go to the PO → click "Create Shipment" (or use the Inbound Shipments module)
Enter tracking number(s) and carrier
If the vendor sends multiple boxes on one PO, create one Shipment per tracking number
If one box contains items from multiple POs, note all PO numbers in the Shipment record
Save — this creates the pre-arrival record so the team can see it on the "Expected Today" dashboard