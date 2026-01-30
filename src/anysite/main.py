"""Main CLI application."""

from typing import Annotated

import typer
from rich.console import Console

from anysite import __app_name__, __version__
from anysite.cli import config as config_cli
from anysite.cli import instagram as instagram_cli
from anysite.cli import linkedin as linkedin_cli
from anysite.cli import twitter as twitter_cli
from anysite.cli import web as web_cli
from anysite.cli import yc as yc_cli

# Create main app
app = typer.Typer(
    name=__app_name__,
    help="Anysite CLI - Web data extraction for humans and AI agents",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Add subcommands
app.add_typer(linkedin_cli.app, name="linkedin", help="LinkedIn data extraction")
app.add_typer(instagram_cli.app, name="instagram", help="Instagram data extraction")
app.add_typer(twitter_cli.app, name="twitter", help="Twitter/X data extraction")
app.add_typer(web_cli.app, name="web", help="Web page parsing")
app.add_typer(yc_cli.app, name="yc", help="Y Combinator data")
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


if __name__ == "__main__":
    app()
