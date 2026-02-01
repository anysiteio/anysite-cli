# Anysite CLI

Web data extraction for humans and AI agents.

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

Or install from source:

```bash
git clone https://github.com/anysiteio/anysite-cli.git
cd anysite-cli
python -m venv .venv
source .venv/bin/activate
pip install -e .
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

## Endpoint Discovery

Browse and search all available API endpoints:

```bash
# List all endpoints
anysite describe

# Describe a specific endpoint (input params + output fields)
anysite describe /api/linkedin/company
anysite describe linkedin.user

# Search by keyword
anysite describe --search "company"

# JSON output for scripts/agents
anysite describe --json -q
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
    db_load:
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

# Load into PostgreSQL with automatic FK linking
anysite dataset load-db dataset.yaml -c pg --drop-existing

# Run history and logs
anysite dataset history my-dataset
anysite dataset logs my-dataset --run 42

# Generate cron/systemd schedule
anysite dataset schedule dataset.yaml --incremental --load-db pg

# Reset incremental state
anysite dataset reset-cursor dataset.yaml
```

## Database

Manage database connections and run queries.

```bash
# Add a connection (--password auto-stores via env var reference)
anysite db add pg --type postgres --host localhost --database mydb --user app --password secret
# Or reference an existing env var
anysite db add pg --type postgres --host localhost --database mydb --user app --password-env PGPASS

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

Supports SQLite and PostgreSQL. Passwords stored as env var references.

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
  --api-key TEXT     API key (or set ANYSITE_API_KEY)
  --base-url TEXT    API base URL
  --debug            Enable debug output
  --no-color         Disable colored output
  --version, -v      Show version
  --help             Show help
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
