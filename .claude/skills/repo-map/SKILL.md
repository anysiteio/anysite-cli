---
name: repo-map
description: Map of anysite-cli - every module under src/anysite/, the dataset, llm and db subsystems (YAML source types, three-level filtering, DB loading, catalogs), the agent protocol (JSON envelope, exit codes, discovery payload), the Typer option aliases, the test layout and the full command catalogue. Load before editing anything under src/ or tests/, or adding a command.
---

# repo-map

Read only the file the task needs:

| File | Holds |
|---|---|
| `modules.md` | what each module does, the reusable Typer options in `cli/options.py`, the test layout |
| `subsystems.md` | API pattern, schema cache, dataset YAML and pipeline, LLM, database, credentials, agent protocol |
| `commands.md` | every CLI command with its flags |
