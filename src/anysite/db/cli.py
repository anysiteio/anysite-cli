"""CLI commands for the database subsystem."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from anysite.db.config import ConnectionConfig, DatabaseType, OnConflict
from anysite.db.manager import ConnectionManager

app = typer.Typer(help="Store API data in SQL databases")


def _get_manager() -> ConnectionManager:
    return ConnectionManager()


def _get_config_or_exit(name: str) -> ConnectionConfig:
    """Get a connection config by name or exit with error."""
    config = _get_manager().get(name)
    if config is None:
        typer.echo(f"Error: connection '{name}' not found", err=True)
        typer.echo("Run 'anysite db list' to see available connections.", err=True)
        raise typer.Exit(1)
    return config


# ── Connection management ──────────────────────────────────────────────


@app.command("add")
def add(
    name: Annotated[
        str,
        typer.Argument(help="Connection name"),
    ],
    type: Annotated[
        DatabaseType,
        typer.Option("--type", "-t", help="Database type"),
    ] = DatabaseType.SQLITE,
    host: Annotated[
        str | None,
        typer.Option("--host", "-h", help="Database host"),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", "-p", help="Database port"),
    ] = None,
    database: Annotated[
        str | None,
        typer.Option("--database", "-d", help="Database name"),
    ] = None,
    user: Annotated[
        str | None,
        typer.Option("--user", "-u", help="Database user"),
    ] = None,
    password_env: Annotated[
        str | None,
        typer.Option("--password-env", help="Env var containing password"),
    ] = None,
    url_env: Annotated[
        str | None,
        typer.Option("--url-env", help="Env var containing connection URL"),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option("--path", help="Database file path (SQLite/DuckDB)"),
    ] = None,
    ssl: Annotated[
        bool,
        typer.Option("--ssl", help="Enable SSL"),
    ] = False,
) -> None:
    """Add a named database connection.

    \b
    Examples:
      anysite db add local --type sqlite --path ./data.db
      anysite db add prod --type postgres --host db.example.com --database analytics --user app --password-env DB_PASS
      anysite db add remote --type postgres --url-env DATABASE_URL
    """
    try:
        config = ConnectionConfig(
            name=name,
            type=type,
            host=host,
            port=port,
            database=database,
            user=user,
            password_env=password_env,
            url_env=url_env,
            path=path,
            ssl=ssl,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    manager = _get_manager()
    manager.add(config)

    console = Console()
    console.print(f"[green]Added[/green] connection '{name}' ({type.value})")


@app.command("list")
def list_connections() -> None:
    """List all saved database connections."""
    manager = _get_manager()
    connections = manager.list()

    if not connections:
        typer.echo("No connections configured.")
        typer.echo("Add one with: anysite db add <name> --type sqlite --path ./data.db")
        return

    console = Console()
    table = Table(title="Database Connections")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Location")

    for conn in connections:
        if conn.type in (DatabaseType.SQLITE, DatabaseType.DUCKDB):
            location = conn.path or ""
        elif conn.url_env:
            location = f"${conn.url_env}"
        else:
            parts = []
            if conn.user:
                parts.append(f"{conn.user}@")
            if conn.host:
                parts.append(conn.host)
            if conn.port:
                parts.append(f":{conn.port}")
            if conn.database:
                parts.append(f"/{conn.database}")
            location = "".join(parts)

        table.add_row(conn.name, conn.type.value, location)

    console.print(table)


@app.command("test")
def test(
    name: Annotated[
        str,
        typer.Argument(help="Connection name to test"),
    ],
) -> None:
    """Test a database connection."""
    _get_config_or_exit(name)

    console = Console()
    console.print(f"Testing connection '{name}'...")

    manager = _get_manager()
    try:
        info = manager.test(name)
        console.print(f"[green]Connected[/green] to {info.get('type', 'unknown')}")
        for key, value in info.items():
            console.print(f"  {key}: {value}")
    except Exception as e:
        console.print(f"[red]Failed[/red]: {e}")
        raise typer.Exit(1) from None


@app.command("remove")
def remove(
    name: Annotated[
        str,
        typer.Argument(help="Connection name to remove"),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Remove a saved database connection."""
    _get_config_or_exit(name)

    if not force:
        confirm = typer.confirm(f"Remove connection '{name}'?")
        if not confirm:
            raise typer.Abort()

    manager = _get_manager()
    manager.remove(name)

    console = Console()
    console.print(f"[green]Removed[/green] connection '{name}'")


