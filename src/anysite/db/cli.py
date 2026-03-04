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

app = typer.Typer(
    help="Store API data in SQL databases",
    invoke_without_command=True,
    epilog="Run 'anysite db <command> --help' for details on each command.",
)


@app.callback(invoke_without_command=True)
def db_callback(ctx: typer.Context) -> None:
    """Database subsystem entry point."""
    if ctx.invoked_subcommand is None:
        from anysite.cli.discovery import build_command_detail, is_pipe_mode

        if is_pipe_mode():
            import json

            typer.echo(json.dumps(build_command_detail("db", ctx), indent=2))
            raise typer.Exit(0)
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def _get_manager() -> ConnectionManager:
    return ConnectionManager()


def _get_config_or_exit(name: str, *, json_output: bool = False) -> ConnectionConfig:
    """Get a connection config by name or exit with error."""
    config = _get_manager().get(name)
    if config is None:
        available = [c.name for c in _get_manager().list()]
        if json_output:
            from anysite.cli.json_output import json_error

            json_error(
                "CONNECTION_NOT_FOUND",
                f"Connection '{name}' not found",
                suggestions=[
                    f"Available connections: {', '.join(available) or 'none'}",
                    "Add one with: anysite db add <name> --type sqlite --path ./data.db",
                ],
            )
        typer.echo(f"Error: connection '{name}' not found", err=True)
        if available:
            typer.echo(f"Available: {', '.join(available)}", err=True)
        else:
            typer.echo(
                "Add one with: anysite db add <name> --type sqlite --path ./data.db", err=True
            )
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
    password: Annotated[
        str | None,
        typer.Option("--password", help="Database password (stored via auto-generated env var)"),
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
    read_only: Annotated[
        bool,
        typer.Option(
            "--read-only", help="Force connection as read-only (prevents write operations)"
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress non-data output"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Add a named database connection.

    \b
    Examples:
      anysite db add local --type sqlite --path ./data.db
      anysite db add prod --type postgres --host db.example.com --database analytics --user app --password-env DB_PASS
      anysite db add remote --type postgres --url-env DATABASE_URL
      anysite db add replica --type postgres --host replica.example.com --read-only
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    if password and password_env:
        typer.echo("Error: --password and --password-env are mutually exclusive", err=True)
        raise typer.Exit(1)

    try:
        config = ConnectionConfig(
            name=name,
            type=type,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            password_env=password_env,
            url_env=url_env,
            path=path,
            ssl=ssl,
            read_only=read_only,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    manager = _get_manager()
    manager.add(config)

    hints = [
        ("Test connection", f"anysite db test {name}"),
        ("View schema", f"anysite db schema {name}"),
        ("Insert data", f"anysite db insert {name} --table <table> --stdin"),
        ("Discover structure", f"anysite db discover {name}"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"name": name, "type": type.value},
            hints=hints,
            command="anysite db add",
        )
        return

    console = Console()
    console.print(f"[green]Added[/green] connection '{name}' ({type.value})")
    if password:
        console.print("[dim]Password saved in ~/.anysite/connections.yaml[/dim]")

    from anysite.cli.json_output import print_hints

    print_hints(hints, quiet=quiet)


@app.command("list")
def list_connections(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """List all saved database connections.

    \b
    Examples:
      anysite db list
      anysite db list --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    manager = _get_manager()
    connections = manager.list()

    if json_output:
        from anysite.cli.json_output import json_response

        if not connections:
            json_response([], command="anysite db list")
            return

        items = []
        for conn in connections:
            entry: dict[str, Any] = {
                "name": conn.name,
                "type": conn.type.value,
                "read_only": conn.read_only,
            }
            if conn.type in (DatabaseType.SQLITE, DatabaseType.DUCKDB):
                entry["path"] = conn.path or ""
            elif conn.url_env:
                entry["url_env"] = conn.url_env
            else:
                if conn.host:
                    entry["host"] = conn.host
                if conn.port:
                    entry["port"] = conn.port
                if conn.database:
                    entry["database"] = conn.database
                if conn.user:
                    entry["user"] = conn.user
            items.append(entry)

        json_response(items, command="anysite db list")
        return

    if not connections:
        typer.echo("No connections configured.")
        typer.echo("Add one with: anysite db add <name> --type sqlite --path ./data.db")
        return

    console = Console()
    table = Table(title="Database Connections")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Location")
    table.add_column("Access")

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

        # Resolve access: config flag takes priority, then catalog discovery
        if conn.read_only:
            access = "[yellow]read-only[/yellow]"
        else:
            store = _get_catalog_store()
            cat = store.load(conn.name)
            if cat is not None and cat.read_only is True:
                access = "[yellow]read-only[/yellow]"
            elif cat is not None and cat.read_only is False:
                access = "[green]read-write[/green]"
            else:
                access = ""
        table.add_row(conn.name, conn.type.value, location, access)

    console.print(table)


@app.command("test")
def test(
    name: Annotated[
        str,
        typer.Argument(help="Connection name to test"),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Test a database connection.

    \b
    Examples:
      anysite db test mydb
      anysite db test mydb --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    _get_config_or_exit(name, json_output=json_output)

    console = Console()

    if not json_output:
        console.print(f"Testing connection '{name}'...")

    manager = _get_manager()
    try:
        info = manager.test(name)
    except Exception as e:
        if json_output:
            from anysite.cli.json_output import json_error

            json_error("CONNECTION_FAILED", str(e))
        console.print(f"[red]Failed[/red]: {e}")
        raise typer.Exit(1) from None

    hints = [
        ("View schema", f"anysite db schema {name}"),
        ("Run a query", f'anysite db query {name} --sql "SELECT 1"'),
        ("Discover structure", f"anysite db discover {name}"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(info, hints=hints, command="anysite db test")
        return

    console.print(f"[green]Connected[/green] to {info.get('type', 'unknown')}")
    for key, value in info.items():
        console.print(f"  {key}: {value}")

    from anysite.cli.json_output import print_hints

    print_hints(hints, quiet=False)


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
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Remove a saved database connection.

    \b
    Examples:
      anysite db remove mydb
      anysite db remove mydb --force
      anysite db remove mydb --json --force
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    _get_config_or_exit(name, json_output=json_output)

    if not force:
        from anysite.cli.json_output import is_non_interactive

        if is_non_interactive():
            typer.echo(
                f"Error: removing '{name}' requires confirmation. "
                "Use --force to skip confirmation in non-interactive mode.",
                err=True,
            )
            raise typer.Exit(1)
        confirm = typer.confirm(f"Remove connection '{name}'?")
        if not confirm:
            raise typer.Abort()

    manager = _get_manager()
    manager.remove(name)

    hints = [
        ("List remaining connections", "anysite db list"),
        ("Add new connection", "anysite db add <name> --type sqlite --path ./data.db"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"name": name, "removed": True},
            hints=hints,
            command="anysite db remove",
        )
        return

    console = Console()
    console.print(f"[green]Removed[/green] connection '{name}'")

    from anysite.cli.json_output import print_hints

    print_hints(hints, quiet=False)


@app.command("info")
def info(
    name: Annotated[
        str,
        typer.Argument(help="Connection name"),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Show details about a database connection.

    \b
    Examples:
      anysite db info mydb
      anysite db info mydb --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config = _get_config_or_exit(name, json_output=json_output)

    if json_output:
        from anysite.cli.json_output import json_response

        data: dict[str, Any] = {
            "name": config.name,
            "type": config.type.value,
        }
        if config.path:
            data["path"] = config.path
        if config.host:
            data["host"] = config.host
        if config.port:
            data["port"] = config.port
        if config.database:
            data["database"] = config.database
        if config.user:
            data["user"] = config.user
        if config.password_env:
            data["password_env"] = config.password_env
        if config.url_env:
            data["url_env"] = config.url_env
        if config.ssl:
            data["ssl"] = config.ssl
        if config.read_only:
            data["read_only"] = config.read_only
        if config.options:
            data["options"] = config.options

        json_response(data, command="anysite db info")
        return

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
    if config.read_only:
        console.print("  Read-only: [yellow]yes[/yellow]")
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
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Inspect database schema -- list tables or show table columns.

    \b
    Examples:
      anysite db schema mydb                    # list all tables
      anysite db schema mydb --table users      # show columns of 'users'
      anysite db schema mydb --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config = _get_config_or_exit(name, json_output=json_output)
    manager = _get_manager()
    adapter = manager.get_adapter(config)

    console = Console()

    with adapter:
        if table:
            if not adapter.table_exists(table):
                if json_output:
                    from anysite.cli.json_output import json_error

                    json_error(
                        "TABLE_NOT_FOUND",
                        f"Table '{table}' does not exist",
                    )
                typer.echo(f"Error: table '{table}' does not exist", err=True)
                raise typer.Exit(1)

            columns = adapter.get_table_schema(table)

            if json_output:
                from anysite.cli.json_output import json_response

                json_response(
                    {"table": table, "columns": columns},
                    command="anysite db schema",
                )
                return

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

            if json_output:
                from anysite.cli.json_output import json_response

                hints = [
                    ("View table detail", f"anysite db schema {name} --table <table>"),
                    (
                        "Query data",
                        f'anysite db query {name} --sql "SELECT * FROM <table> LIMIT 10"',
                    ),
                    ("Discover", f"anysite db discover {name}"),
                ]
                json_response(
                    {"tables": tables},
                    hints=hints,
                    command="anysite db schema",
                )
                return

            if not tables:
                console.print("[dim]No tables found[/dim]")
                return

            tbl = Table(title="Tables")
            tbl.add_column("Table Name", style="bold")
            for t in tables:
                tbl.add_row(t)
            console.print(tbl)

            from anysite.cli.json_output import print_hints

            print_hints(
                [
                    ("View table detail", f"anysite db schema {name} --table <table>"),
                    (
                        "Query data",
                        f'anysite db query {name} --sql "SELECT * FROM <table> LIMIT 10"',
                    ),
                    ("Discover", f"anysite db discover {name}"),
                ],
                quiet=False,
            )


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
    elif db_type == DatabaseType.CLICKHOUSE:
        rows = adapter.fetch_all(
            "SELECT name FROM system.tables "
            "WHERE database = currentDatabase() "
            "AND engine NOT IN ('View', 'MaterializedView') "
            "ORDER BY name"
        )
        return [r["name"] for r in rows]
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
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Create a table with schema inferred from JSON data.

    \b
    Examples:
      echo '{"name":"test","age":30}' | anysite db create-table mydb --table users --stdin
      echo '{"id":1,"name":"test"}' | anysite db create-table mydb --table users --stdin --pk id --dry-run
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

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

    config = _get_config_or_exit(name, json_output=json_output)
    manager = _get_manager()
    dialect = config.type.value

    inferred_schema = infer_table_schema(table, rows)
    sql_types = inferred_schema.to_sql_types(dialect)

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

    hints = [
        ("Insert data", f"anysite db insert {name} --table {table} --stdin"),
        ("View schema", f"anysite db schema {name} --table {table}"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"table": table, "columns": len(sql_types)},
            hints=hints,
            command="anysite db create-table",
        )
        return

    console.print(f"[green]Created[/green] table '{table}' with {len(sql_types)} columns")

    from anysite.cli.json_output import print_hints

    print_hints(hints, quiet=False)


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
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
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
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    from anysite.db.operations.insert import insert_from_file, insert_from_stdin

    if not stdin and not file:
        typer.echo("Error: provide --stdin or --file", err=True)
        raise typer.Exit(1)

    if file and not file.exists():
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(1)

    conflict_cols = [c.strip() for c in conflict_columns.split(",")] if conflict_columns else None

    config = _get_config_or_exit(name, json_output=json_output)
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

    hints = [
        ("Query inserted data", f'anysite db query {name} --sql "SELECT * FROM {table} LIMIT 10"'),
        ("View table schema", f"anysite db schema {name} --table {table}"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"table": table, "rows_inserted": count},
            hints=hints,
            command="anysite db insert",
        )
        return

    if not quiet:
        console.print(f"[green]Inserted[/green] {count} row(s) into '{table}'")

        from anysite.cli.json_output import print_hints

        print_hints(hints, quiet=quiet)


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
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Upsert JSON data -- insert or update on conflict.

    Shorthand for `insert --on-conflict update --conflict-columns ...`.

    \b
    Examples:
      anysite api /api/linkedin/user user=satyanadella \\
        | anysite db upsert mydb --table users --conflict-columns linkedin_url --stdin
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    from anysite.db.operations.insert import insert_from_file, insert_from_stdin

    if not stdin and not file:
        typer.echo("Error: provide --stdin or --file", err=True)
        raise typer.Exit(1)

    if file and not file.exists():
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(1)

    conflict_cols = [c.strip() for c in conflict_columns.split(",")]

    config = _get_config_or_exit(name, json_output=json_output)
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

    hints = [
        ("Query upserted data", f'anysite db query {name} --sql "SELECT * FROM {table} LIMIT 10"'),
        ("View table schema", f"anysite db schema {name} --table {table}"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"table": table, "rows_upserted": count},
            hints=hints,
            command="anysite db upsert",
        )
        return

    if not quiet:
        console.print(f"[green]Upserted[/green] {count} row(s) into '{table}'")

        from anysite.cli.json_output import print_hints

        print_hints(hints, quiet=quiet)


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
        typer.Option("--file", "--sql-file", "-f", help="Read SQL from file"),
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
    no_truncate: Annotated[
        bool,
        typer.Option("--no-truncate", help="Disable column truncation in table output"),
    ] = False,
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

    _output_results(results, format, output, fields, no_truncate=no_truncate)


def _output_results(
    data: list[dict[str, Any]],
    format: str = "table",
    output: Path | None = None,
    fields: str | None = None,
    *,
    no_truncate: bool = False,
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
    format_output(data, fmt, include_fields, output, quiet=False, no_truncate=no_truncate)


def _get_catalog_store() -> Any:
    from anysite.db.catalog import CatalogStore

    return CatalogStore()


# ── Discovery commands ────────────────────────────────────────────────


@app.command("discover")
def discover(
    name: Annotated[
        str,
        typer.Argument(help="Connection name to discover"),
    ],
    with_llm: Annotated[
        bool,
        typer.Option("--with-llm", help="Generate LLM descriptions for tables and columns"),
    ] = False,
    sample_rows_count: Annotated[
        int,
        typer.Option("--sample-rows", help="Sample rows per table"),
    ] = 1,
    tables: Annotated[
        str | None,
        typer.Option("--tables", help="Comma-separated list of tables to include"),
    ] = None,
    exclude_tables: Annotated[
        str | None,
        typer.Option("--exclude-tables", help="Comma-separated list of tables to skip"),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="LLM provider override (openai/anthropic)"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="LLM model override"),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Skip LLM cache"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Minimal output"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output catalog as JSON"),
    ] = False,
) -> None:
    """Discover database schema, sample data, and optionally describe with LLM.

    Introspects tables, columns, types, foreign keys, indexes, row counts,
    and sample data. Saves the result as a catalog for future reference.

    \b
    Examples:
      anysite db discover mydb
      anysite db discover mydb --with-llm
      anysite db discover mydb --tables users,posts --sample-rows 10
      anysite db discover mydb --exclude-tables _migrations,_temp
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    import json as json_mod

    from anysite.db.discovery import DatabaseDiscoverer

    config = _get_config_or_exit(name)
    manager = _get_manager()
    adapter = manager.get_adapter(config)
    console = Console()

    include = [t.strip() for t in tables.split(",")] if tables else None
    exclude = [t.strip() for t in exclude_tables.split(",")] if exclude_tables else None

    with adapter:
        if not quiet:
            console.print(f"Discovering [bold]{name}[/bold] ({config.type.value})...")

        discoverer = DatabaseDiscoverer(adapter, config.type.value, name)
        catalog = discoverer.discover(
            sample_rows=sample_rows_count,
            include_tables=include,
            exclude_tables=exclude,
            force_read_only=config.read_only,
        )

    if with_llm:
        import asyncio

        from anysite.db.llm_describe import llm_describe_catalog

        if not quiet:
            console.print("Enriching with LLM descriptions...")

        asyncio.run(
            llm_describe_catalog(
                catalog,
                provider_override=provider,
                model_override=model,
                no_cache=no_cache,
            )
        )

    # Save catalog
    store = _get_catalog_store()
    path = store.save(catalog)

    if json_output:
        typer.echo(json_mod.dumps(catalog.to_dict(), indent=2, default=str))
    elif not quiet:
        access = ""
        if catalog.read_only is True:
            access = " [yellow](read-only)[/yellow]"
        elif catalog.read_only is False:
            access = " [green](read-write)[/green]"
        console.print(f"\n[green]Discovered[/green] {len(catalog.tables)} table(s){access}")
        for t in catalog.tables:
            row_info = f" ({t.row_count:,} rows)" if t.row_count is not None else ""
            desc = f" — {t.description}" if t.description else ""
            console.print(f"  {t.name}: {len(t.columns)} columns{row_info}{desc}")
        console.print(f"\n[dim]Catalog saved to {path}[/dim]")

        from anysite.cli.json_output import print_hints

        print_hints(
            [
                ("View catalog", f"anysite db catalog {name}"),
                ("Query data", f'anysite db query {name} --sql "SELECT * FROM <table> LIMIT 10"'),
                ("Export as JSON", f"anysite db catalog {name} --json"),
            ],
            quiet=quiet,
        )


@app.command("catalog")
def catalog(
    name: Annotated[
        str | None,
        typer.Argument(help="Connection name (omit to list all catalogs)"),
    ] = None,
    table: Annotated[
        str | None,
        typer.Option("--table", "-t", help="Show specific table detail"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format (table/json)"),
    ] = "table",
) -> None:
    """View saved database catalogs.

    Without arguments, lists all saved catalogs.
    With a connection name, shows the full catalog.
    With --table, shows detail for a specific table.

    \b
    Examples:
      anysite db catalog                           # list all catalogs
      anysite db catalog mydb                      # show full catalog
      anysite db catalog mydb --table users         # show table detail
      anysite db catalog mydb --json                # JSON output for agents
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    import json as json_mod

    store = _get_catalog_store()
    console = Console()

    if name is None:
        # List all catalogs
        catalogs = store.list()
        if not catalogs:
            console.print("[dim]No catalogs found. Run 'anysite db discover <name>' first.[/dim]")
            return

        if json_output or format == "json":
            typer.echo(json_mod.dumps(catalogs, indent=2))
            return

        tbl = Table(title="Database Catalogs")
        tbl.add_column("Connection", style="bold")
        tbl.add_column("Type")
        tbl.add_column("Tables")
        tbl.add_column("Discovered")
        tbl.add_column("LLM")

        for c in catalogs:
            tbl.add_row(
                c["name"],
                c["database_type"],
                c["table_count"],
                c["discovered_at"][:19] if c["discovered_at"] else "",
                "yes" if c["llm_enriched"] == "True" else "no",
            )
        console.print(tbl)
        return

    # Show specific catalog
    cat = store.load(name)
    if cat is None:
        typer.echo(
            f"Error: no catalog for '{name}'. Run 'anysite db discover {name}' first.", err=True
        )
        raise typer.Exit(1)

    if table:
        # Show single table detail
        t = cat.get_table(table)
        if t is None:
            typer.echo(f"Error: table '{table}' not in catalog for '{name}'", err=True)
            available = [tb.name for tb in cat.tables]
            typer.echo(f"Available tables: {', '.join(available)}", err=True)
            raise typer.Exit(1)

        if json_output or format == "json":
            typer.echo(json_mod.dumps(t.to_dict(), indent=2, default=str))
            return

        _print_table_detail(console, t)
        return

    # Show full catalog
    if json_output or format == "json":
        typer.echo(json_mod.dumps(cat.to_dict(), indent=2, default=str))
        return

    _print_catalog(console, cat)


def _print_table_detail(console: Console, t: Any) -> None:
    """Print detailed info for a single table."""
    from anysite.db.discovery import TableInfo

    assert isinstance(t, TableInfo)

    header = f"[bold]{t.name}[/bold]"
    if t.row_count is not None:
        header += f" ({t.row_count:,} rows)"
    console.print(header)
    if t.description:
        console.print(f"  [dim]{t.description}[/dim]")
    console.print()

    # Columns
    col_table = Table(title="Columns")
    col_table.add_column("Name", style="bold")
    col_table.add_column("Type")
    col_table.add_column("PK")
    col_table.add_column("Nullable")
    col_table.add_column("Default")
    col_table.add_column("Description")

    for col in t.columns:
        col_table.add_row(
            col.name,
            col.type,
            "yes" if col.primary_key else "",
            "yes" if col.nullable else "no",
            col.default or "",
            col.description or "",
        )
    console.print(col_table)

    # Indexes
    if t.indexes:
        console.print()
        idx_table = Table(title="Indexes")
        idx_table.add_column("Name")
        idx_table.add_column("Columns")
        idx_table.add_column("Unique")
        for idx in t.indexes:
            idx_table.add_row(idx.name, ", ".join(idx.columns), "yes" if idx.unique else "")
        console.print(idx_table)

    # Foreign keys
    if t.foreign_keys:
        console.print()
        fk_table = Table(title="Foreign Keys")
        fk_table.add_column("Columns")
        fk_table.add_column("References")
        for fk in t.foreign_keys:
            fk_table.add_row(
                ", ".join(fk.constrained_columns),
                f"{fk.referred_table}({', '.join(fk.referred_columns)})",
            )
        console.print(fk_table)

    # Sample rows
    if t.sample_rows:
        console.print()
        sample_table = Table(title=f"Sample Rows ({len(t.sample_rows)})")
        if t.sample_rows:
            for key in t.sample_rows[0]:
                sample_table.add_column(key)
            for row in t.sample_rows:
                sample_table.add_row(*[str(v) if v is not None else "" for v in row.values()])
        console.print(sample_table)


def _print_catalog(console: Console, cat: Any) -> None:
    """Print full catalog overview."""
    from anysite.db.discovery import DatabaseCatalog

    assert isinstance(cat, DatabaseCatalog)

    console.print(f"[bold]Catalog: {cat.connection_name}[/bold] ({cat.database_type})")
    console.print(f"  Discovered: {cat.discovered_at}")
    if cat.read_only is True:
        console.print("  Access: [yellow]read-only[/yellow]")
    elif cat.read_only is False:
        console.print("  Access: [green]read-write[/green]")
    if cat.description:
        console.print(f"  {cat.description}")
    if cat.llm_enriched:
        console.print("  LLM enriched: yes")
    console.print()

    # Tables summary
    tbl = Table(title=f"Tables ({len(cat.tables)})")
    tbl.add_column("Table", style="bold")
    tbl.add_column("Columns", justify="right")
    tbl.add_column("Rows", justify="right")
    tbl.add_column("FKs", justify="right")
    tbl.add_column("Indexes", justify="right")
    tbl.add_column("Description")

    for t in cat.tables:
        tbl.add_row(
            t.name,
            str(len(t.columns)),
            f"{t.row_count:,}" if t.row_count is not None else "",
            str(len(t.foreign_keys)) if t.foreign_keys else "",
            str(len(t.indexes)) if t.indexes else "",
            t.description or "",
        )
    console.print(tbl)

    if cat.implicit_relationships:
        console.print()
        rel_table = Table(title="Implicit Relationships (LLM-detected)")
        rel_table.add_column("From")
        rel_table.add_column("To")
        rel_table.add_column("Confidence")
        rel_table.add_column("Reason")
        for r in cat.implicit_relationships:
            rel_table.add_row(
                f"{r.from_table}.{r.from_column}",
                f"{r.to_table}.{r.to_column}",
                f"{r.confidence:.0%}",
                r.reason,
            )
        console.print(rel_table)
