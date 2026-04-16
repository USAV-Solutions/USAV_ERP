# Backend\tests

## What This Folder Does
Automated tests covering API, integrations, and domain modules.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Mocking stale repository method names after refactors.
- Asserting only success flags without checking counts/field values.
- Not extending fixtures after schema contract changes.

## Child Folders
- `integrations/`
- `modules/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
