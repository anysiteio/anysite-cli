"""Helpers for structured JSON output (agent-friendly mode)."""

from __future__ import annotations

import json
import sys
from typing import Any

import typer
from rich.console import Console

from anysite import __version__
from anysite.cli.exit_codes import EXIT_ERROR


def json_response(
    data: Any,
    *,
    hints: list[tuple[str, str]] | None = None,
    command: str | None = None,
) -> None:
    """Print a success JSON envelope to stdout.

    Args:
        data: Payload (dict, list, or scalar).
        hints: List of (action, command) tuples for next-step suggestions.
        command: CLI command name for meta block (e.g., "anysite db add").
    """
    envelope: dict[str, Any] = {"ok": True, "result": data}
    if hints:
        envelope["hints"] = [{"action": a, "command": c} for a, c in hints]
    meta: dict[str, Any] = {"version": __version__}
    if command:
        meta["command"] = command
    envelope["meta"] = meta
    typer.echo(json.dumps(envelope, indent=2, default=str))


def json_error(
    code: str,
    message: str,
    *,
    suggestions: list[str] | None = None,
    retryable: bool = False,
    exit_code: int = EXIT_ERROR,
) -> None:
    """Print an error JSON envelope to stdout and raise typer.Exit.

    Args:
        code: Machine-readable error code (e.g., "CONNECTION_NOT_FOUND").
        message: Human-readable message.
        suggestions: Actionable suggestions for resolving the error.
        retryable: Whether the operation can be retried.
        exit_code: Process exit code.
    """
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if suggestions:
        error["suggestions"] = suggestions
    envelope: dict[str, Any] = {
        "ok": False,
        "error": error,
        "meta": {"version": __version__},
    }
    typer.echo(json.dumps(envelope, indent=2, default=str))
    raise typer.Exit(exit_code)


def json_error_from_exception(exc: Exception) -> None:
    """Convert an AnysiteError (or subclass) to JSON error output."""
    from anysite.api.errors import AnysiteError

    if isinstance(exc, AnysiteError):
        json_error(
            exc.error_code,
            exc.message,
            suggestions=exc.suggestions or None,
            retryable=exc.retryable,
            exit_code=exc.exit_code,
        )
    else:
        json_error("UNKNOWN_ERROR", str(exc))


def print_hints(hints: list[tuple[str, str]], *, quiet: bool = False) -> None:
    """Print next-step hints to stderr.

    Each hint is a (action, command) tuple.
    Suppressed when quiet=True.

    Args:
        hints: List of (action_label, command_string) tuples.
        quiet: If True, suppress output.
    """
    if quiet or not hints:
        return
    stderr = Console(stderr=True)
    stderr.print("\n[dim]Next steps:[/dim]")
    max_action = max(len(a) for a, _ in hints)
    for action, command in hints:
        label = f"{action}:"
        stderr.print(f"  [dim]{label:<{max_action + 2}}[/dim] [cyan]{command}[/cyan]")


def resolve_json_output(explicit: bool = False) -> bool:
    """Decide whether to produce JSON output.

    Priority:
      1. ``--json`` on the command  → always JSON
      2. ``--human`` global flag    → always human
      3. stdout is a real pipe/file → JSON (agent auto-detect)
      4. otherwise                  → human

    Uses ``fileno()`` to distinguish real pipes from test runners
    (Click's CliRunner replaces stdout with a StringIO that has no fd).
    """
    if explicit:
        return True
    from anysite.main import state

    if state.get("human"):
        return False
    # Only auto-detect on real stdout (not inside CliRunner / test harness)
    try:
        sys.stdout.fileno()
    except (AttributeError, OSError):
        return False
    return not sys.stdout.isatty()


def is_non_interactive() -> bool:
    """Check if the CLI is running in non-interactive mode."""
    from anysite.main import state

    if state.get("non_interactive"):
        return True
    return not sys.stdin.isatty()
