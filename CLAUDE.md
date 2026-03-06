# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Install with dataset support (duckdb, pyarrow)
pip install -e ".[dev,data]"

# Install with ClickHouse support
pip install -e ".[dev,clickhouse]"

# Run all tests
pytest

# Run single test file
pytest tests/test_cli/test_main.py

# Run single test
pytest tests/test_cli/test_main.py::test_version

# Run with coverage
pytest --cov=anysite --cov-report=term-missing

# Lint and format
ruff check src/
ruff check src/ --fix
ruff format src/

# Type check
mypy src/

# Test CLI directly
anysite --help
anysite api /api/linkedin/user user=satyanadella
anysite describe /api/linkedin/user
anysite schema update

# Dataset commands
anysite dataset init my-dataset
anysite dataset collect dataset.yaml
anysite dataset collect dataset.yaml --source linkedin_profiles --incremental --dry-run
anysite dataset collect dataset.yaml --no-llm
anysite dataset collect dataset.yaml --load-db pg
anysite dataset collect dataset.yaml --limit 10
anysite dataset status dataset.yaml
anysite dataset query dataset.yaml --sql "SELECT * FROM profiles LIMIT 10"
anysite dataset query dataset.yaml --source profiles --fields "name, urn.value AS urn_id, headline"
anysite dataset query dataset.yaml --source profiles --fields "name, headline" --exclude "_input_value,_parent_source"
anysite dataset query dataset.yaml --interactive
anysite dataset stats dataset.yaml --source profiles
anysite dataset profile dataset.yaml
anysite dataset load-db dataset.yaml -c pg --drop-existing
anysite dataset load-db dataset.yaml -c pg --snapshot 2026-01-15
anysite dataset history my-dataset
anysite dataset logs my-dataset --run 42
anysite dataset schedule dataset.yaml --incremental --load-db pg
anysite dataset schedule dataset.yaml --systemd --load-db pg
anysite dataset diff dataset.yaml --source profiles --key _input_value
anysite dataset diff dataset.yaml --source profiles --key urn.value --from 2026-01-30 --to 2026-02-01
anysite dataset diff dataset.yaml --source profiles --key urn.value --fields "name,headline,follower_count"
anysite dataset reset-cursor dataset.yaml
anysite dataset reset-cursor dataset.yaml --source profiles
anysite dataset guide
anysite dataset guide --section sources
anysite dataset guide --example advanced
anysite dataset guide --list
anysite dataset guide --json
anysite dataset validate dataset.yaml
anysite dataset validate dataset.yaml --json

# LLM commands
anysite llm setup                                                    # Interactive (human)
anysite llm setup --provider openai --api-key sk-xxx --no-test       # Non-interactive (agent)
anysite llm setup --provider anthropic --api-key-env ANTHROPIC_API_KEY --no-test
anysite llm summarize dataset.yaml --source profiles --fields "name,headline" --format table
anysite llm classify dataset.yaml --source posts --categories "positive,negative,neutral" --format table
anysite llm enrich dataset.yaml --source posts --add "sentiment:positive/negative/neutral" --add "language:string"
anysite llm generate dataset.yaml --source profiles --prompt "Write intro for {name}" --temperature 0.7
anysite llm match dataset.yaml --source-a profiles --source-b companies --top-k 3
anysite llm deduplicate dataset.yaml --source profiles --key name --threshold 0.8
anysite llm cache-stats
anysite llm cache-clear

# Auth commands
anysite auth login                          # Interactive browser-based OAuth2
anysite auth login --force --no-browser     # Re-authenticate without confirmation (agent)
anysite auth status
anysite auth status --json
anysite auth logout
anysite auth logout --force                 # Skip confirmation (agent)

