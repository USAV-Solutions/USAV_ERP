# Backend\app\modules\purchasing

## What This Folder Does
Purchase order domain: import pipelines, vendor workflows, receiving, and matching.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Changing import-source behavior without updating schema enums and UI source selectors.
- Breaking source tagging used downstream in Zoho notes/reconciliation.
- Editing PO status transitions without test updates.
- Mixing dependency styles in route signatures; prefer `Annotated[..., Depends(...)]` and `Annotated[..., Query(...)]` for maintainable, consistent FastAPI typing.
- In Python signatures, non-default dependency params must come before optional/default query params to avoid `SyntaxError: parameter without a default follows parameter with a default`.

## Child Folders
- `schemas/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
