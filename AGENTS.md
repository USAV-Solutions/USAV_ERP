# Agent Working Rules

## 1. Coding Rules:
Follow these guidelines:

- State assumptions before making changes.
- Prefer the smallest correct change.
- Do not add features, abstractions, or configurability that were not requested.
- Do not refactor unrelated code.
- Match the existing project style.
- Every changed line should directly support the requested task.
- If something is unclear, ask instead of guessing.
- Define how the change will be verified before implementation.

## 2. Navigation & Required Read Order

Use `Backend/.context/tree/TREE.md` only when file location is unknown or the task spans unfamiliar modules.

Do not scan or read the whole codebase by default.

Preferred order:
1. Use targeted search (`rg`) for known symbols, routes, models, fields, or filenames.
2. Read `Backend/.context/tree/TREE.md` only if navigation is unclear.
3. Read the relevant folder README only if it helps understand the module.
4. Inspect/edit only the specific source files needed.

Avoid large outputs:
- Do not `cat` large files.
- Do not dump large JSON/log files.
- Use `sed -n`, `rg`, `jq`, or small Python summaries.
- Prefer reading small ranges of files unless more context is necessary.

## 3. Mandatory Update Rule
Update matching context docs (Backend only) only when the change affects module behavior, public contracts, env vars, folder responsibilities, or known pitfalls.
- **Code folder:** `Backend/<path>`
- **Doc folder:** `Backend/.context/tree/Backend/<path>/README.md`

**What to update in the README:**
- **What This Folder Does:** Modify if the module's behavior changed.
- **Common Pitfalls:** Add any new gotchas, environment variables, or edge cases introduced.
- **Child Folders:** Update if you added or removed directories.

## 4. Completion Criteria

Before finishing, report:
- files changed
- whether backend context docs were updated
- if not updated, why no context-doc update was needed
- verification performed or recommended