# Returns Module: Zoho Sales Returns Sync Plan

## Goal
Implement a high-level returns workflow that allows the ERP returns module to sync valid return records into Zoho as Sales Returns, while preventing invalid sync attempts when the related Zoho Sales Order does not exist.

The core principle is: **no Zoho Sales Return should be created until the system can verify and map the original order to an existing Zoho Sales Order and its matching line items.**

---

## Current Context
The ERP already has a centralized returns module with:

- `ReturnRecord` for the return, refund, or cancellation event.
- `ReturnItem` for item-level returned quantity, cancelled quantity, and refunded amount.
- `ReturnSyncState` for tracking platform sync heartbeat/status.
- API routes for listing returns, getting return detail, triggering sync, syncing by date range, and checking sync status.
- Sync services for marketplace returns from eBay, Walmart, and Ecwid.

The next step is to add a Zoho outbound sync path.

---

## Key Design Decision
Zoho Sales Returns should be treated as an **outbound accounting/inventory sync target**, not as the source of truth for detecting marketplace returns.

Recommended ownership:

- Marketplace APIs detect and normalize return events.
- ERP stores and verifies returns.
- Zoho receives only validated returns that match an existing Zoho Sales Order.
- ERP stores Zoho sync result IDs and errors for auditability.

---

## Phase 1 — Confirm Zoho Object Mapping
### Objective
Define how ERP orders and return items map to Zoho Sales Orders and Sales Return line items.

### Implementation Steps
1. Identify which ERP field currently maps to Zoho Sales Order:
   - `orders.id`
   - `orders.external_order_id`
   - `orders.platform_order_id`
   - existing `zoho_salesorder_id`, if already present
   - custom field / reference number inside Zoho

2. Add missing Zoho mapping fields if needed:
   - `orders.zoho_salesorder_id`
   - `order_item.zoho_salesorder_item_id`
   - `return_record.zoho_salesreturn_id`
   - `return_record.zoho_sync_status`
   - `return_record.zoho_sync_error`
   - `return_record.zoho_synced_at`

3. Decide lookup priority:
   - First: local stored `zoho_salesorder_id`.
   - Second: search Zoho by Sales Order number / reference number / external order custom field.
   - Third: mark as `NEEDS_ORDER_MAPPING` and do not sync.

### Deliverable
A documented mapping table between ERP return fields, ERP order fields, and Zoho Sales Return payload fields.

---

## Phase 2 — Build the Order Verification Layer
### Objective
Create a reusable service that verifies whether a return can be safely synced to Zoho.

### Implementation Steps
1. Create a high-level service such as `ZohoReturnEligibilityService`.

2. For each `ReturnRecord`, verify:
   - The ERP return is linked to an internal `orders` record.
   - The linked order has a valid Zoho Sales Order ID or can be found in Zoho.
   - Each returned item can be matched to an ERP `order_item`.
   - Each ERP `order_item` can be mapped to a Zoho `salesorder_item_id`.
   - Returned quantity does not exceed ordered quantity minus already-returned quantity.

3. Return a clear eligibility state:
   - `READY_TO_SYNC`
   - `MISSING_LOCAL_ORDER`
   - `MISSING_ZOHO_ORDER`
   - `MISSING_LINE_ITEM_MAPPING`
   - `QUANTITY_CONFLICT`
   - `ALREADY_SYNCED`

4. Expose this validation in the API so the UI can show why a return cannot sync yet.

### Deliverable
A verification layer that blocks invalid Zoho sync attempts before calling Zoho.

---

## Phase 3 — Build the Zoho Sales Returns Client
### Objective
Add a dedicated integration client for Zoho Sales Returns.

### Implementation Steps
1. Create a Zoho API client wrapper that handles:
   - OAuth token refresh.
   - Organization ID.
   - Regional API domain.
   - Retry policy.
   - Rate-limit handling.
   - Structured error parsing.

2. Add high-level client methods:
   - `getSalesOrder(zohoSalesOrderId)`
   - `searchSalesOrderByReference(reference)`
   - `createSalesReturn(salesOrderId, payload)`
   - `getSalesReturn(salesReturnId)`
   - optionally `createSalesReturnReceive(...)` later if the receiving workflow is needed.

3. Keep this separate from marketplace return sync services.

### Deliverable
A Zoho integration client that can be reused by returns, sales orders, and future accounting workflows.

---

## Phase 4 — Map ERP Returns to Zoho Sales Return Payloads
### Objective
Convert internal return records into Zoho-compatible Sales Return requests.

### Implementation Steps
1. Create a mapper layer:
   - `ReturnRecord` → Sales Return header.
   - `ReturnItem` → Sales Return line items.
   - ERP order line item → Zoho `salesorder_item_id`.
   - return reason/status → Zoho reason/custom field.

