# Best-Selling Products Dashboard: Implementation Plan

## Goal
Build a clean, useful dashboard that helps the team quickly understand which products are selling best, which products are most profitable, which products are risky because of returns, and which products may need inventory action.

The dashboard should not only rank products by quantity sold. It should combine sales, revenue, profit, returns, and inventory availability so the team can make better operational decisions.

---

## Current Context
The ERP already supports most of the required dashboard data:

- SKU and product name from product variants / product families.
- Platform from orders or platform listings.
- Quantity sold from order items.
- Revenue from order item totals.
- Cost basis from allocated inventory items.
- Return quantity and return rate from the returns module.
- Inventory left from available inventory items.
- Average selling price and profit margin as calculated metrics.

The main missing or partially-supported pieces are:

- Platform fee capture or estimation.
- Shipping cost allocation from order level to SKU level.
- A dashboard aggregation layer for fast reporting.

---

## Product Direction
The dashboard should answer these core questions:

1. What are the best-selling SKUs by quantity?
2. Which products generate the most revenue?
3. Which products generate the most gross profit?
4. Which products have high sales but poor margin?
5. Which products have high return rates?
6. Which products are selling fast but have low inventory left?
7. Which platforms are driving the most sales and profit?

---

## Phase 1 — Define Dashboard Metrics and Business Rules
### Objective
Lock down metric definitions before building UI or APIs.

### Implementation Steps
1. Define core metrics:
   - quantity sold
   - revenue
   - average selling price
   - cost of goods sold
   - gross profit
   - gross margin percentage
   - return quantity
   - return rate percentage
   - inventory left

2. Define optional advanced metrics:
   - estimated platform fees
   - allocated shipping cost
   - net profit
   - net margin percentage
   - sell-through speed
   - inventory coverage estimate

3. Decide business rules:
   - Count only completed/fulfilled orders, not cancelled orders.
   - Decide whether refunded/returned orders reduce revenue or appear separately.
   - Allocate shipping cost by quantity first for MVP.
   - Treat platform fees as unavailable/estimated until proper fee data exists.
   - Calculate return rate as `returned quantity / sold quantity`.

4. Document metric definitions in one shared file so backend, frontend, and business users use the same meaning.

### Deliverable
A metric-definition document and agreed dashboard rules.

---

## Phase 2 — Build the Aggregation Layer
### Objective
Create a fast and reliable data source for dashboard queries.

### Implementation Steps
1. Build a reporting query or summary table that joins:
   - orders
   - order items
   - product variants
   - product families
   - allocated inventory items
   - return items
   - inventory availability

2. Choose the aggregation strategy:
   - SQL view for simple MVP.
   - Materialized view for better performance.
   - Scheduled summary table for larger datasets.

3. Aggregate by useful dimensions:
   - SKU
   - product family
   - platform
   - date range
   - marketplace/store account

4. Add precomputed fields:
   - qty sold
   - revenue
   - cost
   - gross profit
   - return qty
   - inventory left

5. Add indexes around common filters:
   - order date
   - platform
   - SKU / variant ID
   - product family

### Deliverable
A dashboard-ready reporting layer that avoids heavy joins on every page load.

---

## Phase 3 — Backend Dashboard API
### Objective
Expose clean API endpoints for the frontend dashboard.

### Implementation Steps
1. Create endpoints such as:
   - `GET /dashboard/best-selling/summary`
   - `GET /dashboard/best-selling/products`
   - `GET /dashboard/best-selling/trends`
   - `GET /dashboard/best-selling/platform-breakdown`
   - `GET /dashboard/best-selling/products/{sku}`

2. Support filters:
   - date range
   - platform
   - store/account
   - SKU search
   - product family
   - sort by qty sold, revenue, gross profit, return rate, inventory left

3. Return data in UI-friendly shapes:
   - summary KPI cards
   - ranked product table
   - chart series
   - platform breakdown
   - product detail drawer data

4. Add pagination and export support for the product table.

### Deliverable
Stable dashboard API contracts that frontend can build against.

---

