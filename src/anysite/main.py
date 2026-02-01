"""Main CLI application."""

from typing import Annotated

import typer
from rich.console import Console

from anysite import __app_name__, __version__
from anysite.cli import config as config_cli

# Create main app
app = typer.Typer(
    name=__app_name__,
    help="Anysite CLI - Web data extraction for humans and AI agents",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Add subcommands
app.add_typer(config_cli.app, name="config", help="Manage configuration")

# Global state for CLI options
state: dict[str, str | bool | None] = {
    "api_key": None,
    "base_url": None,
    "debug": False,
}


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console = Console()
        console.print(f"{__app_name__} version: [bold]{__version__}[/bold]")
        raise typer.Exit()


@app.callback()
def main(
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            envvar="ANYSITE_API_KEY",
            help="API key (or set ANYSITE_API_KEY)",
        ),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            envvar="ANYSITE_BASE_URL",
            help="API base URL",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable debug output",
        ),
    ] = False,
    no_color: Annotated[
        bool,
        typer.Option(
            "--no-color",
            help="Disable colored output",
        ),
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = None,
) -> None:
    """Anysite CLI - Web data extraction for humans and AI agents.

    Get data from LinkedIn, Instagram, Twitter, and more.

    \b
    Examples:
      anysite linkedin user satyanadella
      anysite linkedin users search --keywords "CTO" --count 10
      anysite instagram user cristiano
      anysite web parse https://example.com

    \b
    Documentation: https://docs.anysite.io/cli
    """
    # Store global options
    state["api_key"] = api_key
    state["base_url"] = base_url
    state["debug"] = debug

    if no_color:
        import os

        os.environ["NO_COLOR"] = "1"


@app.command("describe")
def describe(
    command: Annotated[
        str | None,
        typer.Argument(
            help="Endpoint to describe (e.g., 'linkedin.user', '/api/linkedin/user')"
        ),
    ] = None,
    search: Annotated[
        str | None,
        typer.Option("--search", "-s", help="Search endpoints by keyword"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON (for agents)"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Minimal output (paths only)"),
    ] = False,
) -> None:
    """Describe API endpoints — input params, output fields, search.

    Reads from a local cache (run `anysite schema update` first).
    Shows all endpoints from the API, not just those with CLI commands.

    \b
    Examples:
      anysite describe                          # list all endpoints
      anysite describe linkedin.user            # input + output for endpoint
      anysite describe /api/linkedin/user       # full path also works
      anysite describe --search "company"       # search by keyword
      anysite describe --json -q                # JSON list for agents
    """
    import json as json_mod

    from anysite.api.schemas import get_schema, list_endpoints, search_endpoints

    # Search mode
    if search is not None:
        results = search_endpoints(search)
        if not results:
            typer.echo(f"No endpoints matching '{search}'", err=True)
            typer.echo("Run 'anysite schema update' if cache is empty.", err=True)
            raise typer.Exit(1)
        if json_output:
            typer.echo(json_mod.dumps(results))
        else:
            console = Console()
            console.print(f"[bold]Endpoints matching '{search}':[/bold]\n")
            for r in results:
                console.print(f"  {r['path']:<45} [dim]{r['description']}[/dim]")
        return

    # List all endpoints
    if command is None:
        endpoints = list_endpoints()
        if not endpoints:
            typer.echo("No cached schema. Run: anysite schema update", err=True)
            raise typer.Exit(1)
        if json_output:
            if quiet:
                typer.echo(json_mod.dumps([e["path"] for e in endpoints]))
            else:
                typer.echo(json_mod.dumps(endpoints))
        else:
            console = Console()
            console.print(f"[bold]Available endpoints ({len(endpoints)}):[/bold]\n")
            for ep in endpoints:
                if quiet:
                    console.print(f"  {ep['path']}")
                else:
                    console.print(f"  {ep['path']:<45} [dim]{ep['description']}[/dim]")
            console.print(
                "\n[dim]Use 'anysite describe <endpoint>' for details[/dim]"
            )
        return

    # Describe a specific endpoint
    schema = get_schema(command)
    if schema is None:
        typer.echo(f"Unknown endpoint: {command}", err=True)
        typer.echo("Run 'anysite schema update' to refresh the cache.", err=True)
        raise typer.Exit(1)

    if json_output:
        typer.echo(json_mod.dumps({"input": schema["input"], "output": schema["output"]}))
    else:
        console = Console()
        desc = schema.get("description", "")
        console.print(f"[bold]{command}[/bold]")
        if desc:
            console.print(f"  {desc}\n")

        input_params = schema.get("input", {})
        if input_params:
            console.print("[bold]Input parameters:[/bold]")
            for name, info in input_params.items():
                req = "[red]*[/red]" if info.get("required") else " "
                desc = info.get("description", "")
                desc_part = f"  [dim italic]{desc}[/dim italic]" if desc else ""
                console.print(f"  {req} {name:<30} [dim]{info['type']:<10}[/dim]{desc_part}")
            console.print()

        output_fields = schema.get("output", {})
        if output_fields:
            console.print(f"[bold]Output fields ({len(output_fields)}):[/bold]")
            for name, ftype in output_fields.items():
                console.print(f"    {name:<30} [dim]{ftype}[/dim]")


