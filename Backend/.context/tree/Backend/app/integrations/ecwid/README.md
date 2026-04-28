# Backend\app\integrations\ecwid

## What This Folder Does
Ecwid integration client and Ecwid payload mapping utilities.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Ecwid order normalization should populate optional customer enrichment fields (`customer_phone`, `customer_company`, `customer_source`) when present, otherwise downstream Zoho customer sync loses fidelity.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
