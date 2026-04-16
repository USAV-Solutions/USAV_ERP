# API + Auth Branch

## Scope
- `app/main.py`
- `app/api/`
- `app/modules/auth/`
- Cross-module route wiring and role checks

## Architecture Rules
- Authentication and role gating should use dependencies from `app/api/deps.py`.
- Keep endpoint handlers thin; move non-trivial logic into services/repositories.
- Use explicit response schemas to prevent drift in API contracts.

## Naming / Contract Conventions
- Route-level query aliases are used where needed (e.g. `status` mapped to internal variables).
- Role aliases (`AdminUser`, `AdminOrSalesUser`, etc.) should be used for readability and consistency.
- Error contracts should be `HTTPException` with meaningful `detail`.

## Pitfalls
- Adding new protected endpoints without role dependencies creates accidental privilege escalation.
- Changing request/response shape without updating frontend types creates silent runtime mismatch.
- Keep status enums string-compatible across backend and frontend.

## Change Checklist
- If adding endpoint: update route + schema + frontend endpoint/type client.
- If adding role behavior: verify all affected endpoints still allow intended staff/admin flows.

