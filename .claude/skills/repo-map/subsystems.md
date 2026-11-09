# Subsystems and how they behave

Sections: API and schema cache; dataset pipeline; LLM; database; credentials; agent protocol.

**API Pattern**: All Anysite API endpoints use POST with JSON body. Auth is via `access-token` header.

**Universal API Command**: Instead of per-platform CLI modules, a single `anysite api` command works with any endpoint. Parameters are `key=value` pairs, auto-typed via the schema cache.

**Two Execution Paths**:
- `execute_search_command()` - for list/search endpoints (single request, optional streaming)
- `execute_single_command()` - for single-item endpoints with optional batch support (from-file, stdin, parallel)

**Schema Cache**: `anysite schema update` fetches the OpenAPI spec, resolves all `$ref`/`allOf`/`anyOf`, and caches a compact representation to `~/.anysite/schema.json`. Used by `anysite describe` and for auto-typing `api` command parameters.

**Config Location**: `~/.anysite/config.yaml`

**Dataset Subsystem** (`anysite dataset`): Multi-source data collection, Parquet storage, DuckDB analytics, relational DB loading, per-source transforms/exports, run history, scheduling, and webhook notifications. Optional — requires `pip install anysite-cli[data]`. Registered in `main.py` via try/except ImportError.

**Dataset YAML Config**: Declarative multi-source pipelines. Five source types:
- **Independent** — single API call with `params`
- **from_file** — batch API calls with input values from CSV/JSONL/text file (`from_file` + `file_field` + `input_key`)
- **Dependent** — batch API calls using values extracted from a parent source's Parquet output (`dependency.from_source` + `dependency.field` + `input_key`)
- **Union** (`type: union`) — combines records from multiple parent sources into one (`sources` list + optional `dedupe_by`). All parent sources must have the same endpoint. Useful for merging multiple search results before a single dependent source
- **SQL** (`type: sql`) — runs a SQL query against a named database connection (`connection` + `query` or `query_file`). Downstream sources can depend on SQL output

`input` is accepted as an alias for `params` (preferred in YAML configs). `refresh` supports three values: `auto` (default — skipped with `--incremental` after first run), `always` (re-fetch every run), `never` (skip if data already exists). Dependency shorthand: `${source_id.field_path}` in `input` values auto-expands to `dependency` + `input_key` (e.g., `input: { user: "${search.urn.value}" }` is equivalent to `dependency: { from_source: search, field: urn.value }` + `input_key: user`).

Sources are topologically sorted by dependencies. `input_template` allows transforming extracted values before passing to API (e.g., `{type: company, value: "{value}"}`). Nested objects stored as JSON strings in Parquet are auto-parsed back when extracting with dot-notation paths.

**Three-Level Filtering**: The pipeline supports filtering at three independent stages:
- **Level 1 — `source.filter`**: Applied after collection, before LLM enrichment and Parquet write. Drops records entirely. Saves LLM tokens on irrelevant records.
- **Level 2 — `transform.filter`**: Applied after Parquet write, before exports only. Full records preserved in Parquet for dependency resolution.
- **Level 3 — `db_load.filter`**: Applied when loading records into a relational database. Parquet unchanged.
All three levels use the same safe expression syntax: `.field op value` with `and`/`or` combinators, supporting numbers, strings, booleans (`true`/`false`), and `null`.

**Per-Source Transform**: Optional `transform` block per source with `filter` (safe expression parser, e.g., `.count > 10 and .status == "active"`), `fields` (select/rename with dot-notation aliases), and `add_columns` (inject static values). Transforms apply to export destinations only — Parquet always stores full records to preserve dependency resolution.

**Per-Source Export**: Optional `export` list per source. Runs after Parquet write. Supports `type: file` (JSON/JSONL/CSV with `{{date}}`/`{{source}}`/`{{dataset}}` path templates) and `type: webhook` (POST records to URL with custom headers).

**Collect + Load-DB**: `anysite dataset collect --load-db <connection>` collects data and auto-loads into a database in one step. Used for scheduled pipelines.

