"""CLI commands for the dataset subsystem."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from anysite.dataset import check_data_deps
from anysite.dataset.errors import DatasetError

app = typer.Typer(help="Collect, store, and analyze multi-source datasets")


def _load_config(path: Path) -> Any:
    """Load and validate dataset config from YAML."""
    from anysite.dataset.models import DatasetConfig

    if not path.exists():
        typer.echo(f"Error: dataset config not found: {path}", err=True)
        raise typer.Exit(1)
    try:
        return DatasetConfig.from_yaml(path)
    except Exception as e:
        typer.echo(f"Error parsing dataset config: {e}", err=True)
        raise typer.Exit(1) from None


@app.callback()
def dataset_callback() -> None:
    """Check data dependencies before running any dataset command."""
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
) -> None:
    """Create a new dataset directory with a template YAML config."""
    import yaml

    base = path or Path.cwd()
    dataset_dir = base / name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    config_path = dataset_dir / "dataset.yaml"
    if config_path.exists():
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

    console = Console()
    console.print(f"[green]Created[/green] {config_path}")
    console.print(f"Edit the config and run: anysite dataset collect {config_path}")


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
    load_db: Annotated[
        str | None,
        typer.Option("--load-db", help="After collection, load into database (connection name)"),
    ] = None,
) -> None:
    """Collect data from all sources defined in the dataset config."""
    config = _load_config(config_path)

    try:
        from anysite.dataset.collector import run_collect

        results = run_collect(
            config,
            config_dir=config_path.parent.resolve(),
            source_filter=source,
            incremental=incremental,
            dry_run=dry_run,
            quiet=quiet,
        )

        if not dry_run and not quiet:
            console = Console()
            total = sum(results.values())
            console.print(
                f"\n[bold green]Done.[/bold green] "
                f"Collected {total} records across {len(results)} sources."
            )

        # Auto-load into database if requested
        if load_db and not dry_run:
            _run_load_db(config, load_db, source_filter=source, quiet=quiet)

    except DatasetError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command("status")
def status(
    config_path: Annotated[
        Path,
        typer.Argument(help="Path to dataset.yaml"),
    ],
) -> None:
    """Show collection status for all sources in the dataset."""
    config = _load_config(config_path)

    from anysite.dataset.storage import MetadataStore, get_source_dir

    base_path = config.storage_path()
    metadata = MetadataStore(base_path)

    console = Console()
    table = Table(title=f"Dataset: {config.name}")
    table.add_column("Source", style="bold")
    table.add_column("Endpoint")
    table.add_column("Last Collected")
    table.add_column("Records", justify="right")
    table.add_column("Files", justify="right")

    for src in config.sources:
        info = metadata.get_source_info(src.id)
        source_dir = get_source_dir(base_path, src.id)

        files = list(source_dir.glob("*.parquet")) if source_dir.exists() else []

        table.add_row(
            src.id,
            src.endpoint,
            info.get("last_collected", "-") if info else "-",
            str(info.get("record_count", 0)) if info else "0",
            str(len(files)),
        )

    console.print(table)


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
        typer.Option("--fields", help="Comma-separated fields to include (supports dot-notation, e.g. 'name, urn.value AS urn_id')"),
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
) -> None:
    """Load collected Parquet data into a relational database with FK linking."""
    config = _load_config(config_path)

    from anysite.db.manager import ConnectionManager

    manager = ConnectionManager()
    try:
        adapter = manager.get_adapter_by_name(connection)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    from anysite.dataset.db_loader import DatasetDbLoader

    with adapter:
        loader = DatasetDbLoader(config, adapter)
        try:
            results = loader.load_all(
                source_filter=source,
                drop_existing=drop_existing,
                dry_run=dry_run,
            )
        except Exception as e:
            typer.echo(f"Load error: {e}", err=True)
            raise typer.Exit(1) from None

    if not quiet:
        console = Console()
        if dry_run:
            console.print("[bold]Dry run — no tables modified.[/bold]")

        table = Table(title="Load Results")
        table.add_column("Source", style="bold")
        table.add_column("Table")
        table.add_column("Rows", justify="right")

        from anysite.dataset.db_loader import _table_name_for

        for src in config.sources:
            if src.id in results:
                table.add_row(
                    src.id,
                    _table_name_for(src),
                    str(results[src.id]),
                )

        console.print(table)

        total = sum(results.values())
        console.print(
            f"\n[bold green]{'Would load' if dry_run else 'Loaded'}[/bold green] "
            f"{total} rows across {len(results)} tables."
        )


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
) -> None:
    """Show run history for a dataset."""
    from anysite.dataset.history import HistoryStore

    store = HistoryStore()
    runs = store.get_history(name, limit=limit)

    if not runs:
        typer.echo(f"No history found for dataset '{name}'")
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
) -> None:
    """Generate schedule entries for automated collection."""
    config = _load_config(config_path)

    if not config.schedule:
        typer.echo("Error: no 'schedule' block in dataset config", err=True)
        raise typer.Exit(1)

    from anysite.dataset.scheduler import ScheduleGenerator

    gen = ScheduleGenerator(
        dataset_name=config.name,
        cron_expr=config.schedule.cron,
        yaml_path=str(config_path),
    )

    console = Console()

    if crontab or (not crontab and not systemd):
        entry = gen.generate_crontab(incremental=incremental, load_db=load_db)
        console.print("[bold]Crontab entry:[/bold]")
        console.print(entry)

    if systemd:
        units = gen.generate_systemd(incremental=incremental, load_db=load_db)
        for filename, content in units.items():
            console.print(f"\n[bold]{filename}:[/bold]")
            console.print(content)


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
) -> None:
    """Reset incremental collection state (re-collect everything)."""
    config = _load_config(config_path)

    from anysite.dataset.storage import MetadataStore

    base_path = config.storage_path()
    metadata = MetadataStore(base_path)

    console = Console()

    if source:
        metadata.reset_collected_inputs(source)
        console.print(f"[green]Reset[/green] incremental state for source: {source}")
    else:
        for src in config.sources:
            metadata.reset_collected_inputs(src.id)
        console.print(f"[green]Reset[/green] incremental state for all {len(config.sources)} sources")


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

        for src in config.sources:
            if src.id in results:
                table.add_row(src.id, _table_name_for(src), str(results[src.id]))

        console.print(table)
        total = sum(results.values())
        console.print(f"[bold green]Loaded[/bold green] {total} rows into {connection}.")


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
