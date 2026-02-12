"""CLI commands for the dataset subsystem."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from anysite.dataset import check_data_deps
from anysite.dataset.errors import DatasetError

app = typer.Typer(
    help="Collect, store, and analyze multi-source datasets",
    invoke_without_command=True,
    epilog="Run 'anysite dataset <command> --help' for details on each command.",
)


def _load_config(path: Path, *, json_output: bool = False) -> Any:
    """Load and validate dataset config from YAML."""
    from anysite.dataset.models import DatasetConfig

    if not path.exists():
        if json_output:
            from anysite.cli.json_output import json_error

            json_error(
                "CONFIG_NOT_FOUND",
                f"Dataset config not found: {path}",
                suggestions=["Create with: anysite dataset init <name>"],
            )
        typer.echo(f"Error: dataset config not found: {path}", err=True)
        raise typer.Exit(1)
    try:
        return DatasetConfig.from_yaml(path)
    except Exception as e:
        if json_output:
            from anysite.cli.json_output import json_error

            json_error(
                "CONFIG_PARSE_ERROR",
                f"Error parsing dataset config: {e}",
                suggestions=["Check YAML syntax in the config file"],
            )
        typer.echo(f"Error parsing dataset config: {e}", err=True)
        raise typer.Exit(1) from None


@app.callback(invoke_without_command=True)
def dataset_callback(ctx: typer.Context) -> None:
    """Check data dependencies and handle discovery."""
    if ctx.invoked_subcommand is None:
        from anysite.cli.discovery import build_command_detail, is_pipe_mode

        if is_pipe_mode():
            import json

            typer.echo(json.dumps(build_command_detail("dataset", ctx), indent=2))
            raise typer.Exit(0)
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
    # Only check deps when an actual subcommand will run
    check_data_deps()


@app.command("init")
def init(
    name: Annotated[
        str,
        typer.Argument(help="Dataset name (used as directory name)"),
    ],
    path: Annotated[
        Path | None,
        typer.Option("--path", "-p", help="Parent directory (default: current dir)"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Create a new dataset directory with a template YAML config."""
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    import yaml

    base = path or Path.cwd()
    dataset_dir = base / name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    config_path = dataset_dir / "dataset.yaml"
    if config_path.exists():
        if json_output:
            from anysite.cli.json_output import json_error

            json_error(
                "CONFIG_EXISTS",
                f"{config_path} already exists",
                suggestions=[f"Edit existing config: $EDITOR {config_path}"],
            )
        typer.echo(f"Error: {config_path} already exists", err=True)
        raise typer.Exit(1)

    template: dict[str, Any] = {
        "name": name,
        "description": f"Dataset: {name}",
        "sources": [
            {
                "id": "example_profiles",
                "endpoint": "/api/linkedin/search/users",
                "params": {
                    "keywords": "software engineer",
                    "count": 10,
                },
            },
        ],
        "storage": {
            "format": "parquet",
            "path": f"./data/{name}/",
            "partition_by": ["source_id", "collected_date"],
        },
    }

    with open(config_path, "w") as f:
        yaml.dump(template, f, default_flow_style=False, sort_keys=False)

    hints = [
        ("Edit the config", f"$EDITOR {config_path}"),
        ("Run collection", f"anysite dataset collect {config_path}"),
        ("Preview plan", f"anysite dataset collect {config_path} --dry-run"),
        ("Discover endpoints", "anysite describe --search '<keyword>'"),
        ("Dataset config guide", "anysite dataset guide"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"path": str(config_path), "name": name},
            hints=hints,
            command="anysite dataset init",
        )
        return

    console = Console()
    console.print(f"[green]Created[/green] {config_path}")
    console.print(f"Edit the config and run: anysite dataset collect {config_path}")

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("collect")
def collect(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    source: Annotated[
        str | None,
        typer.Option("--source", "-s", help="Collect only this source (and dependencies)"),
    ] = None,
    incremental: Annotated[
        bool,
        typer.Option("--incremental", "-i", help="Skip sources already collected today"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show collection plan without executing"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress progress output"),
    ] = False,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Skip LLM enrichment steps"),
    ] = False,
    load_db: Annotated[
        str | None,
        typer.Option("--load-db", help="After collection, load into database (connection name)"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Collect data from all sources defined in the dataset config."""
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config = _load_config(config_path, json_output=json_output)

    try:
        from anysite.dataset.collector import run_collect

        results = run_collect(
            config,
            config_dir=config_path.parent.resolve(),
            source_filter=source,
            incremental=incremental,
            dry_run=dry_run,
            quiet=quiet,
            no_llm=no_llm,
        )

        total = sum(results.values())
        first_source = next(iter(results), None)

        if json_output and not dry_run:
            from anysite.cli.json_output import json_response

            hints = [
                ("Check status", f"anysite dataset status {config_path}"),
                (
                    "Query data",
                    f"anysite dataset query {config_path} --source {first_source} --format table"
                    if first_source
                    else f"anysite dataset query {config_path} --format table",
                ),
                (
                    "Query with SQL",
                    f"anysite dataset query {config_path} --sql 'SELECT * FROM {first_source} LIMIT 10'"
                    if first_source
                    else f"anysite dataset query {config_path} --interactive",
                ),
                ("Load into database", f"anysite dataset load-db {config_path} -c <connection>"),
                ("View run history", f"anysite dataset history {config.name}"),
            ]
            json_response(
                {"sources": results, "total_records": total, "source_count": len(results)},
                hints=hints,
                command="anysite dataset collect",
            )
        elif not dry_run and not quiet:
            console = Console()
            console.print(
                f"\n[bold green]Done.[/bold green] "
                f"Collected {total} records across {len(results)} sources."
            )

            from anysite.cli.json_output import print_hints

            hints = [
                ("Check status", f"anysite dataset status {config_path}"),
                (
                    "Query data",
                    f"anysite dataset query {config_path} --source {first_source} --format table"
                    if first_source
                    else f"anysite dataset query {config_path} --format table",
                ),
                (
                    "Query with SQL",
                    f"anysite dataset query {config_path} --sql 'SELECT * FROM {first_source} LIMIT 10'"
                    if first_source
                    else f"anysite dataset query {config_path} --interactive",
                ),
                ("Load into database", f"anysite dataset load-db {config_path} -c <connection>"),
                ("View run history", f"anysite dataset history {config.name}"),
            ]
            print_hints(hints, quiet=quiet)

        # Auto-load into database if requested
        if load_db and not dry_run:
            _run_load_db(config, load_db, source_filter=source, quiet=quiet)

    except DatasetError as e:
        if json_output:
            from anysite.cli.json_output import json_error

            json_error("COLLECT_ERROR", str(e))
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command("status")
def status(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Show collection status for all sources in the dataset."""
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config = _load_config(config_path, json_output=json_output)

    from anysite.dataset.storage import MetadataStore, get_source_dir

    base_path = config.storage_path()
    metadata = MetadataStore(base_path)

    source_statuses = []
    first_source_id = None

    for src in config.sources:
        if first_source_id is None:
            first_source_id = src.id
        info = metadata.get_source_info(src.id)
        source_dir = get_source_dir(base_path, src.id)
        files = list(source_dir.glob("*.parquet")) if source_dir.exists() else []

        source_statuses.append(
            {
                "id": src.id,
                "endpoint": src.endpoint,
                "last_collected": info.get("last_collected", "-") if info else "-",
                "record_count": info.get("record_count", 0) if info else 0,
                "files": len(files),
            }
        )

    hints = [
        ("Collect new data", f"anysite dataset collect {config_path}"),
        ("Collect incrementally", f"anysite dataset collect {config_path} --incremental"),
        (
            "Query a source",
            f"anysite dataset query {config_path} --source {first_source_id}"
            if first_source_id
            else f"anysite dataset query {config_path}",
        ),
        (
            "Compare snapshots",
            f"anysite dataset diff {config_path} --source {first_source_id} --key <field>"
            if first_source_id
            else f"anysite dataset diff {config_path} --source <source_id> --key <field>",
        ),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"name": config.name, "sources": source_statuses},
            hints=hints,
            command="anysite dataset status",
        )
        return

    console = Console()
    table = Table(title=f"Dataset: {config.name}")
    table.add_column("Source", style="bold")
    table.add_column("Endpoint")
    table.add_column("Last Collected")
    table.add_column("Records", justify="right")
    table.add_column("Files", justify="right")

    for s in source_statuses:
        table.add_row(
            s["id"],
            s["endpoint"],
            str(s["last_collected"]),
            str(s["record_count"]),
            str(s["files"]),
        )

    console.print(table)

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("query")
def query(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    sql: Annotated[
        str | None,
        typer.Option("--sql", help="SQL query to execute"),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read SQL from file"),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Start interactive SQL shell"),
    ] = False,
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
        typer.Option(
            "--fields",
            help="Comma-separated fields to include (supports dot-notation, e.g. 'name, urn.value AS urn_id')",
        ),
    ] = None,
    source: Annotated[
        str | None,
        typer.Option("--source", "-s", help="Source to query (auto-generates SELECT query)"),
    ] = None,
) -> None:
    """Run SQL queries against collected dataset data using DuckDB."""
    config = _load_config(config_path)

    from anysite.dataset.analyzer import DatasetAnalyzer, expand_dot_fields

    with DatasetAnalyzer(config) as analyzer:
        if interactive:
            analyzer.interactive_shell()
            return

        # Auto-generate SQL from --source + --fields
        if source and not sql and not file:
            view_name = source.replace("-", "_").replace(".", "_")
            if fields:
                select_expr = expand_dot_fields(fields)
                fields = None  # Already in SQL, don't post-filter
            else:
                select_expr = "*"
            sql = f"SELECT {select_expr} FROM {view_name}"

        if file:
            if not file.exists():
                typer.echo(f"Error: SQL file not found: {file}", err=True)
                raise typer.Exit(1)
            sql = file.read_text().strip()

        if not sql:
            typer.echo("Error: provide --sql, --file, --source, or --interactive", err=True)
            raise typer.Exit(1)

        try:
            results = analyzer.query(sql)
        except Exception as e:
            typer.echo(f"Query error: {e}", err=True)
            raise typer.Exit(1) from None

        _output_results(results, format, output, fields)