**Run History**: `HistoryStore` records every collection run in SQLite (`~/.anysite/dataset_history.db`): start/finish time, status, record/source counts, duration, errors. `LogManager` stores per-run log files at `~/.anysite/logs/`.

**Scheduling**: `ScheduleGenerator` generates crontab entries and systemd timer/service units from `schedule.cron` in dataset config. Supports `--incremental` and `--load-db` flags in generated commands.

**Webhook Notifications**: `WebhookNotifier` sends POST notifications on collection complete/failure to URLs defined in `notifications.on_complete` / `notifications.on_failure`.

**Provenance Tracking**: Dependent and from_file source records are annotated with `_input_value` (the raw extracted value that produced the record) and `_parent_source` (parent source ID for dependent sources). Union source records are annotated with `_union_source` (ID of the parent source the record came from). This enables FK linking when loading into a relational database.

**Incremental Deduplication**: `MetadataStore` tracks which input values have been collected per source via `collected_inputs` in `metadata.json`. Running `--incremental` skips already-collected values for dependent and from_file sources. `anysite dataset reset-cursor` clears this state.

**Dot-Notation Query**: `expand_dot_fields()` converts `urn.value AS id` to `json_extract_string(urn, '$.value') AS id` for DuckDB queries. The `--source` and `--fields` options on `dataset query` auto-generate SQL with dot-notation expansion.

**Dataset DB Loading** (`dataset load-db`): `DatasetDbLoader` loads Parquet data into a relational database (SQLite/Postgres/ClickHouse). Features:
- Schema inference from Parquet records via `infer_table_schema()`
- Auto-increment `id` primary key per table
- FK linking via provenance: parent `_input_value` → child `{parent}_id` column
- Optional `db_load` config per source: field selection, dot-notation extraction, custom table names, field exclusion, `key` for diff-based incremental sync
- Topological loading order (parents before children)
- Diff-based incremental sync: when `db_load.key` is set and table exists with >=2 snapshots, diffs the two most recent and applies INSERT/DELETE/UPDATE delta
- `--snapshot YYYY-MM-DD` flag to load a specific snapshot date
- `--drop-existing` forces full INSERT of latest snapshot

**Dataset Storage Layout**:
```
<storage.path>/
  raw/<source_id>/<date>.parquet
  metadata.json
```

**LLM Enrichment** (in dataset pipeline): Optional `llm` list per source in dataset YAML. Steps run in order after API collection, before Parquet write. Four types: **enrich** (extract structured attributes via `add` specs), **classify** (categorize with explicit or auto-detected categories), **summarize** (concise text summaries), **generate** (text from custom prompt templates). Enriched fields are stored in Parquet alongside raw data and flow to DB via `db_load.fields`. Skip with `--no-llm` flag on `dataset collect`.

**LLM Subsystem** (`anysite llm`): LLM-powered analysis of collected dataset records using OpenAI or Anthropic. Supports summarization, classification (with auto-detect), enrichment with structured output, free-form text generation, cross-source record matching, and semantic deduplication. Optional — requires `pip install anysite-cli[llm]`. Registered in `main.py` via try/except ImportError. Configuration stored in `~/.anysite/config.yaml` under `llm:` key. Response caching in SQLite at `~/.anysite/llm_cache.db`. Rate limiting via token bucket, concurrent processing via asyncio semaphore.

**Database Subsystem** (`anysite db`): Named database connections, schema inspection, data insertion, SQL queries. Supports SQLite, PostgreSQL, and ClickHouse.

**Connection Storage**: `~/.anysite/connections.yaml`. Passwords stored directly (`password`) or via environment variable reference (`password_env`). Direct value takes priority.

**Adapter Pattern**: `DatabaseAdapter` ABC with implementations for SQLite (stdlib), PostgreSQL (psycopg v3), and ClickHouse (clickhouse-connect). Context manager for connect/disconnect. Methods: `execute`, `fetch_one`, `fetch_all`, `insert_batch`, `create_table`, `table_exists`, `get_table_schema`, `transaction`.

