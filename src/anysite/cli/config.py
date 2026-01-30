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
)


@app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Configuration key (e.g., api_key, defaults.format)")],
    value: Annotated[str, typer.Argument(help="Value to set")],
) -> None:
    """Set a configuration value.

    \b
    Examples:
      anysite config set api_key sk-xxxxx
      anysite config set defaults.format table
      anysite config set defaults.count 20
    """
    # Convert value types
    typed_value: str | int | bool = value
    if value.lower() in ("true", "false"):
        typed_value = value.lower() == "true"
    elif value.isdigit():
        typed_value = int(value)

    try:
        save_config(key, typed_value)
        print_success(f"Set {key} = {typed_value}")
    except Exception as e:
        print_error(f"Failed to save configuration: {e}")
        raise typer.Exit(1) from e


@app.command("get")
def config_get(
    key: Annotated[str, typer.Argument(help="Configuration key to get")],
) -> None:
    """Get a configuration value.

    \b
    Examples:
      anysite config get api_key
      anysite config get defaults.format
    """
    value = get_config_value(key)
    if value is None:
        print_error(f"Configuration key '{key}' not found")
        raise typer.Exit(1)

    # Mask API key for security
    if key == "api_key" and isinstance(value, str) and len(value) > 8:
        masked = value[:4] + "*" * (len(value) - 8) + value[-4:]
        console.print(f"{key}: {masked}")
    else:
        console.print(f"{key}: {value}")


@app.command("list")
def config_list() -> None:
    """List all configuration values.

    \b
    Example:
      anysite config list
    """
    config = list_config()

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


@app.command("path")
def config_path() -> None:
    """Show the configuration file path.

    \b
    Example:
      anysite config path
    """
    path = get_config_path()
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
) -> None:
    """Initialize configuration interactively.

    \b
    Example:
      anysite config init
      anysite config init --api-key sk-xxxxx
    """
    if api_key:
        save_config("api_key", api_key)
        print_success("Configuration initialized!")
        console.print(f"\nConfig saved to: {get_config_path()}")
        console.print("\nYou can now run commands like:")
        console.print("  [cyan]anysite linkedin user satyanadella[/cyan]")


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
) -> None:
    """Reset configuration to defaults.

    \b
    Example:
      anysite config reset
      anysite config reset --force
    """
    config_path = get_config_path()

    if not config_path.exists():
        console.print("[dim]No configuration file to reset.[/dim]")
        return

    if not force:
        confirm = typer.confirm("Are you sure you want to reset all configuration?")
        if not confirm:
            console.print("Aborted.")
            return

    config_path.unlink()
    print_success("Configuration reset to defaults")
