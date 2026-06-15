# Best Selling Products Dashboard: Data Support Analysis

This document outlines how the current system schema and the new `returns` module support the data requirements for the proposed "Best Selling Products" dashboard.

## Dashboard Data Requirements per SKU

| Required Data Point | Current System Support | Source / Calculation Method |
| :--- | :--- | :--- |
| **SKU** | **Supported** | `product_variant.full_sku` or `order_item.external_sku` |
| **Product Name** | **Supported** | `product_variant.variant_name` or `product_family.base_name` |
| **Platform** | **Supported** | `orders.platform` or `platform_listing.platform` |
| **Qty Sold** | **Supported** | Sum of `order_item.quantity` for completed orders |
| **Revenue** | **Supported** | Sum of `order_item.total_price` |
| **Cost / Purchase Cost**| **Supported** | Linked via `order_item.allocated_inventory_id` -> `inventory_item.cost_basis` (Highly accurate COGS) |
| **Shipping Cost** | **Partially Supported**| Tracked at the order level (`orders.shipping_amount`). Needs a business rule to allocate cost per SKU if an order contains multiple items (e.g., split by quantity or weight). |
| **Platform Fee** | **Not explicitly modeled** | Currently missing from the main schema. May need to be extracted from raw API payloads, fetched via separate API endpoints, or calculated based on known platform fee rules. |
| **Gross Profit** | **Supported** | Calculated: `Revenue - Cost - Allocated Shipping Cost` |
| **Net Profit** | **Partially Supported**| Requires Platform Fee and other potential operational expenses not yet fully tracked at the item level. |
| **Profit Margin %** | **Supported** | Calculated: `(Gross or Net Profit) / Revenue * 100` |
| **Return Qty** | **Supported** | Sum of `ReturnItem.returned_qty` from the new `returns` module, linked via `order_item`. |
| **Return Rate %** | **Supported** | Calculated: `Return Qty / Qty Sold * 100` |
| **Inventory Left** | **Supported** | Count of `inventory_item` where `status` indicates availability for a specific `variant_id`. |
| **Avg Selling Price** | **Supported** | Calculated: `Revenue / Qty Sold` |

## Summary
The system is exceptionally well-positioned to build this dashboard. The core transactional data (orders, inventory costs) is fully modeled. The recent addition of the `returns` module perfectly addresses the need to track **Return Qty** and **Return Rate %**. 

**Action Items to fully realize the Dashboard:**
1.  **Platform Fees:** Implement a mechanism to accurately capture or estimate platform fees per order/item.
2.  **Shipping Cost Allocation:** Define the logic for distributing order-level shipping costs to individual SKUs.
3.  **Data Aggregation Pipeline:** Create an aggregation layer (e.g., SQL materialized views, cron jobs generating summary tables, or BI tool queries) to join `orders`, `order_item`, `inventory_item`, and `ReturnItem` efficiently for dashboard consumption.
