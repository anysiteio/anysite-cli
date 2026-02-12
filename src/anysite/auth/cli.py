"""CLI commands for OAuth2 authentication."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.console import Console

app = typer.Typer(
    help="Authenticate with Anysite (OAuth2)",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def auth_callback(ctx: typer.Context) -> None:
    """Auth subsystem entry point."""
    if ctx.invoked_subcommand is None:
        from anysite.cli.discovery import build_command_detail, is_pipe_mode

        if is_pipe_mode():
            import json as _json

            typer.echo(_json.dumps(build_command_detail("auth", ctx), indent=2))
            raise typer.Exit(0)
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

console = Console()


def _get_token_store() -> TokenStore:  # noqa: F821
    """Get a TokenStore instance (patchable in tests)."""
    from anysite.auth.token_store import TokenStore

    return TokenStore()


@app.command("login")
def login(
    auth_server: Annotated[
        str | None,
        typer.Option("--auth-server", help="Auth server URL (default: production)"),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Print auth URL instead of opening browser"),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option("--timeout", help="Seconds to wait for authentication"),
    ] = 120,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-authenticate without confirmation"),
    ] = False,
) -> None:
    """Log in to Anysite via browser-based OAuth2 flow.

    Opens your browser to authenticate. After approval, the CLI
    automatically receives and stores your access token.

    \b
    Examples:
      anysite auth login
      anysite auth login --no-browser
      anysite auth login --auth-server https://staging.anysite.io
    """
    store = _get_token_store()

    # Check for existing valid token
    existing = store.get_valid_token()
    if existing and not force:
        from anysite.cli.json_output import is_non_interactive

        if is_non_interactive():
            raise typer.Exit(0)
        if not typer.confirm("Already logged in. Re-authenticate?", default=False):
            console.print("[dim]Keeping existing session.[/dim]")
            raise typer.Exit(0)

    console.print("Starting OAuth2 authentication flow...")
    if not no_browser:
        console.print("[dim]Opening browser for authorization...[/dim]")
    console.print("[dim]Waiting for authentication (press Ctrl+C to cancel)...[/dim]")

    try:
        from anysite.auth.flow import run_oauth_flow

        token_data = asyncio.run(
            run_oauth_flow(
                auth_server_url=auth_server,
                callback_timeout=timeout,
                token_store=store,
                no_browser=no_browser,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Authentication cancelled.[/yellow]")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"\n[red]Authentication failed:[/red] {e}")
        raise typer.Exit(1) from None

    # Success
    days_left = (token_data.expires_at - _now()).days
    console.print("\n[green]Logged in successfully![/green]")
    console.print(f"  Token expires in {days_left} days")
    console.print(f"  Auth server: {token_data.auth_server_url}")
    console.print()
    console.print("[dim]Next steps:[/dim]")
    console.print("  anysite auth status          Check authentication")
    console.print("  anysite api /api/linkedin/user user=test   Make an API call")


@app.command("logout")
def logout(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Log out by removing stored OAuth tokens.

    \b
    Examples:
      anysite auth logout
      anysite auth logout --force
    """
    store = _get_token_store()

    if store.load() is None:
        console.print("[dim]Not logged in (no OAuth token stored).[/dim]")
        raise typer.Exit(0)

    if not force:
        from anysite.cli.json_output import is_non_interactive

        if is_non_interactive():
            typer.echo(
                "Error: logging out requires confirmation. "
                "Use --force to skip confirmation in non-interactive mode.",
                err=True,
            )
            raise typer.Exit(1)
        if not typer.confirm("Remove stored OAuth token?", default=True):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    store.delete()
    console.print("[green]Logged out.[/green] OAuth token removed.")
    console.print()
    console.print("[dim]To authenticate again:[/dim]")
    console.print("  anysite auth login")
    console.print("  anysite config set api_key <your-key>")


@app.command("status")
def status(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as machine-readable JSON"),
    ] = False,
) -> None:
    """Show current authentication status.

    \b
    Examples:
      anysite auth status
      anysite auth status --json
    """
    import json
    import os

    store = _get_token_store()
    token = store.load()

    # Check OAuth token
    if token is not None:
        if token.is_expired:
            auth_method = "oauth2"
            auth_status = "expired"
            detail = "Token expired. Run: anysite auth login"
        else:
            auth_method = "oauth2"
            auth_status = "active"
            days_left = (token.expires_at - _now()).days
            detail = f"Expires in {days_left} days"

        if json_output:
            typer.echo(json.dumps({
                "method": auth_method,
                "status": auth_status,
                "expires_at": token.expires_at.isoformat(),
                "auth_server": token.auth_server_url,
            }))
        else:
            status_color = "green" if auth_status == "active" else "yellow"
            console.print("  Method:      OAuth2 (via anysite auth login)")
            console.print(f"  Status:      [{status_color}]{auth_status.title()}[/{status_color}]")
            console.print(f"  {detail}")
            console.print(f"  Auth server: {token.auth_server_url}")
        return

    # Check API key
    env_key = os.environ.get("ANYSITE_API_KEY")
    if env_key:
        if json_output:
            typer.echo(json.dumps({"method": "api_key", "source": "environment", "status": "configured"}))
        else:
            console.print("  Method: API key (from ANYSITE_API_KEY env var)")
            console.print("  Status: [green]Configured[/green]")
        return

    from anysite.config import get_settings

    settings = get_settings()
    if settings.api_key:
        if json_output:
            typer.echo(json.dumps({"method": "api_key", "source": "config", "status": "configured"}))
        else:
            console.print("  Method: API key (from config file)")
            console.print("  Status: [green]Configured[/green]")
        return

    # Not authenticated
    if json_output:
        typer.echo(json.dumps({"method": "none", "status": "not_authenticated"}))
    else:
        console.print("  Status: [red]Not authenticated[/red]")
        console.print()
        console.print("[dim]To authenticate:[/dim]")
        console.print("  anysite auth login                        Log in via browser")
        console.print("  anysite config set api_key <your-key>     Set API key manually")


def _now() -> datetime:  # noqa: F821
    """Get current UTC time (patchable in tests)."""
    from datetime import UTC, datetime

    return datetime.now(UTC)
