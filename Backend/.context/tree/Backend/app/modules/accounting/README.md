# Backend\app\modules\accounting

## What This Folder Does
Accounting API endpoints behind `ADMIN`/`ACCOUNTANT` access, including Purchase Order Reports, Sales Order Reports data aggregation/report exports, and bank statement conversion file processing.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Access is restricted to `ADMIN` and `ACCOUNTANT`; role wiring must remain aligned with auth token role values.
- Purchase Order report endpoint requires `start_date`, `end_date`, valid `group_by` (`sku`, `week`, `month`, `quarter`, `year`, `source`, `vendor`), and `order_by` (`total_price`, `quantity`, `sku`, `source`, `date`); it also accepts repeated optional filters for `item` (combined SKU/name search), `source`, `vendor`, and `po_status` (matches `PurchaseOrder.deliver_status` enum values such as `CREATED`, `BILLED`, `DELIVERED`).
- Export endpoints use `file_type` (`csv` or `xlsx`) and return attachment streams; they now also accept `export_full=true` to export ungrouped order rows for the selected date/filter window. Purchase-order full export includes `po_status` (from `PurchaseOrder.deliver_status`) and `inventory_name` (from `ProductVariant.variant_name`) while `item` remains the original order-side item title.
- Filter option endpoint `/accounting/reports/purchase-orders/filter-options` returns `item_options` (`value` + `label` where label shows both SKU and name), plus distinct `source_options`, `vendor_options`, and `po_status_options` for a date range.
- Sales Order report endpoint `/accounting/reports/sales-orders` mirrors Purchase Order report behavior but reads from `orders` + `order_item` (`ordered_at` date range), with `group_by` options `sku`, `week`, `month`, `quarter`, `year`, `source`, `customer`, `order_by` options (`total_price`, `quantity`, `sku`, `source`, `date`), and optional repeated filters `item`, `source`, `customer`.
- Sales report export endpoint `/accounting/reports/sales-orders/export` supports `file_type` (`csv` or `xlsx`) and `export_full=true` for ungrouped rows; in full-export mode it emits `inventory_name` (`ProductVariant.variant_name`), separate `inventory_sku` (from `ProductVariant.full_sku`, blank for unmatched items), `platform_sku` (listing/order external reference id), `tracking_number`, and `shipping_status` columns.
- Sales report filter options endpoint `/accounting/reports/sales-orders/filter-options` returns `item_options` (`value` + `label`), `source_options`, and `customer_options`.
- Bank conversion endpoint only accepts `.pdf` uploads and supports parser formats `boa_v1`, `boa_v2`, `boa_v3`, `amazon`, `apple`, `chase`, and `format_7` (PayPal transaction-history format).
- `format_7` (PayPal) parser is table-layout driven (`pdfplumber.extract_tables`) and outputs `Date, Type, ID, Name, Email, Gross, Fee, Net`; if PayPal PDF rendering changes to non-table text flow, parser may return format mismatch.
- Parser mismatch should return HTTP 400 with `Format does not match selected bank` so frontend can surface correct guidance.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
