# Agent Working Rules

## Required Read Order
1. Read `Backend/.context/tree/TREE.md` to understand the layout.
2. Read the relevant folder doc(s) under `Backend/.context/tree/.../README.md`.
3. Only then inspect/edit code files.

## Scope Rule
- Navigate top-down: `TREE.md` -> domain `README.md` -> specific code files.
- Do not scan or read the whole codebase by default.

## Mandatory Update Rule
When code changes in any backend folder, you MUST update the matching context doc:
- **Code folder:** `Backend/<path>`
- **Doc folder:** `Backend/.context/tree/Backend/<path>/README.md`

**What to update in the README:**
- **What This Folder Does:** Modify if the module's behavior changed.
- **Common Pitfalls:** Add any new gotchas, environment variables, or edge cases introduced.
- **Child Folders:** Update if you added or removed directories.