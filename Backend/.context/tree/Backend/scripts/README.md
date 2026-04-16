# Backend\scripts

## What This Folder Does
One-off operational scripts for backfills, cleanup, reconciliation, and migrations support.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Reusing script-only assumptions in production request paths.
- Running destructive scripts without dry-run guardrails.
- Leaving script output formats undocumented for future operators.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
