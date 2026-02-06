"""Configuration management commands."""

from typing import Annotated

import typer
from rich.table import Table

from anysite.config import get_config_dir, get_config_path
from anysite.config.settings import get_config_value, list_config, save_config
from anysite.output.console import console, print_error, print_success

app = typer.Typer(
    help="Manage Anysite CLI configuration",
    no_args_is_help=True,
    epilog="Run 'anysite config <command> --help' for details on each command.",
)


@app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Configuration key (e.g., api_key, defaults.format)")],
    value: Annotated[str, typer.Argument(help="Value to set")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Set a configuration value.

    \b
    Examples:
      anysite config set api_key sk-xxxxx
      anysite config set defaults.format table
      anysite config set defaults.count 20
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    # Convert value types
    typed_value: str | int | bool = value
    if value.lower() in ("true", "false"):
        typed_value = value.lower() == "true"
    elif value.isdigit():
        typed_value = int(value)

    try:
        save_config(key, typed_value)
    except Exception as e:
        if json_output:
            from anysite.cli.json_output import json_error

            json_error("CONFIG_ERROR", f"Failed to save configuration: {e}")
        print_error(f"Failed to save configuration: {e}")
        raise typer.Exit(1) from e

    hints = [
        ("View all config", "anysite config list"),
        ("Update schema cache", "anysite schema update"),
    ]
    if key == "api_key":
        hints.append(("Verify API key", "anysite api /api/linkedin/user user=test"))

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"key": key, "value": typed_value},
            hints=hints,
            command="anysite config set",
        )
        return

    print_success(f"Set {key} = {typed_value}")

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("get")
def config_get(
    key: Annotated[str, typer.Argument(help="Configuration key to get")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Get a configuration value.

    \b
    Examples:
      anysite config get api_key
      anysite config get defaults.format
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    value = get_config_value(key)
    if value is None:
        if json_output:
            from anysite.cli.json_output import json_error

            json_error(
                "CONFIG_KEY_NOT_FOUND",
                f"Configuration key '{key}' not found",
                suggestions=[
                    "View available keys: anysite config list",
                    "Set a value: anysite config set <key> <value>",
                ],
            )
        print_error(f"Configuration key '{key}' not found")
        raise typer.Exit(1)

    if json_output:
        from anysite.cli.json_output import json_response

        json_response({"key": key, "value": value}, command="anysite config get")
        return

    # Mask API key for security
    if key == "api_key" and isinstance(value, str) and len(value) > 8:
        masked = value[:4] + "*" * (len(value) - 8) + value[-4:]
        console.print(f"{key}: {masked}")
    else:
        console.print(f"{key}: {value}")


@app.command("list")
def config_list(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """List all configuration values.

    \b
    Examples:
      anysite config list
      anysite config list --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config = list_config()

    hints = [
        ("Change a value", "anysite config set <key> <value>"),
        ("Reset config", "anysite config reset"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(config or {}, hints=hints, command="anysite config list")
        return

    if not config:
        console.print("[dim]No configuration set. Run 'anysite config init' to set up.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    def add_items(data: dict, prefix: str = "") -> None:
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                add_items(value, full_key)
            else:
                # Mask API key
                if key == "api_key" and isinstance(value, str) and len(value) > 8:
                    value = value[:4] + "*" * (len(value) - 8) + value[-4:]
                table.add_row(full_key, str(value))

    add_items(config)
    console.print(table)

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("path")
def config_path(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Show the configuration file path.

    \b
    Example:
      anysite config path
      anysite config path --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    path = get_config_path()

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {
                "config_dir": str(get_config_dir()),
                "config_file": str(path),
                "exists": path.exists(),
            },
            command="anysite config path",
        )
        return

    console.print(f"Config directory: {get_config_dir()}")
    console.print(f"Config file: {path}")
    console.print(f"Exists: {path.exists()}")


@app.command("init")
def config_init(
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            "-k",
            help="API key to set",
            prompt="Enter your Anysite API key",
            hide_input=False,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Initialize configuration interactively.

    \b
    Examples:
      anysite config init
      anysite config init --api-key sk-xxxxx
      anysite config init --api-key sk-xxxxx --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    if not api_key:
        from anysite.cli.json_output import is_non_interactive

        if is_non_interactive():
            if json_output:
                from anysite.cli.json_output import json_error

                json_error(
                    "MISSING_API_KEY",
                    "API key required in non-interactive mode",
                    suggestions=["Pass --api-key: anysite config init --api-key sk-xxxxx"],
                )
            print_error("API key required. Pass --api-key in non-interactive mode.")
            raise typer.Exit(1)
        return

    save_config("api_key", api_key)

    hints = [
        ("Update schema cache", "anysite schema update"),
        ("List all endpoints", "anysite describe"),
        ("Make first API call", "anysite api /api/linkedin/user user=satyanadella"),
    ]

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"config_file": str(get_config_path()), "initialized": True},
            hints=hints,
            command="anysite config init",
        )
        return

    print_success("Configuration initialized!")
    console.print(f"\nConfig saved to: {get_config_path()}")

    from anysite.cli.json_output import print_hints

    print_hints(hints)


@app.command("reset")
def config_reset(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Skip confirmation",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Reset configuration to defaults.

    \b
    Examples:
      anysite config reset
      anysite config reset --force
      anysite config reset --force --json
    """
    from anysite.cli.json_output import resolve_json_output

    json_output = resolve_json_output(json_output)

    config_file = get_config_path()

    if not config_file.exists():
        if json_output:
            from anysite.cli.json_output import json_response

            json_response(
                {"reset": False, "reason": "No config file exists"}, command="anysite config reset"
            )
            return
        console.print("[dim]No configuration file to reset.[/dim]")
        return

    if not force:
        from anysite.cli.json_output import is_non_interactive

        if is_non_interactive():
            if json_output:
                from anysite.cli.json_output import json_error

                json_error(
                    "CONFIRMATION_REQUIRED",
                    "Resetting config requires confirmation",
                    suggestions=["Use --force to skip confirmation: anysite config reset --force"],
                )
            print_error(
                "Resetting config requires confirmation. "
                "Use --force to skip confirmation in non-interactive mode."
            )
            raise typer.Exit(1)
        confirm = typer.confirm("Are you sure you want to reset all configuration?")
        if not confirm:
            console.print("Aborted.")
            return

    config_file.unlink()

    if json_output:
        from anysite.cli.json_output import json_response

        json_response(
            {"reset": True},
            hints=[("Re-initialize", "anysite config init --api-key sk-xxxxx")],
            command="anysite config reset",
        )
        return

    print_success("Configuration reset to defaults")