**Schema Inference**: `infer_table_schema()` auto-detects column types from JSON data: integer, float, boolean, date, datetime, url, email, json, varchar, text. Type merging across rows. Dialect-aware SQL type mapping (sqlite, postgres, mysql, clickhouse).

**Database Discovery** (`anysite db discover`): `DatabaseDiscoverer` introspects a connected database via raw SQL, dispatching on dialect (SQLite PRAGMAs, PostgreSQL information_schema/pg_catalog, ClickHouse system tables). Discovers tables, columns (with types, nullability, defaults, PKs), row counts, sample rows, indexes, and foreign keys. Auto-detects read-only status (PostgreSQL via `pg_is_in_recovery()` + transaction test, SQLite via filesystem permission check, ClickHouse via system.settings/system.grants). The `--read-only` flag on `db add` forces read-only; the `force_read_only` parameter on `discover()` propagates this. Result is a `DatabaseCatalog` dataclass with `to_dict()`/`from_dict()` serialization and `to_context_string()` for compact LLM context injection.

**Database Catalog** (`anysite db catalog`): `CatalogStore` persists `DatabaseCatalog` objects as YAML files at `~/.anysite/catalogs/<connection>.yaml`. Supports save/load/list/remove. Agents use `anysite db catalog --json` to discover available data and `to_context_string()` to inject schema into LLM prompts.

**LLM Catalog Enrichment**: `llm_describe_catalog()` enriches a catalog with LLM-generated descriptions in four steps: (1) describe each table, (2) describe columns per table, (3) detect implicit relationships (naming patterns like `user_id → users.id`), (4) generate overall database description. Uses `StructuredSchema` for typed JSON output. Triggered by `anysite db discover --with-llm`. Four built-in prompts added: `describe_table`, `describe_columns`, `describe_database`, `detect_relationships`.

**Credential Storage**: Both database passwords and LLM API keys support dual resolution — direct value (priority) with environment variable fallback. DB: `ConnectionConfig.get_password()` checks `password` then `password_env`. LLM: `get_api_key()` checks `api_key` then `api_key_env`. The `anysite db add --password` saves directly to `connections.yaml`; `anysite llm setup` saves directly to `config.yaml` when a key is pasted.

**Agent Protocol**: The CLI is agent-first — it auto-detects when stdout is a pipe (non-TTY) and switches to structured JSON envelope output. Key components:
- `resolve_json_output()` determines output mode: explicit `--json` flag > `--human` global flag > auto-detect via `stdout.isatty()`
- JSON envelope: `{"ok": true, "result": ..., "hints": [...], "meta": {"version": "...", "command": "..."}}` for success; `{"ok": false, "error": {"code": "...", "message": "...", "retryable": ..., "suggestions": [...]}, "meta": ...}` for errors
- Exit codes: 0 (success), 1 (error), 2 (usage), 3 (auth), 4 (not found), 5 (network/timeout/rate-limit)
- Error codes: every exception has a machine-readable `error_code` (e.g., `AUTH_FAILED`, `RATE_LIMIT`, `CONNECTION_NOT_FOUND`, `DATASET_ERROR`, `LLM_PROVIDER_ERROR`) with `retryable` flag and `suggestions` list
- Hints: every command returns next-step hints as `(action, command)` tuples, rendered in JSON envelope or dim text on stderr
- `--human` global flag forces human-readable output even in pipes
- `--non-interactive` disables interactive prompts (auto-enabled when stdin is not a TTY)
- Discovery payload: `anysite` with no subcommand in a pipe returns a JSON payload listing all commands, protocol, exit codes, installed extras, and `whats_new` (latest release highlights) via `build_discovery_payload()`
- Changelog: `anysite changelog --json` returns structured release history. `anysite changelog --since <version> --json` shows only changes after a specific version. Discovery payload includes `whats_new` key with latest release highlights