@app.command("info")
def info(
    name: Annotated[
        str,
        typer.Argument(help="Connection name"),
    ],
) -> None:
    """Show details about a database connection."""
    config = _get_config_or_exit(name)

    console = Console()
    console.print(f"[bold]Connection: {config.name}[/bold]")
    console.print(f"  Type: {config.type.value}")

    if config.path:
        console.print(f"  Path: {config.path}")
    if config.host:
        console.print(f"  Host: {config.host}")
    if config.port:
        console.print(f"  Port: {config.port}")
    if config.database:
        console.print(f"  Database: {config.database}")
    if config.user:
        console.print(f"  User: {config.user}")
    if config.password_env:
        console.print(f"  Password: ${config.password_env}")
    if config.url_env:
        console.print(f"  URL: ${config.url_env}")
    if config.ssl:
        console.print("  SSL: enabled")
    if config.options:
        console.print(f"  Options: {config.options}")


# ── Schema commands ────────────────────────────────────────────────────


@app.command("schema")
def schema(
    name: Annotated[
        str,
        typer.Argument(help="Connection name"),
    ],
    table: Annotated[
        str | None,
        typer.Option("--table", "-t", help="Table to inspect"),
    ] = None,
) -> None:
    """Inspect database schema — list tables or show table columns.

    \b
    Examples:
      anysite db schema mydb                    # list all tables
      anysite db schema mydb --table users      # show columns of 'users'
    """
    config = _get_config_or_exit(name)
    manager = _get_manager()
    adapter = manager.get_adapter(config)

    console = Console()

    with adapter:
        if table:
            if not adapter.table_exists(table):
                typer.echo(f"Error: table '{table}' does not exist", err=True)
                raise typer.Exit(1)

            columns = adapter.get_table_schema(table)
            tbl = Table(title=f"Table: {table}")
            tbl.add_column("Column", style="bold")
            tbl.add_column("Type")
            tbl.add_column("Nullable")
            tbl.add_column("Primary Key")

            for col in columns:
                tbl.add_row(col["name"], col["type"], col["nullable"], col["primary_key"])
            console.print(tbl)
        else:
            # List tables - adapter-agnostic via querying system tables
            tables = _list_tables(adapter, config.type)
            if not tables:
                console.print("[dim]No tables found[/dim]")
                return

            tbl = Table(title="Tables")
            tbl.add_column("Table Name", style="bold")
            for t in tables:
                tbl.add_row(t)
            console.print(tbl)


def _list_tables(adapter: Any, db_type: DatabaseType) -> list[str]:
    """List all tables in the database."""
    if db_type == DatabaseType.SQLITE:
        rows = adapter.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r["name"] for r in rows]
    elif db_type == DatabaseType.POSTGRES:
        rows = adapter.fetch_all(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        return [r["tablename"] for r in rows]
    return []


@app.command("create-table")
def create_table(
    name: Annotated[
        str,
        typer.Argument(help="Connection name"),
    ],
    table: Annotated[
        str,
        typer.Option("--table", "-t", help="Table name to create"),
    ],
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Infer schema from JSONL on stdin"),
    ] = False,
    pk: Annotated[
        str | None,
        typer.Option("--pk", help="Primary key column"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show CREATE TABLE SQL without executing"),
    ] = False,
) -> None:
    """Create a table with schema inferred from JSON data.

    \b
    Examples:
      echo '{"name":"test","age":30}' | anysite db create-table mydb --table users --stdin
      echo '{"id":1,"name":"test"}' | anysite db create-table mydb --table users --stdin --pk id --dry-run
    """
    import json

    from anysite.db.schema.inference import infer_table_schema
    from anysite.db.utils.sanitize import sanitize_identifier, sanitize_table_name

    if not stdin:
        typer.echo("Error: --stdin is required (provide JSON data via stdin)", err=True)
        raise typer.Exit(1)

    content = sys.stdin.read().strip()
    if not content:
        typer.echo("Error: no data on stdin", err=True)
        raise typer.Exit(1)

    # Parse input
    rows: list[dict[str, Any]] = []
    try:
        data = json.loads(content)
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]
        elif isinstance(data, dict):
            rows = [data]
    except json.JSONDecodeError:
        for line in content.split("\n"):
            line = line.strip()
            if line:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except json.JSONDecodeError:
                    continue

    if not rows:
        typer.echo("Error: no valid JSON objects found in input", err=True)
        raise typer.Exit(1)

    config = _get_config_or_exit(name)
    manager = _get_manager()
    dialect = config.type.value

    schema = infer_table_schema(table, rows)
    sql_types = schema.to_sql_types(dialect)

    safe_table = sanitize_table_name(table)
    col_defs = []
    for col_name, col_type in sql_types.items():
        safe_col = sanitize_identifier(col_name)
        pk_suffix = " PRIMARY KEY" if col_name == pk else ""
        col_defs.append(f"  {safe_col} {col_type}{pk_suffix}")
    create_sql = f"CREATE TABLE IF NOT EXISTS {safe_table} (\n" + ",\n".join(col_defs) + "\n)"

    console = Console()

    if dry_run:
        console.print(f"[dim]-- Inferred from {len(rows)} row(s)[/dim]")
        console.print(create_sql)
        return

    adapter = manager.get_adapter(config)
    with adapter:
        if adapter.table_exists(table):
            typer.echo(f"Error: table '{table}' already exists", err=True)
            raise typer.Exit(1)
        adapter.create_table(table, sql_types, primary_key=pk)
        console.print(f"[green]Created[/green] table '{table}' with {len(sql_types)} columns")


