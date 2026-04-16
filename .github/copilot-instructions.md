# SYSTEM INSTRUCTIONS
You are an expert AI engineer. Before writing or modifying any code, you MUST adhere to the following workflow:

1. **Auto-Context:** You must silently read `/AGENTS.md` before answering any structural or coding query.
2. **Navigation:** Use `Backend/.context/tree/TREE.md` as your primary navigation map. Do not read the whole codebase by default.
3. **Mandatory Documentation:** If you modify ANY code inside `Backend/<path>`, you MUST also update the corresponding documentation file at `Backend/.context/tree/Backend/<path>/README.md`. 
4. **Completion:** A task is considered incomplete if relevant context docs were not updated.