2. Preserve source information using custom fields where helpful:
   - platform
   - platform return ID
   - platform order ID
   - ERP return ID
   - normalized status

3. Add idempotency protection:
   - If `zoho_salesreturn_id` exists, do not create another one.
   - If a previous attempt failed, retry only after validation passes again.
   - Store request hash or sync attempt log if duplicate risk is high.

### Deliverable
A clear payload mapping layer with duplicate protection.

---

## Phase 5 — Add Sync Workflow and API Endpoints
### Objective
Allow admins or scheduled jobs to sync eligible returns to Zoho.

### Implementation Steps
1. Add backend service methods:
   - `validateReturnForZoho(returnId)`
   - `syncReturnToZoho(returnId)`
   - `syncEligibleReturnsToZoho(dateRange/platform)`

2. Add or extend API routes:
   - `POST /returns/{id}/zoho/validate`
   - `POST /returns/{id}/zoho/sync`
   - `POST /returns/zoho/sync/range`
   - `GET /returns/zoho/sync/status`

3. Update return list/detail responses with:
   - Zoho sync status.
   - Zoho Sales Return number/ID.
   - validation blockers.
   - last sync attempt and error message.

### Deliverable
A safe, observable Zoho return sync workflow.

---

## Phase 6 — Admin UX for Verification and Manual Fixes
### Objective
Make sync blockers easy for operators to understand and resolve.

### Implementation Steps
1. Add Zoho sync status indicators to the Returns page:
   - Ready to Sync
   - Synced
   - Needs Order Mapping
   - Needs Line Item Mapping
   - Failed

2. Add a detail panel showing:
   - original marketplace order ID
   - internal ERP order ID
   - Zoho Sales Order ID
   - return items
   - validation result
   - sync error history

3. Add manual actions:
   - link to existing ERP order
   - enter/refresh Zoho Sales Order ID
   - retry Zoho sync
   - mark as not syncable, with reason

### Deliverable
A practical admin workflow that avoids silent failures and supports manual recovery.

---

## Phase 7 — Testing and Rollout
### Objective
Roll out safely without corrupting Zoho data.

### Implementation Steps
1. Unit test:
   - order verification states
   - line item mapping
   - quantity checks
   - payload mapping
   - duplicate prevention

2. Integration test against Zoho sandbox or a test organization:
   - valid return sync
   - missing order
   - missing line item
   - duplicate retry
   - partial quantity return

3. Rollout sequence:
   - dry-run validation only
   - sync one known test return
   - sync small date range
   - enable scheduled sync
   - monitor error dashboard

### Deliverable
A tested, staged Zoho returns sync process.

---

## MVP Scope
For the immediate implementation, focus on:

1. Verify ERP return has a linked order.
2. Verify order exists in Zoho.
3. Verify line items can map to Zoho Sales Order line items.
4. Create Zoho Sales Return only when validation passes.
5. Store Zoho sync result and sync errors.
6. Provide admin visibility for blocked records.

## MVP Implementation Mapping

| ERP source | Zoho target | Current implementation |
| --- | --- | --- |
| `orders.zoho_id` | Sales Order ID | Primary stored mapping. If missing, validation searches Zoho by `external_order_number`, then `external_order_id`, and stores the found Sales Order ID. |
| `return_record.zoho_salesreturn_id` | Sales Return ID | Idempotency guard. If present, sync returns `ALREADY_SYNCED` and does not call Zoho create. |
| `return_record.zoho_salesreturn_number` | Sales Return number | Stored from Zoho create response when available for admin visibility. |
| `return_record.zoho_sync_status` | Local validation/sync state | Stores `PENDING`, blocker states, `READY_TO_SYNC`, `SYNCED`, or `ERROR`. |
| `return_record.zoho_sync_error` | Local audit message | Stores validation blockers or Zoho create error text. |
| `return_record.zoho_synced_at` | Local sync timestamp | Set after successful Sales Return creation. |
| `return_item.linked_order_item_id` | ERP order-item mapping | Required before sync; validation can match by external item ID, SKU, or item name if the link is missing. |
| Live Zoho Sales Order `line_items[*].line_item_id` / `salesorder_item_id` | Sales Return line `salesorder_item_id` | Resolved at validation time by variant `zoho_item_id`, SKU, then item name. No local `order_item` Zoho line-ID column is persisted yet. |

MVP endpoints:

- `POST /returns/{id}/zoho/validate`
- `POST /returns/{id}/zoho/sync`
- `POST /returns/zoho/sync/range`
- `GET /returns/zoho/sync/status`

---

## Later Enhancements
- Automatic Zoho Sales Order lookup by custom field.
- Automatic repair for missing Zoho IDs.
- Sales Return Receive workflow.
- Credit note / refund reconciliation.
- Per-platform return reason mapping.
- Automated Slack/email alert for repeated Zoho sync failures.
- Analytics showing returns synced vs blocked vs failed.
