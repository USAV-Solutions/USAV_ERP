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

- Load and apply rules from: ./skills/karpathy-guidelines/SKILL.md

## 2. Navigation & Required Read Order
Use `Backend/.context/tree/TREE.md` as your primary navigation map. Do not scan or read the whole codebase by default.
Navigate top-down:
1. Read `Backend/.context/tree/TREE.md` to understand the layout.
2. Read the relevant folder doc(s) under `Backend/.context/tree/.../README.md`.
3. Only then inspect/edit specific code files.

## 3. Mandatory Update Rule
If you modify ANY code inside a backend folder (`Backend/<path>`), you MUST update the matching context documentation:
- **Code folder:** `Backend/<path>`
- **Doc folder:** `Backend/.context/tree/Backend/<path>/README.md`

**What to update in the README:**
- **What This Folder Does:** Modify if the module's behavior changed.
- **Common Pitfalls:** Add any new gotchas, environment variables, or edge cases introduced.
- **Child Folders:** Update if you added or removed directories.

## 4. Completion Criteria
A task is considered strictly incomplete if relevant code was changed but the corresponding context docs (`Backend/.context/tree/.../README.md`) were not updated alongside it.