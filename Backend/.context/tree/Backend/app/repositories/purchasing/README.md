# Backend\app\repositories\purchasing

## What This Folder Does
Purchase order and vendor repository/query logic, including purchase list filtering by PO number, vendor name, matched item SKU, and line-item name.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Purchase-order total filtering now supports tolerance windows (`total_amount_range`) and must remain inclusive on both ends to match accountant search expectations.
- `po_number` search now also matches `ProductVariant.full_sku` through `PurchaseOrderItem.variant_id`; avoid changing this to a direct join on the header query or you can duplicate PO rows.
- `po_number` search also matches `PurchaseOrderItem.external_item_name`; keep it in an `EXISTS` subquery to avoid duplicate PO rows.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
