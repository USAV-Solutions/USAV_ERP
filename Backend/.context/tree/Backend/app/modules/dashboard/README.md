# Backend\app\modules\dashboard

## What This Folder Does
Best-selling products dashboard API endpoints and aggregation logic. The module exposes `/dashboard/best-selling/*` routes for summary KPIs, ranked SKU rows, trends, platform breakdowns, and SKU detail drilldowns.

## Typical Contents
- `routes.py` for FastAPI contracts guarded by role-based auth.
- `service.py` for query-based dashboard aggregation.
- `schemas.py` for dashboard response models.

## Common Pitfalls
- The MVP reports gross profit, not net profit, because platform fees are not modeled.
- Shipping cost is allocated from order-level `orders.shipping_amount` to SKU rows by quantity share.
- Reportable sales exclude orders with status `CANCELLED`, `REFUNDED`, `ERROR`, or `ON_HOLD`, and exclude cancelled order items.
- Return rates only include `ReturnItem` rows with `linked_order_item_id`; unlinked returns are surfaced as data-quality warnings.
- Cost comes from `order_item.allocated_inventory_id -> inventory_item.cost_basis`; missing allocation or missing cost basis is surfaced as a warning.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Start with `routes.py` for API shape.
- Read `service.py` before changing metrics or business rules.
