# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Install with dataset support (duckdb, pyarrow)
pip install -e ".[dev,data]"

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
anysite dataset collect dataset.yaml --load-db pg
anysite dataset status dataset.yaml
anysite dataset query dataset.yaml --sql "SELECT * FROM profiles LIMIT 10"
anysite dataset query dataset.yaml --source profiles --fields "name, urn.value AS urn_id, headline"
anysite dataset query dataset.yaml --interactive
anysite dataset stats dataset.yaml --source profiles
anysite dataset profile dataset.yaml
anysite dataset load-db dataset.yaml -c pg --drop-existing
anysite dataset history my-dataset
anysite dataset logs my-dataset --run 42
anysite dataset schedule dataset.yaml --incremental --load-db pg
anysite dataset schedule dataset.yaml --systemd --load-db pg
anysite dataset reset-cursor dataset.yaml
anysite dataset reset-cursor dataset.yaml --source profiles

# Database commands
anysite db add mydb
anysite db list
anysite db test mydb
anysite db info mydb
anysite db remove mydb
anysite db schema mydb
anysite db schema mydb --table users
anysite db insert mydb --table users --stdin --auto-create
anysite db query mydb --sql "SELECT * FROM users LIMIT 10" --format table
anysite db upsert mydb --table users --conflict-columns id --stdin
```

## Architecture

**CLI Framework**: Typer with Rich for terminal output.

**Module Structure**:
- `main.py` - Typer app entry point. Registers `api`, `describe`, `schema`, `config`, `dataset` commands. Handles global options (`--api-key`, `--debug`, `--no-color`).
- `cli/config.py` - Config management commands (set, get, list, path, init, reset)
- `cli/executor.py` - Async execution wrappers: `run_search_command()` for list/search endpoints, `run_single_command()` for single-item + batch
- `cli/options.py` - Reusable Typer option type aliases (FormatOption, FieldsOption, etc.) and `ErrorHandling` enum
- `api/client.py` - Async HTTP client (`AnysiteClient`) with retry logic, exponential backoff, auth via `access-token` header
- `api/errors.py` - Exception hierarchy (AuthenticationError, RateLimitError, NotFoundError, ValidationError, ServerError, NetworkError, TimeoutError)
- `api/schemas.py` - OpenAPI schema cache: fetch spec, resolve `$ref`, extract input/output, search/list endpoints, auto-convert CLI arg types
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
- `dataset/models.py` - Pydantic models for dataset YAML config (`DatasetConfig`, `DatasetSource`, `SourceDependency`, `StorageConfig`, `TransformConfig`, `ExportDestination`, `ScheduleConfig`, `NotificationsConfig`, `WebhookNotification`), topological sort (Kahn's algorithm)
- `dataset/storage.py` - Parquet read/write via pyarrow, directory layout (`raw/<source_id>/<date>.parquet`), `MetadataStore` for `metadata.json`
- `dataset/collector.py` - Collection orchestrator: topo-sorted execution, three source types (independent, from_file, dependent), per-source transform/export, run history, notifications. Uses `BatchExecutor` + `AnysiteClient`
- `dataset/analyzer.py` - DuckDB analytics: SQL query, column stats, profile, interactive shell. Registers views over Parquet files
- `dataset/transformer.py` - `RecordTransformer`: safe filter parser (no `eval()`), field selection with dot-notation/aliases, static column injection. Filter syntax: `.field > 10`, `.status == "active"`, `and`/`or`
- `dataset/exporters.py` - Per-source export after Parquet write: `FileExporter` (JSON/JSONL/CSV with `{{date}}`/`{{source}}` templates), `WebhookExporter` (POST records to URL)
- `dataset/history.py` - `HistoryStore` (SQLite at `~/.anysite/dataset_history.db`): run start/finish tracking. `LogManager`: file-based per-run logs at `~/.anysite/logs/`
- `dataset/scheduler.py` - `ScheduleGenerator`: crontab and systemd timer unit generation from cron expressions
- `dataset/notifications.py` - `WebhookNotifier`: POST to webhook URLs on collection complete/failure
- `dataset/cli.py` - Typer subcommands: `init`, `collect` (with `--load-db`), `status`, `query`, `stats`, `profile`, `load-db`, `history`, `logs`, `schedule`, `reset-cursor`
- `dataset/db_loader.py` - `DatasetDbLoader`: loads Parquet data into relational DB with FK linking via provenance, dot-notation field extraction, schema inference
- `dataset/errors.py` - `DatasetError`, `CircularDependencyError`, `SourceNotFoundError`
- `db/__init__.py` - `check_db_deps()` — verifies optional psycopg is installed for Postgres
- `db/config.py` - `ConnectionConfig`, `DatabaseType`, `OnConflict` enums and models
- `db/manager.py` - `ConnectionManager`: named connections stored in `~/.anysite/connections.yaml`, adapter factory
- `db/adapters/base.py` - `DatabaseAdapter` ABC: connect, execute, fetch, insert_batch, create_table, transaction
- `db/adapters/sqlite.py` - `SQLiteAdapter`: stdlib sqlite3, WAL mode, FK support, JSON serialization
- `db/adapters/postgres.py` - `PostgresAdapter`: psycopg v3, JSONB support, parameterized queries
- `db/schema/inference.py` - `infer_table_schema()`: auto-detect column types from JSON data (integer, float, boolean, date, url, email, json, text)
- `db/schema/types.py` - `get_sql_type()`: maps inferred types to SQL types per dialect (sqlite, postgres, mysql)
- `db/operations/insert.py` - `insert_from_stream()`: batch insert with auto-create, conflict handling
- `db/operations/query.py` - `execute_query()`: SQL execution with output formatting
- `db/utils/sanitize.py` - `sanitize_identifier()`, `sanitize_table_name()`: safe SQL identifier quoting
- `db/cli.py` - Typer subcommands: `add`, `list`, `test`, `info`, `remove`, `schema`, `insert`, `upsert`, `query`, `create-table`

**API Pattern**: All Anysite API endpoints use POST with JSON body. Auth is via `access-token` header.

**Universal API Command**: Instead of per-platform CLI modules, a single `anysite api` command works with any endpoint. Parameters are `key=value` pairs, auto-typed via the schema cache.

**Two Execution Paths**:
- `execute_search_command()` - for list/search endpoints (single request, optional streaming)
- `execute_single_command()` - for single-item endpoints with optional batch support (from-file, stdin, parallel)

**Schema Cache**: `anysite schema update` fetches the OpenAPI spec, resolves all `$ref`/`allOf`/`anyOf`, and caches a compact representation to `~/.anysite/schema.json`. Used by `anysite describe` and for auto-typing `api` command parameters.

**Config Location**: `~/.anysite/config.yaml`

**Dataset Subsystem** (`anysite dataset`): Multi-source data collection, Parquet storage, DuckDB analytics, relational DB loading, per-source transforms/exports, run history, scheduling, and webhook notifications. Optional — requires `pip install anysite-cli[data]`. Registered in `main.py` via try/except ImportError.

**Dataset YAML Config**: Declarative multi-source pipelines. Three source types:
- **Independent** — single API call with `params`
- **from_file** — batch API calls with input values from CSV/JSONL/text file (`from_file` + `file_field` + `input_key`)
- **Dependent** — batch API calls using values extracted from a parent source's Parquet output (`dependency.from_source` + `dependency.field` + `input_key`)

Sources are topologically sorted by dependencies. `input_template` allows transforming extracted values before passing to API (e.g., `{type: company, value: "{value}"}`). Nested objects stored as JSON strings in Parquet are auto-parsed back when extracting with dot-notation paths.

**Per-Source Transform**: Optional `transform` block per source with `filter` (safe expression parser, e.g., `.count > 10 and .status == "active"`), `fields` (select/rename with dot-notation aliases), and `add_columns` (inject static values). Transforms apply to export destinations only — Parquet always stores full records to preserve dependency resolution.

**Per-Source Export**: Optional `export` list per source. Runs after Parquet write. Supports `type: file` (JSON/JSONL/CSV with `{{date}}`/`{{source}}`/`{{dataset}}` path templates) and `type: webhook` (POST records to URL with custom headers).

**Collect + Load-DB**: `anysite dataset collect --load-db <connection>` collects data and auto-loads into a database in one step. Used for scheduled pipelines.

**Run History**: `HistoryStore` records every collection run in SQLite (`~/.anysite/dataset_history.db`): start/finish time, status, record/source counts, duration, errors. `LogManager` stores per-run log files at `~/.anysite/logs/`.

**Scheduling**: `ScheduleGenerator` generates crontab entries and systemd timer/service units from `schedule.cron` in dataset config. Supports `--incremental` and `--load-db` flags in generated commands.

**Webhook Notifications**: `WebhookNotifier` sends POST notifications on collection complete/failure to URLs defined in `notifications.on_complete` / `notifications.on_failure`.

**Provenance Tracking**: Dependent and from_file source records are annotated with `_input_value` (the raw extracted value that produced the record) and `_parent_source` (parent source ID for dependent sources). This enables FK linking when loading into a relational database.

**Incremental Deduplication**: `MetadataStore` tracks which input values have been collected per source via `collected_inputs` in `metadata.json`. Running `--incremental` skips already-collected values for dependent and from_file sources. `anysite dataset reset-cursor` clears this state.

**Dot-Notation Query**: `expand_dot_fields()` converts `urn.value AS id` to `json_extract_string(urn, '$.value') AS id` for DuckDB queries. The `--source` and `--fields` options on `dataset query` auto-generate SQL with dot-notation expansion.

**Dataset DB Loading** (`dataset load-db`): `DatasetDbLoader` loads Parquet data into a relational database (SQLite/Postgres). Features:
- Schema inference from Parquet records via `infer_table_schema()`
- Auto-increment `id` primary key per table
- FK linking via provenance: parent `_input_value` → child `{parent}_id` column
- Optional `db_load` config per source: field selection, dot-notation extraction, custom table names, field exclusion
- Topological loading order (parents before children)

**Dataset Storage Layout**:
```
<storage.path>/
  raw/<source_id>/<date>.parquet
  metadata.json
