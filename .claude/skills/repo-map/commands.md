# CLI command catalogue

```bash
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
