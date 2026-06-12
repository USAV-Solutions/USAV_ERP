# Best-Selling Products Dashboard Metric Definitions

## MVP Business Rules

- Date range uses `orders.ordered_at`.
- Reportable sales exclude orders with status `CANCELLED`, `REFUNDED`, `ERROR`, or `ON_HOLD`.
- Cancelled order items are excluded.
- SKU uses `product_variant.full_sku`, then `order_item.external_sku`, then `UNMATCHED`.
- Product name uses `product_variant.variant_name`, then `product_family.base_name`, then `order_item.item_name`.
- Platform uses `orders.platform`.
- Shipping is allocated from the order to each line by quantity share.
- Platform fees are not captured yet, so the dashboard reports gross profit, not net profit.
- Returns count only `return_item` rows linked to an `order_item`.

## Core Metrics

| Metric | Definition |
| :--- | :--- |
| Quantity sold | Sum of `order_item.quantity` for reportable sales. |
| Revenue | Sum of `order_item.total_price`. |
| Average selling price | `revenue / quantity sold`. |
| Cost of goods sold | Sum of `inventory_item.cost_basis` through `order_item.allocated_inventory_id`. |
| Allocated shipping cost | `orders.shipping_amount * order_item.quantity / total order quantity`. |
| Gross profit | `revenue - cost of goods sold - allocated shipping cost`. |
| Gross margin percentage | `gross profit / revenue * 100`. |
| Return quantity | Sum of linked `return_item.returned_qty`. |
| Return rate percentage | `return quantity / quantity sold * 100`. |
| Inventory left | Count of `inventory_item` rows for the SKU variant where status is `AVAILABLE`. |

## Data Quality Warnings

| Warning | Meaning |
| :--- | :--- |
| `platform_fees_unavailable` | Platform fees are not captured, so net profit is unavailable. |
| `shipping_allocated_by_quantity` | Shipping cost is allocated by quantity as an MVP business rule. |
| `missing_cost_basis` | One or more sold rows have no allocated inventory item or no cost basis. |
| `unlinked_returns` | Some return rows cannot be connected to SKU return rates because they lack `linked_order_item_id`. |

