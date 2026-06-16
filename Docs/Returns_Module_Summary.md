# Returns Module Summary

## Overview
The `returns` module introduces a centralized system to track and manage product returns, refunds, and cancellations across multiple sales platforms (eBay, Walmart, Ecwid, etc.). It normalizes data from different APIs into a unified internal structure.

## Key Components Implemented

### 1. Database Models
*   **`ReturnRecord`**: The core entity representing a return/refund/cancellation event. It stores:
    *   Platform and source identifiers.
    *   Customer details (name, email).
    *   Timestamps (order date, event date).
    *   Financials (order total, refunded amount).
    *   `normalized_status` (e.g., `RETURNED`, `REFUNDED`, `CANCELLED`) to unify different platform statuses.
    *   Link to the original `orders` record.
*   **`ReturnItem`**: Represents the specific line items involved in a return. It tracks:
    *   `ordered_qty`, `returned_qty`, and `cancelled_qty`.
    *   `refunded_amount` per item.
    *   Link to the original `order_item` and the parent `ReturnRecord`.
*   **`ReturnSyncState`**: Tracks the synchronization heartbeat, last successful sync timestamp, and status per platform.

### 2. API Routes
*   **`GET /returns`**: Retrieves a paginated, filterable (by platform, status, date), and sortable list of return records.
*   **`GET /returns/{record_id}`**: Fetches detailed information for a specific return record, including its line items.
*   **`POST /returns/sync`**: Triggers a synchronization process to fetch new returns from configured platform APIs (eBay Mekong/USAV/Dragon, Ecwid, Walmart).
*   **`POST /returns/sync/range`**: Triggers a synchronization process for a specific date range.
*   **`GET /returns/sync/status`**: Provides an overview of the sync status across all platforms and total record counts.

### 3. Sync Services
*   Integration logic to connect to eBay, Walmart, and Ecwid APIs, fetch return/cancellation events, and map them to the normalized `ReturnRecord` and `ReturnItem` schema.
