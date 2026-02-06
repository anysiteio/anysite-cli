<p align="center">
  <img src="assets/logo.png" alt="Anysite" width="200">
</p>

# Anysite CLI

A command-line tool designed for AI agents to collect, analyze, and store web data — with full support for humans too.

**Agent-native protocol.** Auto-detects pipes and subprocesses, switches to structured JSON output. Discovery payload on first run, machine-readable exit codes, error codes with `retryable` flag and `suggestions`, next-step hints on every command. Zero configuration for agents — just call the binary.

**Self-describing API.** 118+ endpoints with `anysite describe`: input parameters, output fields with nested object/array expansion, dot-notation paths for dependency chains. An agent discovers the schema, plans collection, and executes — no documentation lookup needed.

**Declarative data pipelines.** Define multi-source collection workflows in YAML: dependency chains between sources, union merges, incremental collection that skips already-fetched data, per-source transforms and exports, automatic topological execution. One `anysite dataset collect` replaces hundreds of lines of scripting.

**LLM analysis without burning tokens.** Offload enrichment, classification, summarization, and deduplication to cheaper LLMs (OpenAI, Anthropic). Results are cached in SQLite — repeat runs cost nothing. Agents keep their context window for reasoning, not data crunching.

**Database-ready output.** Auto-infer schemas from JSON, create tables, and load into SQLite or PostgreSQL with a single command. Foreign keys are linked automatically via provenance tracking. Diff-based incremental sync keeps your database up to date without full reloads.