## Phase 4 — Dashboard UX and Information Architecture
### Objective
Design a dashboard that is simple enough for daily use but rich enough for decision-making.

### Recommended Layout
1. **Top Filter Bar**
   - Date range
   - Platform/store
   - Product family
   - Search SKU/product name
   - Sort mode

2. **KPI Cards**
   - Total units sold
   - Total revenue
   - Gross profit
   - Average margin
   - Return rate
   - Low-stock best sellers

3. **Main Ranking Table**
   Columns:
   - Rank
   - SKU
   - Product name
   - Platform
   - Qty sold
   - Revenue
   - Avg selling price
   - Cost
   - Gross profit
   - Margin %
   - Return qty
   - Return rate %
   - Inventory left
   - Status badge

4. **Charts**
   - Top 10 products by quantity sold.
   - Top 10 products by revenue.
   - Sales trend over time.
   - Platform breakdown.

5. **Product Detail Drawer**
   When clicking a SKU, show:
   - sales trend
   - platform split
   - return history
   - inventory left
   - recent orders
   - notes / action recommendation

### UX Principles
- Make the default view useful without configuration.
- Use clear status badges like `High Return`, `Low Stock`, `High Margin`, `Fast Seller`.
- Show definitions/tooltips for profit, margin, and return rate.
- Keep advanced filters collapsed unless needed.
- Make export easy for business reporting.

### Deliverable
A frontend wireframe/design direction and component breakdown.

---

## Phase 5 — Frontend Implementation
### Objective
Build the interactive dashboard screen.

### Implementation Steps
1. Create reusable components:
   - filter bar
   - KPI card
   - ranking table
   - chart card
   - product detail drawer
   - empty/loading/error states

2. Add frontend states:
   - loading
   - no data
   - partial data warning
   - failed API request
   - stale data warning

3. Add table interactions:
   - sorting
   - pagination
   - column visibility
   - SKU search
   - row click detail drawer

4. Add visual hierarchy:
   - KPIs first
   - product ranking second
   - charts and drilldowns after

### Deliverable
A usable dashboard page connected to real backend APIs.

---

## Phase 6 — Data Quality and Validation
### Objective
Make sure numbers are trusted before business users rely on the dashboard.

### Implementation Steps
1. Validate a sample date range manually:
   - compare qty sold against order item records
   - compare revenue against order totals
   - compare cost against allocated inventory
   - compare returns against `ReturnItem`

2. Add data warnings:
   - missing cost basis
   - missing platform fees
   - unallocated shipping cost
   - returns without linked order item

3. Add internal QA report:
   - number of orders included
   - number of SKUs included
   - percentage of rows missing cost
   - percentage of rows missing fee data

### Deliverable
A dashboard that communicates confidence and known limitations clearly.

---

## Phase 7 — Rollout and Iteration
### Objective
Release quickly, then improve based on operational feedback.

### Implementation Steps
1. Release MVP with:
   - date/platform filters
   - KPI cards
   - ranking table
   - top product charts
   - return rate and inventory left

2. Gather feedback from users:
   - which columns are used most
   - which filters are missing
   - which numbers are confusing
   - which actions users want after seeing a result

3. Iterate with advanced features:
   - fee-aware net profit
   - shipping allocation modes
   - reorder recommendations
   - slow-moving inventory view
   - product family rollups
   - export/report scheduling

### Deliverable
A practical reporting tool that improves over time.

---

## MVP Scope
For the immediate implementation, build:

1. Date range filter.
2. Platform filter.
3. KPI cards.
4. Best-selling SKU table.
5. Qty sold, revenue, gross profit, margin, return rate, inventory left.
6. Top 10 chart by quantity sold.
7. Product detail drawer.
8. Data quality warnings for missing fees or shipping allocation.

---

## Later Enhancements
- Net profit after platform fees.
- Smarter shipping cost allocation.
- Reorder / low-stock alerts.
- Product velocity scoring.
- Return-risk scoring.
- Platform comparison by SKU.
- Scheduled email report.
- Drilldown to order-level details.