@app.command("stats")
def stats(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    source: Annotated[
        str | None,
        typer.Option("--source", "-s", help="Source to analyze"),
    ] = None,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format (json/jsonl/csv/table)"),
    ] = "table",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Save output to file"),
    ] = None,
) -> None:
    """Show column statistics for a source (min, max, nulls, distinct)."""
    config = _load_config(config_path)

    if not source:
        # Default to first source
        if config.sources:
            source = config.sources[0].id
        else:
            typer.echo("Error: no sources defined in dataset config", err=True)
            raise typer.Exit(1)

    from anysite.dataset.analyzer import DatasetAnalyzer

    with DatasetAnalyzer(config) as analyzer:
        try:
            results = analyzer.stats(source)
        except Exception as e:
            typer.echo(f"Stats error: {e}", err=True)
            raise typer.Exit(1) from None

        _output_results(results, format, output)


@app.command("profile")
def profile(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    format: Annotated[
        str,
        typer.Option("--format", help="Output format (json/jsonl/csv/table)"),
    ] = "table",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Save output to file"),
    ] = None,
) -> None:
    """Profile dataset quality: completeness, record counts, missing data."""
    config = _load_config(config_path)

    from anysite.dataset.analyzer import DatasetAnalyzer

    with DatasetAnalyzer(config) as analyzer:
        try:
            results = analyzer.profile()
        except Exception as e:
            typer.echo(f"Profile error: {e}", err=True)
            raise typer.Exit(1) from None

        _output_results(results, format, output)