# Schema management subcommand
schema_app = typer.Typer(help="Manage API schema cache")
app.add_typer(schema_app, name="schema")


@schema_app.command("update")
def schema_update() -> None:
    """Fetch OpenAPI spec and update local schema cache.

    Downloads the API specification, resolves all references,
    and saves a compact cache to ~/.anysite/schema.json.
    """
    from anysite.api.schemas import OPENAPI_URL, fetch_and_parse_openapi, save_cache

    console = Console()
    console.print(f"Fetching OpenAPI spec from {OPENAPI_URL}...")

    try:
        data = fetch_and_parse_openapi()
    except Exception as e:
        console.print(f"[red]Error fetching spec:[/red] {e}")
        raise typer.Exit(1) from e

    cache_path = save_cache(data)
    count = len(data.get("endpoints", {}))
    console.print(f"[green]✓[/green] Cached {count} endpoints to {cache_path}")


@app.command(
    "api",
    context_settings={"allow_extra_args": True, "allow_interspersed_args": True},
)
def api_call(
    ctx: typer.Context,
    endpoint: Annotated[
        str,
        typer.Argument(help="API endpoint path (e.g., /api/linkedin/user)"),
    ],
    # Output options
    format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format (json/jsonl/csv/table)"),
    ] = "json",
    fields: Annotated[
        str | None,
        typer.Option("--fields", help="Comma-separated fields to include"),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Save output to file"),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress non-data output"),
    ] = False,
    exclude: Annotated[
        str | None,
        typer.Option("--exclude", help="Comma-separated fields to exclude"),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option("--compact", help="Compact output (no indentation)"),
    ] = False,
    # Batch options
    from_file: Annotated[
        str | None,
        typer.Option("--from-file", help="Read inputs from file"),
    ] = None,
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Read inputs from stdin"),
    ] = False,
    parallel: Annotated[
        int,
        typer.Option("--parallel", "-j", help="Number of parallel requests"),
    ] = 1,
    delay: Annotated[
        float,
        typer.Option("--delay", help="Delay between requests in seconds"),
    ] = 0.0,
    on_error: Annotated[
        str,
        typer.Option("--on-error", help="Error handling: stop, skip, retry"),
    ] = "stop",
    rate_limit: Annotated[
        str | None,
        typer.Option("--rate-limit", help="Rate limit (e.g., '10/s', '100/m')"),
    ] = None,
    input_key: Annotated[
        str | None,
        typer.Option("--input-key", help="Parameter name to iterate over in batch mode"),
    ] = None,
    # Feedback
    progress: Annotated[
        bool | None,
        typer.Option("--progress/--no-progress", help="Show progress bar"),
    ] = None,
    stats: Annotated[
        bool,
        typer.Option("--stats", help="Show statistics after completion"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Verbose output"),
    ] = False,
    append: Annotated[
        bool,
        typer.Option("--append", help="Append to existing output file"),
    ] = False,
) -> None:
    """Call any API endpoint directly with key=value parameters.

    Pass parameters as key=value pairs after the endpoint path.
    Types are auto-converted using the schema cache.

    \b
    Examples:
      anysite api /api/linkedin/user user=satyanadella
      anysite api /api/linkedin/search/users title=CTO count=100 --format csv
      anysite api /api/reddit/user user=spez --format table
      anysite api /api/linkedin/user --from-file users.txt --input-key user --parallel 5
    """
    from pathlib import Path

    from anysite.api.schemas import convert_value, get_schema
    from anysite.cli.executor import run_search_command, run_single_command
    from anysite.cli.options import ErrorHandling as EH
    from anysite.output.formatters import OutputFormat

    # Validate endpoint format
    if not endpoint.startswith("/"):
        typer.echo(
            f"Error: endpoint must start with '/' (e.g., /api/linkedin/user), got: {endpoint}",
            err=True,
        )
        raise typer.Exit(1)

    # Parse key=value args from ctx.args
    raw_params: dict[str, str] = {}
    for arg in ctx.args:
        if "=" not in arg:
            typer.echo(f"Error: invalid parameter '{arg}', expected key=value format", err=True)
            raise typer.Exit(1)
        key, _, value = arg.partition("=")
        raw_params[key] = value

    # Convert types using schema if available
    schema = get_schema(endpoint)
    payload: dict[str, str | int | bool | float] = {}
    if schema and schema.get("input"):
        input_schema = schema["input"]
        for key, value in raw_params.items():
            if key in input_schema:
                type_hint = input_schema[key].get("type", "string")
                try:
                    payload[key] = convert_value(value, type_hint)
                except (ValueError, TypeError):
                    payload[key] = value
            else:
                payload[key] = value
    else:
        # No schema — pass as strings, try auto-converting obvious types
        for key, value in raw_params.items():
            if value.isdigit():
                payload[key] = int(value)
            elif value.lower() in ("true", "false"):
                payload[key] = value.lower() == "true"
            else:
                payload[key] = value

    # Resolve format enum
    try:
        fmt = OutputFormat(format.lower())
    except ValueError:
        typer.echo(f"Error: invalid format '{format}', use json/jsonl/csv/table", err=True)
        raise typer.Exit(1) from None

    # Resolve error handling enum
    try:
        err_handling = EH(on_error.lower())
    except ValueError:
        typer.echo(f"Error: invalid on-error '{on_error}', use stop/skip/retry", err=True)
        raise typer.Exit(1) from None

    output_path = Path(output) if output else None
    from_file_path = Path(from_file) if from_file else None

    is_batch = from_file_path is not None or stdin

    if is_batch:
        if not input_key and not from_file_path:
            typer.echo(
                "Error: --input-key is required for batch mode with plain text input",
                err=True,
            )
            raise typer.Exit(1)

        run_single_command(
            endpoint,
            payload,
            format=fmt,
            fields=fields,
            output=output_path,
            quiet=quiet,
            exclude=exclude,
            compact=compact,
            from_file=from_file_path,
            stdin=stdin,
            parallel=parallel,
            delay=delay,
            on_error=err_handling,
            rate_limit=rate_limit,
            progress=progress,
            stats=stats,
            verbose=verbose,
            append=append,
            input_key=input_key or "user",
            extra_payload=dict(payload),
        )
    else:
        run_search_command(
            endpoint,
            dict(payload),
            format=fmt,
            fields=fields,
            output=output_path,
            quiet=quiet,
            exclude=exclude,
            compact=compact,
            stream=False,
            progress=progress,
            stats=stats,
            verbose=verbose,
            append=append,
        )


def get_api_key() -> str | None:
    """Get API key from global state or settings."""
    if state["api_key"]:
        return str(state["api_key"])

    from anysite.config import get_settings

    return get_settings().api_key


def get_base_url() -> str:
    """Get base URL from global state or settings."""
    if state["base_url"]:
        return str(state["base_url"])

    from anysite.config import get_settings

    return get_settings().base_url


def is_debug() -> bool:
    """Check if debug mode is enabled."""
    return bool(state["debug"])


# Register dataset subcommand (requires optional [data] dependencies)
try:
    from anysite.dataset.cli import app as dataset_app

    app.add_typer(dataset_app, name="dataset", help="Collect, store, and analyze datasets")
except ImportError:
    pass

# Register db subcommand (SQLite always available, PostgreSQL needs optional deps)
try:
    from anysite.db.cli import app as db_app

    app.add_typer(db_app, name="db", help="Store API data in SQL databases")
except ImportError:
    pass



if __name__ == "__main__":
    app()