# ── Data commands ──────────────────────────────────────────────────────


@app.command("insert")
def insert(
    name: Annotated[
        str,
        typer.Argument(help="Connection name"),
    ],
    table: Annotated[
        str,
        typer.Option("--table", "-t", help="Target table"),
    ],
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Read JSON data from stdin"),
    ] = False,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read JSON data from file"),
    ] = None,
    auto_create: Annotated[
        bool,
        typer.Option("--auto-create", help="Create table if it doesn't exist"),
    ] = False,
    pk: Annotated[
        str | None,
        typer.Option("--pk", help="Primary key column (for auto-create)"),
    ] = None,
    on_conflict: Annotated[
        OnConflict,
        typer.Option("--on-conflict", help="Conflict handling: error, ignore, replace, update"),
    ] = OnConflict.ERROR,
    conflict_columns: Annotated[
        str | None,
        typer.Option("--conflict-columns", help="Comma-separated conflict columns (for upsert)"),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", help="Rows per batch insert"),
    ] = 100,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress non-data output"),
    ] = False,
) -> None:
    """Insert JSON data into a database table.

    Reads JSONL (one JSON object per line) or a JSON array from stdin or file.

    \b
    Examples:
      echo '{"name":"test","value":42}' | anysite db insert mydb --table demo --stdin --auto-create
      anysite api /api/linkedin/user user=satyanadella | anysite db insert mydb --table users --stdin
      anysite db insert mydb --table users --file data.jsonl
    """
    from anysite.db.operations.insert import insert_from_file, insert_from_stdin

    if not stdin and not file:
        typer.echo("Error: provide --stdin or --file", err=True)
        raise typer.Exit(1)

    if file and not file.exists():
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(1)

    conflict_cols = [c.strip() for c in conflict_columns.split(",")] if conflict_columns else None

    config = _get_config_or_exit(name)
    manager = _get_manager()
    adapter = manager.get_adapter(config)

    console = Console()

    with adapter:
        if stdin:
            count = insert_from_stdin(
                adapter,
                table,
                on_conflict=on_conflict,
                conflict_columns=conflict_cols,
                auto_create=auto_create,
                primary_key=pk,
                batch_size=batch_size,
                quiet=quiet,
            )
        else:
            assert file is not None
            count = insert_from_file(
                adapter,
                table,
                file,
                on_conflict=on_conflict,
                conflict_columns=conflict_cols,
                auto_create=auto_create,
                primary_key=pk,
                batch_size=batch_size,
                quiet=quiet,
            )

    if not quiet:
        console.print(f"[green]Inserted[/green] {count} row(s) into '{table}'")


