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

## Child Folders
- `schemas/`

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