@app.command("load-db")
def load_db(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    connection: Annotated[
        str,
        typer.Option("--connection", "-c", help="Database connection name"),
    ],
    source: Annotated[
        str | None,
        typer.Option("--source", "-s", help="Load only this source (and dependencies)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show plan without executing"),
    ] = False,
    drop_existing: Annotated[
        bool,
        typer.Option("--drop-existing", help="Drop tables before creating"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress progress output"),
    ] = False,
    snapshot: Annotated[
        str | None,
        typer.Option("--snapshot", help="Load a specific snapshot date (YYYY-MM-DD)"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Load collected Parquet data into a relational database with FK linking."""
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config = _load_config(config_path, json_output=json_output)

    from anysite.db.manager import ConnectionManager

    manager = ConnectionManager()
    try:
        adapter = manager.get_adapter_by_name(connection)
    except ValueError as e:
        if json_output:
            from anysite.cli.json_output import json_error

            json_error(
                "CONNECTION_NOT_FOUND",
                str(e),
                suggestions=[f"Add connection: anysite db add {connection}"],
            )
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    from anysite.dataset.db_loader import DatasetDbLoader, _table_name_for

    with adapter:
        loader = DatasetDbLoader(config, adapter)
        try:
            results = loader.load_all(
                source_filter=source,
                drop_existing=drop_existing,
                dry_run=dry_run,
                snapshot=snapshot,
            )
        except Exception as e:
            if json_output:
                from anysite.cli.json_output import json_error

                json_error("LOAD_ERROR", str(e))
            typer.echo(f"Load error: {e}", err=True)
            raise typer.Exit(1) from None

    # Build result data for both json and rich output
    result_data = {}
    first_table = None
    first_source_id = None
    for src in config.sources:
        if src.id in results:
            lr = results[src.id]
            tname = _table_name_for(src)
            if first_table is None:
                first_table = tname
                first_source_id = src.id
            result_data[src.id] = {
                "table": tname,
                "rows": lr.row_count,
                "ops": lr.ops,
            }

    hints = [
        (
            "Query loaded data",
            f"anysite db query {connection} --sql 'SELECT * FROM {first_table} LIMIT 10' --format table"
            if first_table
            else f"anysite db query {connection} --sql 'SELECT 1' --format table",
        ),
        ("View DB schema", f"anysite db schema {connection}"),
        (
            "Compare snapshots",
            f"anysite dataset diff {config_path} --source {first_source_id} --key <field>"
            if first_source_id
            else f"anysite dataset diff {config_path} --source <source_id> --key <field>",
        ),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            result_data,
            hints=hints,
            command="anysite dataset load-db",
        )
        return

    if not quiet:
        console = Console()
        if dry_run:
            console.print("[bold]Dry run — no tables modified.[/bold]")

        table = Table(title="Load Results")
        table.add_column("Source", style="bold")
        table.add_column("Table")
        table.add_column("Rows", justify="right")
        table.add_column("Synced", justify="right")

        total_rows = 0
        total_ops = 0
        for src in config.sources:
            if src.id in results:
                lr = results[src.id]
                total_rows += lr.row_count
                total_ops += lr.ops
                synced = str(lr.ops) if lr.ops != lr.row_count else ""
                table.add_row(
                    src.id,
                    _table_name_for(src),
                    str(lr.row_count),
                    synced,
                )

        console.print(table)

        if total_ops != total_rows and not dry_run:
            console.print(
                f"\n[bold green]Loaded[/bold green] "
                f"{total_rows} rows across {len(results)} tables ({total_ops} operations)."
            )
        else:
            console.print(
                f"\n[bold green]{'Would load' if dry_run else 'Loaded'}[/bold green] "
                f"{total_rows} rows across {len(results)} tables."
            )

        from anysite.cli.json_output import print_hints

        print_hints(hints, quiet=quiet)


@app.command("diff")
def diff_cmd(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    source: Annotated[
        str,
        typer.Option("--source", "-s", help="Source to compare"),
    ],
    key: Annotated[
        str,
        typer.Option("--key", "-k", help="Field to match records by (e.g., _input_value, urn)"),
    ],
    from_date: Annotated[
        str | None,
        typer.Option("--from", help="Older snapshot date (YYYY-MM-DD)"),
    ] = None,
    to_date: Annotated[
        str | None,
        typer.Option("--to", help="Newer snapshot date (YYYY-MM-DD)"),
    ] = None,
    fields: Annotated[
        str | None,
        typer.Option("--fields", "-f", help="Only compare these fields (comma-separated)"),
    ] = None,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format: table, json, jsonl, csv"),
    ] = "table",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write output to file"),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress summary, only output data"),
    ] = False,
) -> None:
    """Compare two snapshots of a source to show added, removed, and changed records."""
    from datetime import date as date_type

    from anysite.dataset.differ import (
        DatasetDiffer,
        format_diff_records,
        format_diff_table,
    )

    config = _load_config(config_path)

    # Validate source exists
    src = config.get_source(source)
    if src is None:
        typer.echo(f"Error: source '{source}' not found in dataset", err=True)
        raise typer.Exit(1)

    differ = DatasetDiffer(config.storage_path())

    # Parse dates
    parsed_from = None
    parsed_to = None
    try:
        if from_date:
            parsed_from = date_type.fromisoformat(from_date)
        if to_date:
            parsed_to = date_type.fromisoformat(to_date)
    except ValueError as e:
        typer.echo(f"Error: invalid date format: {e}", err=True)
        raise typer.Exit(1) from None

    # Parse fields
    field_list = None
    if fields:
        field_list = [f.strip() for f in fields.split(",") if f.strip()]

    try:
        result = differ.diff(
            source,
            key,
            from_date=parsed_from,
            to_date=parsed_to,
            fields=field_list,
        )
    except DatasetError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    # Print summary unless quiet
    if not quiet:
        console = Console()
        console.print(
            f"\n[bold]Diff: {source}[/bold] "
            f"({result.from_date.isoformat()} → {result.to_date.isoformat()})\n"
        )
        console.print(f"  [green]Added:[/green]     {len(result.added)}")
        console.print(f"  [red]Removed:[/red]   {len(result.removed)}")
        console.print(f"  [yellow]Changed:[/yellow]   {len(result.changed)}")
        console.print(f"  Unchanged: {result.unchanged_count}")
        console.print()

        from anysite.cli.json_output import print_hints

        hints = [
            ("View full history", f"anysite dataset history {config.name}"),
            ("Collect new snapshot", f"anysite dataset collect {config_path}"),
        ]
        print_hints(hints)

    if not result.has_changes:
        if not quiet:
            Console().print("[dim]No changes detected.[/dim]")
        return

    # Format and output
    rows = (
        format_diff_table(result, output_fields=field_list)
        if format == "table"
        else format_diff_records(result, output_fields=field_list)
    )

    _output_results(rows, format, output)


@app.command("history")
def history(
    name: Annotated[
        str,
        typer.Argument(help="Dataset name"),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Number of recent runs to show"),
    ] = 20,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Show run history for a dataset."""
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    from anysite.dataset.history import HistoryStore

    store = HistoryStore()
    runs = store.get_history(name, limit=limit)

    if not runs:
        if json_output:
            from anysite.cli.json_output import json_response

            json_response(
                [],
                hints=[("Collect new data", "anysite dataset collect <path>")],
                command="anysite dataset history",
            )
            return
        typer.echo(f"No history found for dataset '{name}'")
        return

    run_dicts = [
        {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at[:19] if run.started_at else None,
            "duration": f"{run.duration:.1f}s" if run.duration else None,
            "record_count": run.record_count,
            "source_count": run.source_count,
            "error": (run.error or "")[:60] or None,
        }
        for run in runs
    ]

    latest_id = runs[0].id if runs else None

    hints = [
        (
            "View run logs",
            f"anysite dataset logs {name} --run {latest_id}"
            if latest_id
            else f"anysite dataset logs {name}",
        ),
        ("Collect new data", "anysite dataset collect <path>"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            run_dicts,
            hints=hints,
            command="anysite dataset history",
        )
        return

    console = Console()
    table = Table(title=f"Run History: {name}")
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("Started")
    table.add_column("Duration", justify="right")
    table.add_column("Records", justify="right")
    table.add_column("Sources", justify="right")
    table.add_column("Error")

    for run in runs:
        status_style = {
            "success": "green",
            "failed": "red",
            "running": "yellow",
            "partial": "yellow",
        }.get(run.status, "")

        duration_str = f"{run.duration:.1f}s" if run.duration else "-"
        started = run.started_at[:19] if run.started_at else "-"

        table.add_row(
            str(run.id),
            f"[{status_style}]{run.status}[/{status_style}]" if status_style else run.status,
            started,
            duration_str,
            str(run.record_count),
            str(run.source_count),
            (run.error or "")[:60],
        )

    console.print(table)

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("logs")
def logs(
    name: Annotated[
        str,
        typer.Argument(help="Dataset name"),
    ],
    run_id: Annotated[
        int | None,
        typer.Option("--run", help="Specific run ID (default: latest)"),
    ] = None,
) -> None:
    """Show logs for a dataset collection run."""
    from anysite.dataset.history import HistoryStore, LogManager

    log_mgr = LogManager()

    if run_id is None:
        store = HistoryStore()
        runs = store.get_history(name, limit=1)
        if not runs:
            typer.echo(f"No runs found for dataset '{name}'")
            raise typer.Exit(1)
        run_id = runs[0].id

    content = log_mgr.read_log(name, run_id)  # type: ignore[arg-type]
    if content:
        typer.echo(content)
    else:
        typer.echo(f"No log file found for run {run_id}")


@app.command("schedule")
def schedule(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    crontab: Annotated[
        bool,
        typer.Option("--crontab", help="Generate crontab entry"),
    ] = False,
    systemd: Annotated[
        bool,
        typer.Option("--systemd", help="Generate systemd timer units"),
    ] = False,
    incremental: Annotated[
        bool,
        typer.Option("--incremental", "-i", help="Include --incremental flag"),
    ] = False,
    load_db: Annotated[
        str | None,
        typer.Option("--load-db", help="Include --load-db <connection> flag"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Generate schedule entries for automated collection."""
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config = _load_config(config_path, json_output=json_output)

    if not config.schedule:
        if json_output:
            from anysite.cli.json_output import json_error

            json_error(
                "NO_SCHEDULE",
                "No 'schedule' block in dataset config",
                suggestions=[f"Add a schedule block to {config_path}"],
            )
        typer.echo("Error: no 'schedule' block in dataset config", err=True)
        raise typer.Exit(1)

    from anysite.dataset.scheduler import ScheduleGenerator

    gen = ScheduleGenerator(
        dataset_name=config.name,
        cron_expr=config.schedule.cron,
        yaml_path=str(config_path),
    )

    result_data: dict[str, Any] = {}

    if crontab or (not crontab and not systemd):
        entry = gen.generate_crontab(incremental=incremental, load_db=load_db)
        result_data["crontab"] = entry

    if systemd:
        units = gen.generate_systemd(incremental=incremental, load_db=load_db)
        result_data["systemd"] = units

    hints = [
        ("Run collection now", f"anysite dataset collect {config_path}"),
        ("Run incrementally", f"anysite dataset collect {config_path} --incremental"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            result_data,
            hints=hints,
            command="anysite dataset schedule",
        )
        return

    console = Console()

    if "crontab" in result_data:
        console.print("[bold]Crontab entry:[/bold]")
        console.print(result_data["crontab"])

    if "systemd" in result_data:
        for filename, content in result_data["systemd"].items():
            console.print(f"\n[bold]{filename}:[/bold]")
            console.print(content)

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("reset-cursor")
def reset_cursor(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
    source: Annotated[
        str | None,
        typer.Option("--source", "-s", help="Reset only this source"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Reset incremental collection state (re-collect everything)."""
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config = _load_config(config_path, json_output=json_output)

    from anysite.dataset.storage import MetadataStore

    base_path = config.storage_path()
    metadata = MetadataStore(base_path)

    if source:
        metadata.reset_collected_inputs(source)
    else:
        for src in config.sources:
            metadata.reset_collected_inputs(src.id)

    hints = [
        ("Run full collection", f"anysite dataset collect {config_path}"),
        ("Check status", f"anysite dataset status {config_path}"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"source": source or "all", "reset": True},
            hints=hints,
            command="anysite dataset reset-cursor",
        )
        return

    console = Console()
    if source:
        console.print(f"[green]Reset[/green] incremental state for source: {source}")
    else:
        console.print(
            f"[green]Reset[/green] incremental state for all {len(config.sources)} sources"
        )

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("guide")
def guide(
    section: Annotated[
        str | None,
        typer.Option("--section", "-s", help="Show specific section (e.g., sources, llm, db_load)"),
    ] = None,
    example: Annotated[
        str | None,
        typer.Option(
            "--example", "-e", help="Show a complete example config (e.g., basic, advanced)"
        ),
    ] = None,
    list_sections: Annotated[
        bool,
        typer.Option("--list", help="List available sections and examples"),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Show comprehensive dataset configuration reference with examples.

    The dataset guide covers all source types, config options, and real-world
    examples for building data collection pipelines.

    \b
    Examples:
      anysite dataset guide                        # full reference
      anysite dataset guide --section sources       # source types only
      anysite dataset guide --section llm           # LLM enrichment
      anysite dataset guide --example basic          # basic config example
      anysite dataset guide --example advanced       # multi-source pipeline
      anysite dataset guide --list                   # list all sections
      anysite dataset guide --json                   # structured JSON for agents
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    from anysite.dataset.guide import EXAMPLE_CONFIGS, GUIDE_SECTIONS, SECTION_ORDER

    # --list: show available sections and examples
    if list_sections:
        if json_output:
            from anysite.cli.json_output import json_response

            json_response(
                {
                    "sections": [
                        {"key": k, "title": GUIDE_SECTIONS[k].title} for k in SECTION_ORDER
                    ],
                    "examples": list(EXAMPLE_CONFIGS.keys()),
                },
                command="anysite dataset guide",
            )
            return

        console = Console()
        console.print("[bold]Available sections:[/bold]")
        for key in SECTION_ORDER:
            s = GUIDE_SECTIONS[key]
            console.print(f"  [cyan]{key:<16}[/cyan] {s.description}")
        console.print("\n[bold]Available examples:[/bold]")
        for key in EXAMPLE_CONFIGS:
            console.print(f"  [cyan]{key}[/cyan]")
        console.print("\n[dim]Usage: anysite dataset guide --section <name>[/dim]")
        return

    # --example: show a specific example config
    if example:
        if example not in EXAMPLE_CONFIGS:
            if json_output:
                from anysite.cli.json_output import json_error

                json_error(
                    "EXAMPLE_NOT_FOUND",
                    f"Example '{example}' not found",
                    suggestions=[f"Available: {', '.join(EXAMPLE_CONFIGS.keys())}"],
                )
            typer.echo(
                f"Error: example '{example}' not found. "
                f"Available: {', '.join(EXAMPLE_CONFIGS.keys())}",
                err=True,
            )
            raise typer.Exit(1)

        if json_output:
            from anysite.cli.json_output import json_response

            json_response(
                {"example": example, "config": EXAMPLE_CONFIGS[example]},
                command="anysite dataset guide",
            )
            return

        console = Console()
        console.print(f"[bold]Example: {example}[/bold]\n")
        console.print(EXAMPLE_CONFIGS[example])
        return

    # --section: show a specific section
    if section:
        if section not in GUIDE_SECTIONS:
            if json_output:
                from anysite.cli.json_output import json_error

                json_error(
                    "SECTION_NOT_FOUND",
                    f"Section '{section}' not found",
                    suggestions=[
                        f"Available: {', '.join(SECTION_ORDER)}",
                        "List all: anysite dataset guide --list",
                    ],
                )
            typer.echo(
                f"Error: section '{section}' not found. Available: {', '.join(SECTION_ORDER)}",
                err=True,
            )
            raise typer.Exit(1)

        s = GUIDE_SECTIONS[section]
        if json_output:
            from anysite.cli.json_output import json_response

            json_response(s.to_dict(), command="anysite dataset guide")
            return

        console = Console()
        console.print(f"[bold]{s.title}[/bold]")
        console.print(f"[dim]{s.description}[/dim]\n")
        console.print(s.content)
        if s.examples:
            console.print("\n[bold]Examples:[/bold]")
            for ex in s.examples:
                console.print(ex)
        return

    # Full guide (no flags)
    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {
                "sections": {k: GUIDE_SECTIONS[k].to_dict() for k in SECTION_ORDER},
                "examples": EXAMPLE_CONFIGS,
                "available_sections": SECTION_ORDER,
                "available_examples": list(EXAMPLE_CONFIGS.keys()),
            },
            command="anysite dataset guide",
        )
        return

    console = Console()
    console.print("[bold underline]Dataset Configuration Guide[/bold underline]\n")

    for key in SECTION_ORDER:
        s = GUIDE_SECTIONS[key]
        console.print(f"\n[bold cyan]{'=' * 60}[/bold cyan]")
        console.print(f"[bold]{s.title}[/bold]")
        console.print(f"[dim]{s.description}[/dim]\n")
        console.print(s.content)
        if s.examples:
            console.print("\n[bold]Examples:[/bold]")
            for ex in s.examples:
                console.print(ex)

    console.print(f"\n[bold cyan]{'=' * 60}[/bold cyan]")
    console.print("[bold]Complete Example Configs[/bold]\n")
    for name, config in EXAMPLE_CONFIGS.items():
        console.print(f"[bold]{name}:[/bold]")
        console.print(config)
        console.print()

    from anysite.cli.json_output import print_hints

    print_hints(
        [
            ("Create a new dataset", "anysite dataset init <name>"),
            ("View specific section", "anysite dataset guide --section <name>"),
            ("View example config", "anysite dataset guide --example basic"),
        ]
    )


def _run_load_db(
    config: Any,
    connection: str,
    *,
    source_filter: str | None = None,
    quiet: bool = False,
) -> None:
    """Load collected Parquet data into a database after collection."""
    from anysite.db.manager import ConnectionManager

    manager = ConnectionManager()
    try:
        adapter = manager.get_adapter_by_name(connection)
    except ValueError as e:
        typer.echo(f"Error loading to DB: {e}", err=True)
        return

    from anysite.dataset.db_loader import DatasetDbLoader, _table_name_for

    with adapter:
        loader = DatasetDbLoader(config, adapter)
        try:
            results = loader.load_all(source_filter=source_filter)
        except Exception as e:
            typer.echo(f"DB load error: {e}", err=True)
            return

    if not quiet:
        console = Console()
        table = Table(title="DB Load Results")
        table.add_column("Source", style="bold")
        table.add_column("Table")
        table.add_column("Rows", justify="right")
        table.add_column("Synced", justify="right")

        total_rows = 0
        total_ops = 0
        first_table = None
        for src in config.sources:
            if src.id in results:
                lr = results[src.id]
                total_rows += lr.row_count
                total_ops += lr.ops
                tname = _table_name_for(src)
                if first_table is None:
                    first_table = tname
                synced = str(lr.ops) if lr.ops != lr.row_count else ""
                table.add_row(src.id, tname, str(lr.row_count), synced)

        console.print(table)
        if total_ops != total_rows:
            console.print(
                f"[bold green]Loaded[/bold green] {total_rows} rows into {connection} ({total_ops} operations)."
            )
        else:
            console.print(f"[bold green]Loaded[/bold green] {total_rows} rows into {connection}.")

        from anysite.cli.json_output import print_hints

        hints = [
            (
                "Query loaded data",
                f"anysite db query {connection} --sql 'SELECT * FROM {first_table} LIMIT 10' --format table"
                if first_table
                else f"anysite db query {connection} --sql 'SELECT 1' --format table",
            ),
            ("View DB schema", f"anysite db schema {connection}"),
        ]
        print_hints(hints, quiet=quiet)


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
