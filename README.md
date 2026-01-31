# Anysite CLI

Web data extraction for humans and AI agents.

## Installation

```bash
pip install anysite-cli
```

Or install from source:

```bash
git clone https://github.com/anysite/anysite-cli.git
cd anysite-cli
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

## Development

### Setup

```bash
git clone https://github.com/anysite/anysite-cli.git
cd anysite-cli
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
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