@app.command("upsert")
def upsert(
    name: Annotated[
        str,
        typer.Argument(help="Connection name"),
    ],
    table: Annotated[
        str,
        typer.Option("--table", "-t", help="Target table"),
    ],
    conflict_columns: Annotated[
        str,
        typer.Option("--conflict-columns", help="Comma-separated conflict columns"),
    ],
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Read JSON data from stdin"),
    ] = False,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read JSON data from file"),
    ] = None,
    auto_create: Annotated[
        bool,
        typer.Option("--auto-create", help="Create table if it doesn't exist"),
    ] = False,
    pk: Annotated[
        str | None,
        typer.Option("--pk", help="Primary key column (for auto-create)"),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", help="Rows per batch insert"),
    ] = 100,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress non-data output"),
    ] = False,
) -> None:
    """Upsert JSON data — insert or update on conflict.

    Shorthand for `insert --on-conflict update --conflict-columns ...`.

    \b
    Examples:
      anysite api /api/linkedin/user user=satyanadella \\
        | anysite db upsert mydb --table users --conflict-columns linkedin_url --stdin
    """
    from anysite.db.operations.insert import insert_from_file, insert_from_stdin

    if not stdin and not file:
        typer.echo("Error: provide --stdin or --file", err=True)
        raise typer.Exit(1)

    if file and not file.exists():
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(1)

    conflict_cols = [c.strip() for c in conflict_columns.split(",")]

    config = _get_config_or_exit(name)
    manager = _get_manager()
    adapter = manager.get_adapter(config)

    console = Console()

    with adapter:
        if stdin:
            count = insert_from_stdin(
                adapter,
                table,
                on_conflict=OnConflict.UPDATE,
                conflict_columns=conflict_cols,
                auto_create=auto_create,
                primary_key=pk,
                batch_size=batch_size,
                quiet=quiet,
            )
        else:
            assert file is not None
            count = insert_from_file(
                adapter,
                table,
                file,
                on_conflict=OnConflict.UPDATE,
                conflict_columns=conflict_cols,
                auto_create=auto_create,
                primary_key=pk,
                batch_size=batch_size,
                quiet=quiet,
            )

    if not quiet:
        console.print(f"[green]Upserted[/green] {count} row(s) into '{table}'")


# ── Query command ──────────────────────────────────────────────────────


@app.command("query")
def query(
    name: Annotated[
        str,
        typer.Argument(help="Connection name"),
    ],
    sql: Annotated[
        str | None,
        typer.Option("--sql", help="SQL query to execute"),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read SQL from file"),
    ] = None,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format (json/jsonl/csv/table)"),
    ] = "table",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Save output to file"),
    ] = None,
    fields: Annotated[
        str | None,
        typer.Option("--fields", help="Comma-separated fields to include"),
    ] = None,
) -> None:
    """Run a SQL query against a database.

    \b
    Examples:
      anysite db query mydb --sql "SELECT * FROM users LIMIT 10"
      anysite db query mydb --sql "SELECT * FROM users" --format csv --output users.csv
      anysite db query mydb --file queries/report.sql --format json
    """
    from anysite.db.operations.query import execute_query, execute_query_from_file

    if not sql and not file:
        typer.echo("Error: provide --sql or --file", err=True)
        raise typer.Exit(1)

    if file and not file.exists():
        typer.echo(f"Error: SQL file not found: {file}", err=True)
        raise typer.Exit(1)

    config = _get_config_or_exit(name)
    manager = _get_manager()
    adapter = manager.get_adapter(config)

    with adapter:
        try:
            if file:
                results = execute_query_from_file(adapter, file)
            else:
                assert sql is not None
                results = execute_query(adapter, sql)
        except Exception as e:
            typer.echo(f"Query error: {e}", err=True)
            raise typer.Exit(1) from None

    _output_results(results, format, output, fields)


def _output_results(
    data: list[dict[str, Any]],
    format: str = "table",
    output: Path | None = None,
    fields: str | None = None,
) -> None:
    """Output query results using the existing formatter pipeline."""
    from anysite.cli.options import parse_fields
    from anysite.output.formatters import OutputFormat, format_output

    try:
        fmt = OutputFormat(format.lower())
    except ValueError:
        typer.echo(f"Error: invalid format '{format}', use json/jsonl/csv/table", err=True)
        raise typer.Exit(1) from None

    include_fields = parse_fields(fields)
    format_output(data, fmt, include_fields, output, quiet=False)
