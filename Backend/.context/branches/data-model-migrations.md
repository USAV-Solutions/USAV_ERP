# Data Model + Migrations Branch

## Scope
- `app/models/`
- `migrations/versions/`
- Cross-layer enum/column contract consistency

## What This Layer Does
- Defines persistent schema and ORM relationships
- Evolves schema via Alembic revisions

## Strict Rules
- Any schema change in models must have corresponding migration.
- Enum additions require:
  - DB enum alteration migration
  - ORM enum update
  - schema/type updates in API/frontend
- Prefer additive changes with safe defaults for existing rows.

## Naming Conventions
- Alembic revision filenames are timestamped and descriptive.
- Enum names are stable DB type names (e.g., `order_platform_enum`, `platform_enum`).
- Use explicit index/constraint names where practical.

## Common Pitfalls
- Updating Python enum only (forgetting DB enum migration).
- Adding non-null columns without default/backfill strategy.
- Forgetting seed rows for operational tables (e.g., sync-state platform rows).

## Migration Safety Checklist
- Upgrade path works on populated DB
- Backfill runs idempotently where needed
- Downgrade behavior is safe and explicit (even when enum value removal is not trivial)

