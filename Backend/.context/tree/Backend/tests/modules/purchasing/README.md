# Backend\tests\modules\purchasing

## What This Folder Does
Purchasing domain tests: imports, mapping, and PO workflow invariants.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Purchase-order Zoho payload mapping tests should assert `custom_fields` coverage, including `cf_source` mapping behavior.
- Goodwill shipped-source tests should assert the canonical stored value `GOODWILL_SHIPPED` when validating source-to-Zoho mapping.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
