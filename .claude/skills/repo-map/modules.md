# Module map of `src/anysite/`

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
- `api/schemas.py` - OpenAPI schema cache: fetch spec (`fetch_raw_openapi_spec`, `parse_openapi_spec`), resolve `$ref`, extract input/output, list endpoints, auto-convert CLI arg types. `_extract_properties()` recursively expands nested objects/arrays with dot-notation keys (e.g., `urn.value`, `experience[].title`) up to `max_depth=3`
- `api/graph.py` - Endpoint dependency graph: `build_graph()` from raw OpenAPI spec (nodes=endpoints, edges=data flow via typed ID types like `li:fsd_profile`, `ig:user`). `search_graph()` returns matches + upstream providers + downstream consumers. `get_endpoint_connections()` for single endpoint. Cache at `~/.anysite/graph.json`. Falls back to keyword search over schema.json when graph unavailable
- `config/settings.py` - Pydantic Settings with priority: CLI > ENV > config file > defaults
- `config/paths.py` - Config/cache file paths (`~/.anysite/config.yaml`, `~/.anysite/schema.json`, `~/.anysite/graph.json`)
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
- `test_api/` — API client, error codes, structured error output, dependency graph
- `test_batch/` — Batch executor, rate limiter, input parser
- `test_streaming/` — Progress and writer
- `test_output/` — Formatters and templates
- `test_utils/` — Field selection and retry
- `test_dataset/` — Dataset models, storage, collector (mocked API), DuckDB analyzer, DB loader (SQLite in-memory), transformer, exporters, history, scheduler, notifications, differ, guide command
- `test_db/` — Database adapters, schema inference, connection manager, operations, discovery engine (SQLite in-memory), catalog store, LLM description (mocked provider)
- `test_llm/` — LLM cache, CLI commands, models, processor, prompts, providers