```

**Database Subsystem** (`anysite db`): Named database connections, schema inspection, data insertion, SQL queries. Supports SQLite and PostgreSQL.

**Connection Storage**: `~/.anysite/connections.yaml`. Passwords stored as environment variable references (`password_env: PG_PASS`).

**Adapter Pattern**: `DatabaseAdapter` ABC with implementations for SQLite (stdlib) and PostgreSQL (psycopg v3). Context manager for connect/disconnect. Methods: `execute`, `fetch_one`, `fetch_all`, `insert_batch`, `create_table`, `table_exists`, `get_table_schema`, `transaction`.

**Schema Inference**: `infer_table_schema()` auto-detects column types from JSON data: integer, float, boolean, date, datetime, url, email, json, varchar, text. Type merging across rows. Dialect-aware SQL type mapping (sqlite, postgres, mysql).

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
- `test_cli/` — CLI commands
- `test_api/` — API client
- `test_batch/` — Batch executor, rate limiter, input parser
- `test_streaming/` — Progress and writer
- `test_output/` — Formatters and templates
- `test_utils/` — Field selection and retry
- `test_dataset/` — Dataset models, storage, collector (mocked API), DuckDB analyzer, DB loader (SQLite in-memory), transformer, exporters, history, scheduler, notifications
- `test_db/` — Database adapters, schema inference, connection manager, operations
