# Testing Playbook Branch

## Scope
- `tests/`
- Module-specific tests (`tests/modules/...`)
- Integration tests (`tests/integrations/...`)

## Strategy
- Keep fast unit tests around service/repository behavior.
- Add integration tests for parser/client normalization and endpoint contracts.
- For import/sync features, validate counts, dedupe behavior, and status transitions.

## Rules
- When adding a new platform/source:
  - add at least one mapping/dispatch test
  - add at least one parser/normalization test (or placeholder behavior test)
- When adding filters:
  - verify query serialization (frontend client)
  - verify repository-side filtering logic

## Common Pitfalls
- Mocking old repository method names after service lookup API changes.
- Asserting only success flags; missing count/field assertions.
- Adding schema fields (like `source`) without updating fixtures/mocks.

## Practical Checklist Per Feature
- Unit: domain service behavior
- API: request/response contract
- Regression: enum/platform/source mappings