# Database commands
anysite db add mydb
anysite db add pg --type postgres --host localhost --database mydb --user app --password secret
anysite db add pg --type postgres --host localhost --database mydb --user app --password-env PGPASS
anysite db add ch --type clickhouse --host ch.example.com --port 8443 --database analytics --user app --password secret --ssl
anysite db add replica --type postgres --host replica.example.com --read-only
anysite db list
anysite db test mydb
anysite db info mydb
anysite db remove mydb
anysite db schema mydb
anysite db schema mydb --table users
anysite db insert mydb --table users --stdin --auto-create
anysite db query mydb --sql "SELECT * FROM users LIMIT 10" --format table
anysite db query mydb --sql "SELECT * FROM users" --format parquet --output users.parquet
anysite db query mydb --sql "SELECT * FROM users" --format csv --output "reports/{{date}}/users.csv"
anysite db upsert mydb --table users --conflict-columns id --stdin
anysite db discover mydb
anysite db discover mydb --with-llm
anysite db discover mydb --tables users,posts --sample-rows 10
anysite db discover mydb --exclude-tables _migrations
anysite db catalog
anysite db catalog mydb
anysite db catalog mydb --table users
anysite db catalog mydb --json

# Changelog commands
anysite changelog                              # all releases, human-readable
anysite changelog --json                       # all releases, JSON for agents
anysite changelog --since 0.3.16 --json        # changes after 0.3.16
anysite changelog --last 1 --json              # latest release only
```

## Changelog Rule (MANDATORY)

**Every commit that adds features, fixes bugs, or changes behavior MUST include a corresponding update to `src/anysite/changelog.py`.** This is not optional — agents rely on the changelog to discover new capabilities after upgrades.

- Add a `Change(category=..., summary=...)` to the current version's `ChangeEntry` in `CHANGELOG`
- If bumping the version, create a new `ChangeEntry` at the top of the `CHANGELOG` list
- Categories: `"added"` (new feature), `"changed"` (behavior change), `"fixed"` (bug fix), `"removed"` (removed feature)
- Include `detail` for significant features, `example` for YAML/command snippets
- Keep summaries concise (one line) — agents parse them programmatically

## Release Process

When releasing a new version:

1. **Update version in THREE places:**
   - `pyproject.toml` — `version = "X.Y.Z"`
   - `src/anysite/__init__.py` — `__version__ = "X.Y.Z"`
   - `src/anysite/changelog.py` — add a new `ChangeEntry` at the top of `CHANGELOG` list with all changes since the last release

2. **Build and publish:**
   ```bash
   rm -rf dist/ && python -m build
   TWINE_USERNAME=__token__ TWINE_PASSWORD='<pypi-token>' python -m twine upload dist/*
   ```

3. **Commit and push:**
   ```bash
   git add pyproject.toml src/anysite/__init__.py src/anysite/changelog.py
   git commit -m "Bump version to X.Y.Z"
   git push origin main
   ```

## Architecture

**CLI Framework**: Typer with Rich for terminal output.

**Module Structure**:
- `main.py` - Typer app entry point. Registers `api`, `describe`, `schema`, `config`, `dataset` commands. Handles global options (`--api-key`, `--debug`, `--no-color`, `--json`, `--human`, `--non-interactive`). When invoked with no subcommand in a non-TTY pipe, returns a JSON discovery payload via `build_discovery_payload()`.
- `cli/config.py` - Config management commands (set, get, list, path, init, reset)
- `cli/executor.py` - Async execution wrappers: `run_search_command()` for list/search endpoints, `run_single_command()` for single-item + batch
- `cli/options.py` - Reusable Typer option type aliases (FormatOption, FieldsOption, etc.) and `ErrorHandling` enum
- `cli/exit_codes.py` - Standard exit codes: `EXIT_SUCCESS` (0), `EXIT_ERROR` (1), `EXIT_USAGE` (2), `EXIT_AUTH` (3), `EXIT_NOT_FOUND` (4), `EXIT_NETWORK` (5)
- `cli/json_output.py` - `json_response()`, `json_error()`, `json_error_from_exception()`, `resolve_json_output()`, `print_hints()`, `is_non_interactive()`: structured JSON envelope output with auto-detection of pipe/TTY
- `cli/discovery.py` - `build_discovery_payload()`: introspects Typer app to produce JSON discovery payload with commands, protocol, exit codes, installed extras, and `whats_new` from changelog
- `changelog.py` - Structured changelog for agent discovery. `CHANGELOG` list of `ChangeEntry` objects (newest first). `whats_new_payload()` for discovery integration. `get_changelog_since()` for filtered queries. Used by `anysite changelog` command
- `api/client.py` - Async HTTP client (`AnysiteClient`) with retry logic, exponential backoff, auth via `access-token` header
- `api/errors.py` - Exception hierarchy (AuthenticationError, RateLimitError, NotFoundError, ValidationError, ServerError, NetworkError, TimeoutError). Each has `error_code`, `exit_code`, `retryable`, `suggestions`, and `to_dict()` for structured JSON error output
- `api/schemas.py` - OpenAPI schema cache: fetch spec, resolve `$ref`, extract input/output, search/list endpoints, auto-convert CLI arg types. `_extract_properties()` recursively expands nested objects/arrays with dot-notation keys (e.g., `urn.value`, `experience[].title`) up to `max_depth=3`
- `config/settings.py` - Pydantic Settings with priority: CLI > ENV > config file > defaults
- `config/paths.py` - Config/cache file paths (`~/.anysite/config.yaml`, `~/.anysite/schema.json`)
- `output/formatters.py` - JSON, JSONL, CSV, Table formatters with field selection and exclusion
- `output/templates.py` - Filename templates for batch output (`{id}`, `{username}`, `{date}`, `{index}`)
- `batch/executor.py` - BatchExecutor: parallel/sequential execution with semaphore, error handling (stop/skip/retry), progress callbacks
- `batch/input.py` - InputParser: text, JSONL, CSV input file parsing
- `batch/rate_limiter.py` - Token bucket rate limiter (`"10/s"`, `"100/m"`)
- `streaming/writer.py` - StreamingWriter for JSONL/CSV with field filtering, append mode, auto-flush
- `streaming/progress.py` - Rich progress bars, auto-detect TTY, statistics
- `utils/fields.py` - Field selection with dot notation, array wildcards, built-in presets (minimal, contact, recruiting)
- `utils/retry.py` - RetryConfig and retry logic
- `dataset/__init__.py` - `check_data_deps()` — verifies optional duckdb/pyarrow are installed
- `dataset/models.py` - Pydantic models for dataset YAML config. `DatasetSource` is a discriminated union of `ApiSource`, `LlmSource`, `UnionSource`, `SqlSource` (with `_SourceBase` shared fields), selected by `_source_discriminator()` (defaults to `"api"`). `ApiSource.params` accepts `input` as a validation alias (preferred in YAML configs). `EnrichFieldSpec` provides structured alternative to string-based LLM add specs. Other models: `DatasetConfig`, `SourceDependency`, `StorageConfig`, `TransformConfig`, `ExportDestination`, `LLMStepConfig`, `ScheduleConfig`, `NotificationsConfig`, `WebhookNotification`, `DbLoadConfig`. Topological sort (Kahn's algorithm)
- `dataset/storage.py` - Parquet read/write via pyarrow, directory layout (`raw/<source_id>/<date>.parquet`), `MetadataStore` for `metadata.json`
- `dataset/collector.py` - Collection orchestrator: topo-sorted execution, five source types (independent, from_file, dependent, union, sql), per-source LLM enrichment/transform/export, run history, notifications. Uses `BatchExecutor` + `AnysiteClient`. Supports `--no-llm` to skip LLM steps
- `dataset/llm_enrichment.py` - LLM enrichment bridge: applies per-source LLM steps (enrich, classify, summarize, generate) after API collection, before Parquet write. Builds StructuredSchema from step config, dispatches to LLMProcessor, merges results into records. `_parse_add_specs()` accepts both string format and structured `EnrichFieldSpec` objects
- `dataset/analyzer.py` - DuckDB analytics: SQL query, column stats, profile, interactive shell. Registers views over Parquet files
- `dataset/transformer.py` - `RecordTransformer`: safe filter parser (no `eval()`), field selection with dot-notation/aliases, static column injection. Public `parse_filter()` function used by collector, db_loader, and RecordTransformer. `validate_filter()` returns error messages without raising (used by validator). Filter diagnostics detect common typos (`=` -> `==`, `&&` -> `and`, `||` -> `or`). Filter syntax: `.field > 10`, `.status == "active"`, `.active == true`, `and`/`or`
- `dataset/exporters.py` - Per-source export after Parquet write: `FileExporter` (JSON/JSONL/CSV with `{{date}}`/`{{source}}` templates), `WebhookExporter` (POST records to URL)
- `dataset/history.py` - `HistoryStore` (SQLite at `~/.anysite/dataset_history.db`): run start/finish tracking. `LogManager`: file-based per-run logs at `~/.anysite/logs/`
- `dataset/scheduler.py` - `ScheduleGenerator`: crontab and systemd timer unit generation from cron expressions
- `dataset/notifications.py` - `WebhookNotifier`: POST to webhook URLs on collection complete/failure
- `dataset/differ.py` - `DatasetDiffer`: compare two Parquet snapshots using DuckDB (added/removed/changed records). Supports dot-notation keys via `json_extract_string()`. `DiffResult` dataclass, `format_diff_table()` and `format_diff_records()` formatters with output field filtering
- `dataset/cli.py` - Typer subcommands: `init`, `collect` (with `--load-db`), `status`, `query`, `stats`, `profile`, `load-db`, `diff`, `history`, `logs`, `schedule`, `reset-cursor`, `guide`, `validate`
- `dataset/db_loader.py` - `DatasetDbLoader`: loads Parquet data into relational DB with FK linking via provenance, dot-notation field extraction, schema inference, diff-based incremental sync (`db_load.key` + `db_load.sync: full|append`). Supports diff-based incremental sync via `db_load.key` and `--snapshot` for loading specific dates
- `dataset/errors.py` - `DatasetError`, `CircularDependencyError`, `SourceNotFoundError`. All inherit from `AnysiteError` with `error_code` and `exit_code` for structured error output
- `dataset/guide.py` - Built-in dataset configuration guide: `GUIDE_SECTIONS` dict with `GuideSection` dataclasses covering all source types, params, dependencies, LLM, transforms, exports, db_load, storage, scheduling, notifications, incremental, validation. `EXAMPLE_CONFIGS` dict with complete YAML examples. Used by `anysite dataset guide` command with `--section`, `--example`, `--list`, `--json` options
- `dataset/validator.py` - `validate_dataset_config()`: fast config validation (<0.1s, no API calls). Checks dependency graph, filter expressions (with typo diagnostics), LLM add specs (string and `EnrichFieldSpec`). Returns `ValidationResult` with `errors` and `warnings`. Used by `anysite dataset validate` command
- `llm/__init__.py` - `check_llm_deps()`, `load_llm_config()`, `get_api_key()` — verifies optional openai/anthropic are installed, loads LLM config from `~/.anysite/config.yaml`. `get_api_key()` resolves direct `api_key` first, then `api_key_env` fallback
- `llm/models.py` - Dataclass models: `LLMProviderConfig` (with `api_key` direct + `api_key_env` fallback), `LLMConfig`, `LLMMessage`, `LLMResponse`, `StructuredSchema`, `ProcessorResult`
- `llm/errors.py` - `LLMError`, `ConfigError`, `ProviderError`, `PromptError`. All inherit from `AnysiteError` with `error_code`, `exit_code`, and `retryable` for structured error output
- `llm/providers.py` - `LLMProvider` ABC, `OpenAIProvider` (AsyncOpenAI, JSON Schema structured output), `AnthropicProvider` (AsyncAnthropic, system-prompt structured output), `create_provider()` factory
- `llm/cache.py` - `LLMCache` SQLite cache at `~/.anysite/llm_cache.db` with SHA256 keys, WAL mode
- `llm/prompts.py` - `PromptBuilder` with template/builtin support, `BUILTIN_PROMPTS` (summarize, classify, classify_auto_detect, match, deduplicate, enrich), `filter_record_fields()` with dot-notation
- `llm/processor.py` - `LLMProcessor`: async batch processing with rate limiting, semaphore concurrency, cache integration, JSON response parsing
- `llm/cli.py` - Typer subcommands: `setup`, `summarize`, `classify`, `match`, `deduplicate`, `enrich`, `generate`, `cache-stats`, `cache-clear`
- `db/__init__.py` - `check_db_deps()` — verifies optional psycopg is installed for Postgres
- `db/config.py` - `ConnectionConfig` (with `password`, `password_env`, `read_only`, `url_env` fields), `DatabaseType`, `OnConflict` enums and models. `get_password()` resolves direct `password` first, then `password_env` fallback
- `db/manager.py` - `ConnectionManager`: named connections stored in `~/.anysite/connections.yaml`, adapter factory
- `db/adapters/base.py` - `DatabaseAdapter` ABC: connect, execute, fetch, insert_batch, create_table, transaction
- `db/adapters/sqlite.py` - `SQLiteAdapter`: stdlib sqlite3, WAL mode, FK support, JSON serialization
- `db/adapters/postgres.py` - `PostgresAdapter`: psycopg v3, JSONB support, parameterized queries
- `db/adapters/clickhouse.py` - `ClickHouseAdapter`: clickhouse-connect (HTTP), MergeTree engines, no-op transactions, system table introspection
- `db/schema/inference.py` - `infer_table_schema()`: auto-detect column types from JSON data (integer, float, boolean, date, url, email, json, text)
- `db/schema/types.py` - `get_sql_type()`: maps inferred types to SQL types per dialect (sqlite, postgres, mysql, clickhouse)
- `db/operations/insert.py` - `insert_from_stream()`: batch insert with auto-create, conflict handling
- `db/operations/query.py` - `execute_query()`: SQL execution with output formatting
- `db/utils/sanitize.py` - `sanitize_identifier()`, `sanitize_table_name()`: safe SQL identifier quoting
- `db/discovery.py` - Data models (`ColumnInfo`, `IndexInfo`, `ForeignKeyInfo`, `ImplicitRelationship`, `TableInfo`, `DatabaseCatalog`) and `DatabaseDiscoverer` engine with dialect-specific introspection (SQLite via PRAGMAs, PostgreSQL via information_schema/pg_catalog, ClickHouse via system tables). `DatabaseCatalog.to_context_string()` for compact LLM context injection
- `db/catalog.py` - `CatalogStore` — YAML persistence at `~/.anysite/catalogs/<connection>.yaml`. Save/load/list/remove database catalogs
- `db/llm_describe.py` - `llm_describe_catalog()` — LLM-powered enrichment of catalogs: table descriptions, column descriptions, implicit relationship detection, overall database description. Reuses `LLMProcessor`, `LLMCache`, `StructuredSchema` from `anysite.llm`
- `db/cli.py` - Typer subcommands: `add`, `list`, `test`, `info`, `remove`, `schema`, `insert`, `upsert`, `query`, `create-table`, `discover`, `catalog`

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

## Common CLI Options Pattern

Reusable Typer option type aliases are defined in `cli/options.py`:
- `FormatOption` - output format (json/jsonl/csv/table)
- `FieldsOption` - comma-separated field selection
- `OutputOption` - file path for output
- `QuietOption` - suppress non-data output
- `ExcludeOption` - fields to exclude
- `CompactOption` - compact JSON output
- `FromFileOption`, `StdinOption` - batch input
- `ParallelOption`, `DelayOption`, `RateLimitOption` - concurrency control
- `OnErrorOption` - error handling mode (stop/skip/retry)
- `ProgressOption`, `StatsOption`, `VerboseOption` - feedback

## Testing

Tests are in `tests/` with subdirectories mirroring `src/anysite/`:
- `test_cli/` — CLI commands, discovery payload, JSON output, exit codes
- `test_api/` — API client, error codes and structured error output
- `test_batch/` — Batch executor, rate limiter, input parser
- `test_streaming/` — Progress and writer
- `test_output/` — Formatters and templates
- `test_utils/` — Field selection and retry
- `test_dataset/` — Dataset models, storage, collector (mocked API), DuckDB analyzer, DB loader (SQLite in-memory), transformer, exporters, history, scheduler, notifications, differ, guide command
- `test_db/` — Database adapters, schema inference, connection manager, operations, discovery engine (SQLite in-memory), catalog store, LLM description (mocked provider)
- `test_llm/` — LLM cache, CLI commands, models, processor, prompts, providers