Supports **LinkedIn** (profiles, companies, jobs, Sales Navigator, email lookup), **Instagram** (profiles, posts, reels, comments), **Twitter/X**, **Reddit**, **YouTube** (channels, videos, subtitles), **Y Combinator**, **SEC EDGAR**, **GitHub**, **Amazon**, **Google News**, **Trustpilot**, **TripAdvisor**, **Hacker News**, web page parsing, and [60+ more sources](https://anysite.io) via the Anysite API.

## Installation

```bash
pip install anysite-cli
```

Optional extras:

```bash
pip install "anysite-cli[data]"       # DuckDB + PyArrow for dataset pipelines
pip install "anysite-cli[postgres]"   # PostgreSQL support
pip install "anysite-cli[all]"        # All optional dependencies
```

## Agent Protocol

anysite CLI is **agent-first**: it auto-detects when stdout is not a TTY (pipe, subprocess) and switches all output to structured JSON. No flags needed.

### Discovery

Run `anysite` with no arguments in a pipe to get a full discovery payload:

```bash
anysite | jq '.result'
```

Returns:
- `commands` — all available commands with descriptions and subcommands
- `agent_protocol` — how auto-JSON, `--json`, `--human`, `--non-interactive` work
- `output_schema` — success/error envelope format
- `exit_codes` — machine-readable exit code meanings
- `installed_extras` — which optional packages are available (`data`, `llm`, `postgres`)

Discover API endpoints:

```bash
anysite describe                          # list all 118+ endpoints
anysite describe --search "company"       # search by keyword
anysite describe /api/linkedin/company    # input params + output fields with nested expansion
```

Nested fields are expanded with dot-notation:

```
Output fields (15):
    name                           string
    urn                            object
      .type                        string
      .value                       string
    experience                     array[object]
      .title                       string
      .company_urn                 string
```

Use these paths in `--fields`, `dependency.field`, and `db_load.fields`.

### JSON Envelope

Every command in pipe mode returns a JSON envelope:

**Success:**
```json
{
  "ok": true,
  "result": { ... },
  "hints": [{"action": "Next step", "command": "anysite ..."}],
  "meta": {"version": "0.2.0", "command": "anysite db add"}
}
```

**Error:**
```json
{
  "ok": false,
  "error": {
    "code": "AUTH_FAILED",
    "message": "Authentication failed",
    "retryable": false,
    "suggestions": ["Set API key: anysite config set api_key <key>"]
  },
  "meta": {"version": "0.2.0"}
}
```

Check `ok` for success/failure. Use `error.code` for programmatic handling. Use `error.retryable` to decide whether to retry. Use `error.suggestions` and `hints` for next steps.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Usage error (invalid args, missing params) |
| 3 | Authentication failed |
| 4 | Resource not found |
| 5 | Network / timeout / rate limit |

### Output Mode Flags

| Context | Default | Override |
|---------|---------|----------|
| Pipe / subprocess (no TTY) | JSON envelope | `--human` to force human text |
| Terminal (TTY) | Human-readable Rich text | `--json` to force JSON envelope |

`--non-interactive` disables interactive prompts (auto-enabled when stdin is not a TTY).

### Hints

Every command returns next-step hints — in JSON (`hints` array) and human mode (dim text on stderr). Agents discover follow-up commands without consulting documentation.

### Built-in Guide

```bash
anysite dataset guide                        # full YAML config reference
anysite dataset guide --section sources      # specific section
anysite dataset guide --example advanced     # complete example config
anysite dataset guide --json                 # structured JSON for agents
```

## Quick Start

### 1. Configure your API key

```bash
anysite config set api_key sk-xxxxx
```

Or set environment variable:

```bash
export ANYSITE_API_KEY=sk-xxxxx
```

### 2. Update the schema cache

```bash
anysite schema update
```

### 3. Make your first request

```bash
anysite api /api/linkedin/user user=satyanadella
```

## The `api` Command

A single universal command for calling any API endpoint:

```bash
anysite api <endpoint> [key=value ...] [OPTIONS]
```

Parameters are passed as `key=value` pairs. Types are auto-converted using the schema cache.

```bash
# LinkedIn
anysite api /api/linkedin/user user=satyanadella
anysite api /api/linkedin/company company=anthropic
anysite api /api/linkedin/search/users title=CTO count=50 --format csv

# Instagram
anysite api /api/instagram/user user=cristiano
anysite api /api/instagram/user/posts user=nike count=20

# Twitter/X
anysite api /api/twitter/user user=elonmusk --format table

# Web parsing
anysite api /api/web/parse url=https://example.com

# Y Combinator
anysite api /api/yc/company company=anthropic
```

## Output Formats

```bash
--format json    # Default: Pretty JSON
--format jsonl   # Newline-delimited JSON (for streaming)
--format csv     # CSV with headers
--format table   # Rich table for terminal
```

## Field Selection

```bash
# Include specific fields (dot notation and wildcards supported)
anysite api /api/linkedin/user user=satyanadella --fields "name,headline,follower_count"

# Exclude fields
anysite api /api/linkedin/user user=satyanadella --exclude "certifications,recommendations"

# Compact JSON
anysite api /api/linkedin/user user=satyanadella --compact
```

Built-in field presets: `minimal`, `contact`, `recruiting`.

## Save to File

```bash
anysite api /api/linkedin/search/users title=CTO count=100 --output ctos.json
anysite api /api/linkedin/search/users title=CTO count=100 --output ctos.csv --format csv
```

## Pipe to jq

```bash
anysite api /api/linkedin/user user=satyanadella -q | jq '.follower_count'
```

## Batch Processing

Process multiple inputs from a file or stdin:

```bash
# From a text file (one value per line)
anysite api /api/linkedin/user --from-file users.txt --input-key user

# From JSONL (one JSON object per line)
anysite api /api/linkedin/user --from-file users.jsonl

# From stdin
cat users.txt | anysite api /api/linkedin/user --stdin --input-key user

# Parallel execution
anysite api /api/linkedin/user --from-file users.txt --input-key user --parallel 5

# Rate limiting
anysite api /api/linkedin/user --from-file users.txt --input-key user --rate-limit "10/s"

# Error handling
anysite api /api/linkedin/user --from-file users.txt --input-key user --on-error skip

# Progress bar and stats
anysite api /api/linkedin/user --from-file users.txt --input-key user --progress --stats
```

Input file formats: plain text (one value per line), JSONL, CSV.

## Dataset Pipelines

Collect multi-source datasets with dependency chains, store as Parquet, query with DuckDB, and load into a relational database. Includes per-source transforms, file/webhook exports, run history, scheduling, and webhook notifications.

### Create a dataset

```bash
anysite dataset init my-dataset
```

Edit `my-dataset/dataset.yaml` to define sources:

```yaml
name: my-dataset
sources:
  # Search sources (can be combined with union)
  - id: search_cto
    endpoint: /api/linkedin/search/users
    params: { keywords: "CTO fintech", count: 50 }

  - id: search_vp
    endpoint: /api/linkedin/search/users
    params: { keywords: "VP Engineering", count: 50 }

  # Union combines multiple sources (must have same endpoint)
  - id: all_candidates
    type: union
    sources: [search_cto, search_vp]
    dedupe_by: urn.value                  # Optional: remove duplicates by field

  # Dependent source using union as parent
  - id: profiles
    endpoint: /api/linkedin/user
    dependency:
      from_source: all_candidates
      field: urn.value
    input_key: user

  - id: companies
    endpoint: /api/linkedin/company
    from_file: companies.txt
    input_key: company
    transform:                          # Post-collection transform (for exports)
      filter: '.employee_count > 10'
      fields: [name, url, employee_count]
      add_columns:
        batch: "q1-2026"
    export:                             # Export to file/webhook after Parquet write
      - type: file
        path: ./output/companies-{{date}}.csv
        format: csv
    db_load:
      key: _input_value                    # Unique key for incremental sync
      sync: full                           # full (default) or append (no DELETE)
      fields: [name, url, employee_count]

  - id: employees
    endpoint: /api/linkedin/company/employees
    dependency:
      from_source: companies
      field: urn.value
    input_key: companies
    input_template:
      companies:
        - type: company
          value: "{value}"
      count: 5
    refresh: always                       # Re-collect every run with --incremental
    db_load:
      key: urn.value                       # Unique key for incremental sync
      sync: append                         # Keep old records (no DELETE on diff)
      fields: [name, url, headline]

storage:
  format: parquet
  path: ./data/

schedule:
  cron: "0 9 * * *"                    # Daily at 9 AM

notifications:
  on_complete:
    - url: "https://hooks.slack.com/xxx"
  on_failure:
    - url: "https://alerts.example.com/fail"
```

### Collect, query, and load

```bash
# Preview collection plan
anysite dataset collect dataset.yaml --dry-run

# Collect data (supports --incremental to skip already-collected inputs)
anysite dataset collect dataset.yaml

# Collect and auto-load into PostgreSQL
anysite dataset collect dataset.yaml --load-db pg

# Check status
anysite dataset status dataset.yaml

# Query with SQL (DuckDB)
anysite dataset query dataset.yaml --sql "SELECT * FROM companies LIMIT 10"

# Query with dot-notation field extraction
anysite dataset query dataset.yaml --source profiles --fields "name, urn.value AS urn_id"

# Interactive SQL shell
anysite dataset query dataset.yaml --interactive

# Column stats and data profiling
anysite dataset stats dataset.yaml --source companies
anysite dataset profile dataset.yaml

# Load into PostgreSQL with automatic FK linking (incremental sync with db_load.key)
anysite dataset load-db dataset.yaml -c pg

# Drop and reload from latest snapshot
anysite dataset load-db dataset.yaml -c pg --drop-existing

# Load a specific snapshot date
anysite dataset load-db dataset.yaml -c pg --snapshot 2026-01-15

# Run history and logs
anysite dataset history my-dataset
anysite dataset logs my-dataset --run 42

# Generate cron/systemd schedule
anysite dataset schedule dataset.yaml --incremental --load-db pg

# Compare snapshots (diff two collection dates, supports dot-notation keys)
anysite dataset diff dataset.yaml --source employees --key _input_value
anysite dataset diff dataset.yaml --source profiles --key urn.value --fields "name,headline"

# Reset incremental state
anysite dataset reset-cursor dataset.yaml
```

### Incremental Collection

When collecting data from `from_file` or `dependency` sources, anysite tracks which input values have already been processed. This allows resuming collection without re-fetching data you already have.

**How it works:**
1. After collecting a source, input values are saved to `metadata.json` (`collected_inputs`)
2. On next run with `--incremental`, these values are skipped
3. Only new input values are collected

```bash
# First run — collects all 1000 companies from file
anysite dataset collect dataset.yaml
# → Collected: 1000 records

# Add 50 new companies to the input file, run with --incremental
anysite dataset collect dataset.yaml --incremental
# → Skipped: 1000 (already collected), Collected: 50 (new only)

# Force re-collection of everything
anysite dataset reset-cursor dataset.yaml
anysite dataset collect dataset.yaml
# → Collected: 1050 records
```

**Per-source control with `refresh`:**
```yaml
sources:
  - id: profiles
    refresh: auto      # (default) respects --incremental, skips collected inputs

  - id: activity
    refresh: always    # ignores --incremental, always re-collects
                       # useful for time-sensitive data (posts, activity feeds)
```

**Reset cursor:**
```bash
# Reset all sources — next run collects everything
anysite dataset reset-cursor dataset.yaml

# Reset specific source only
anysite dataset reset-cursor dataset.yaml --source profiles
```

**Typical workflow for scheduled pipelines:**
```bash
# Daily cron with incremental — only fetches new data
anysite dataset schedule dataset.yaml --incremental --load-db pg

# Weekly full refresh — reset and collect all
anysite dataset reset-cursor dataset.yaml && anysite dataset collect dataset.yaml --load-db pg
```

## Database

Manage database connections and run queries.

```bash
# Add a connection (--password saves directly in connections.yaml)
anysite db add pg --type postgres --host localhost --database mydb --user app --password secret
# Or reference an existing env var
anysite db add pg --type postgres --host localhost --database mydb --user app --password-env PGPASS
# Mark connection as read-only (prevents write operations)
anysite db add replica --type postgres --host replica.example.com --database mydb --user reader --read-only

# List and test connections
anysite db list
anysite db test pg

# Query
anysite db query pg --sql "SELECT * FROM companies" --format table

# Insert data (auto-create table from schema inference)
cat data.jsonl | anysite db insert pg --table users --stdin --auto-create

# Upsert with conflict handling
cat updates.jsonl | anysite db upsert pg --table users --conflict-columns id --stdin

# Inspect schema
anysite db schema pg --table users
```

### Database Discovery

Introspect database schema, sample data, and optionally enrich with LLM descriptions:

```bash
# Discover schema (tables, columns, types, FKs, indexes, row counts, sample data)
anysite db discover mydb

# Discover with LLM-generated table/column descriptions and implicit relationship detection
anysite db discover mydb --with-llm

# Filter tables
anysite db discover mydb --tables users,posts --sample-rows 10
anysite db discover mydb --exclude-tables _migrations

# View saved catalogs
anysite db catalog                       # List all catalogs
anysite db catalog mydb                  # Show full catalog
anysite db catalog mydb --table users    # Show specific table
anysite db catalog mydb --json           # JSON output for agents
```

Read-only access is auto-detected during discovery. Use `--read-only` on `db add` to force it.

Supports SQLite and PostgreSQL. Passwords stored directly (`--password`) or via env var reference (`--password-env`).

## LLM Analysis

LLM-powered analysis of collected dataset records. Summarize, classify, enrich, generate text, match records across sources, and find semantic duplicates.

```bash
pip install "anysite-cli[llm]"        # OpenAI + Anthropic SDKs
```

### Setup

```bash
anysite llm setup
```

Configures provider (OpenAI or Anthropic), API key (paste directly or reference an env var), and default model. Tests the connection. Direct keys are saved in `~/.anysite/config.yaml`.

### Commands

```bash
# Classify records into categories (auto-detects categories if --categories omitted)
anysite llm classify dataset.yaml --source posts --categories "positive,negative,neutral" --format table

# Summarize each record
anysite llm summarize dataset.yaml --source profiles --fields "name,headline" --max-length 50

# Enrich records with LLM-extracted attributes
anysite llm enrich dataset.yaml --source posts \
  --add "sentiment:positive/negative/neutral" \
  --add "language:string" \
  --add "quality_score:1-10"

# Generate text using record fields as template variables
anysite llm generate dataset.yaml --source profiles \
  --prompt "Write a LinkedIn intro for {name} who works as {headline}" \
  --temperature 0.7

# Match records between two sources
anysite llm match dataset.yaml --source-a profiles --source-b companies --top-k 3

# Find semantic duplicates
anysite llm deduplicate dataset.yaml --source profiles --key name --threshold 0.8
```

Common options: `--provider`, `--model`, `--fields`, `--format`, `--output`, `--parallel`, `--rate-limit`, `--temperature`, `--dry-run`, `--no-cache`, `--prompt`, `--prompt-file`.

### Cache

```bash
anysite llm cache-stats    # Show cache statistics
anysite llm cache-clear    # Clear all cached responses
```

Responses are cached in SQLite at `~/.anysite/llm_cache.db`. Use `--no-cache` to skip cache lookup.

## Configuration

Configuration is stored in `~/.anysite/config.yaml`.

```bash
# Set a value
anysite config set api_key sk-xxxxx
anysite config set defaults.format table

# Get a value
anysite config get api_key

# List all settings
anysite config list

# Show config file path
anysite config path

# Initialize interactively
anysite config init

# Reset to defaults
anysite config reset --force
```

### Configuration Priority

1. CLI arguments (`--api-key`)
2. Environment variables (`ANYSITE_API_KEY`)
3. Config file (`~/.anysite/config.yaml`)
4. Defaults

## Global Options

```bash
anysite [OPTIONS] COMMAND

Options:
  --api-key TEXT       API key (or set ANYSITE_API_KEY)
  --base-url TEXT      API base URL
  --debug              Enable debug output
  --no-color           Disable colored output
  --json               Force JSON envelope output (auto-enabled in pipes)
  --human              Force human-readable output (override auto-JSON in pipes)
  --non-interactive    Disable interactive prompts (auto-enabled when stdin is not a TTY)
  --version, -v        Show version
  --help               Show help
```

## Claude Code Skill

Install the anysite-cli skill for Claude Code to get AI-assisted data collection:

```bash
# Add marketplace
/plugin marketplace add https://github.com/anysiteio/agent-skills

# Install skill
/plugin install anysite-cli@anysite-skills
```

The skill gives Claude Code knowledge of all anysite commands, dataset pipeline configuration, and database operations.

## Development

### Setup

```bash
git clone https://github.com/anysiteio/anysite-cli.git
cd anysite-cli
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# With dataset + database support
pip install -e ".[dev,data]"
```

### Run Tests

```bash
pytest
pytest --cov=anysite --cov-report=term-missing
```

### Linting

```bash
ruff check src/
ruff format src/
mypy src/
```

## License

MIT
