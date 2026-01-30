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

### 2. Make your first request

```bash
anysite linkedin user satyanadella
```

## Commands

### LinkedIn

```bash
# Get user profile
anysite linkedin user satyanadella
anysite linkedin user satyanadella --format table
anysite linkedin user satyanadella --fields "name,headline,follower_count"

# Search users
anysite linkedin users --keywords "CTO fintech" --count 20
anysite linkedin users --title "Director" --company "Google" --count 50

# Company info
anysite linkedin company anthropic
anysite linkedin company-employees anthropic --count 50
anysite linkedin company-posts anthropic --count 20

# Search posts
anysite linkedin posts --keywords "AI agents" --count 50
```

### Instagram

```bash
# Get user profile
anysite instagram user cristiano
anysite instagram user nike --format table

# Get user content
anysite instagram user-posts nike --count 20
anysite instagram user-reels nike --count 10

# Get post details
anysite instagram post CxYz123abc

# Search posts
anysite instagram search-posts --query "startup" --count 20
```

### Twitter/X

```bash
# Get user profile
anysite twitter user elonmusk
anysite twitter user openai --format table

# Get user posts
anysite twitter user-posts elonmusk --count 20

# Search
anysite twitter search-posts --query "AI agents" --count 50
anysite twitter search-users --query "AI researcher" --count 20
```

### Web Parser

```bash
# Parse web page
anysite web parse https://example.com
anysite web parse https://blog.example.com --only-main-content
anysite web parse https://company.com --extract-contacts
anysite web parse https://company.com --social-links-only

# Get sitemap
anysite web sitemap https://example.com --count 100
```

### Y Combinator

```bash
# Get company info
anysite yc company anthropic
anysite yc company stripe --format table

# Search companies
anysite yc search-companies --query "AI" --count 20
anysite yc search-companies --batch W24 --industry "B2B"

# Search founders
anysite yc search-founders --query "ML" --count 20
```

## Output Formats

```bash
--format json    # Default: Pretty JSON
--format jsonl   # Newline-delimited JSON (for streaming)
--format csv     # CSV with headers
--format table   # Rich table for terminal
```

## Field Selection

Reduce output size by selecting specific fields:

```bash
anysite linkedin user satyanadella --fields "name,headline,follower_count"
```

## Save to File

```bash
anysite linkedin users --keywords "CTO" --count 100 --output ctos.json
```

## Pipe to jq

```bash
anysite linkedin user satyanadella -q | jq '.follower_count'
```

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
# Clone the repository
git clone https://github.com/anysite/anysite-cli.git
cd anysite-cli

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install with dev dependencies
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
pytest --cov=anysite --cov-report=term-missing
```

### Linting

```bash
ruff check .
ruff format .
mypy src/
```

## License

MIT
