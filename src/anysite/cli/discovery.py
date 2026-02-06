"""Agent discovery payload — returned when an agent first invokes the CLI."""

from __future__ import annotations

from typing import Any


def build_discovery_payload(ctx: Any) -> dict[str, Any]:
    """Build the full discovery JSON for AI agents.

    Args:
        ctx: Typer/Click context from the root command callback.
    """
    from anysite import __version__

    return {
        "ok": True,
        "result": {
            "tool": "anysite-cli",
            "version": __version__,
            "agent_protocol": {
                "auto_json": (
                    "JSON output is automatic when stdout is not a TTY. "
                    "Every management command returns a JSON envelope."
                ),
                "force_json": "Pass --json on any command to force JSON output in a terminal.",
                "force_human": "Pass --human global flag to force human-readable output in pipes.",
                "non_interactive": (
                    "Interactive prompts are auto-disabled when stdin is not a TTY. "
                    "Or pass --non-interactive explicitly."
                ),
            },
            "output_schema": {
                "success": {
                    "ok": True,
                    "result": "<command-specific data>",
                    "hints": [{"action": "<description>", "command": "<example>"}],
                    "meta": {"version": "<semver>", "command": "<cli command>"},
                },
                "error": {
                    "ok": False,
                    "error": {
                        "code": "<ERROR_CODE>",
                        "message": "<human description>",
                        "retryable": False,
                        "suggestions": ["<actionable fix>"],
                    },
                    "meta": {"version": "<semver>"},
                },
            },
            "exit_codes": {
                "0": "success",
                "1": "error",
                "2": "usage",
                "3": "auth",
                "4": "not_found",
                "5": "network",
            },
            "commands": _discover_commands(ctx),
            "installed_extras": _discover_installed_extras(),
        },
        "meta": {"version": __version__},
    }


def _discover_commands(ctx: Any) -> dict[str, Any]:
    """Introspect the Click/Typer app to list commands and subcommands."""
    click_app = ctx.command
    if not hasattr(click_app, "list_commands"):
        return {}

    commands: dict[str, Any] = {}
    for name in click_app.list_commands(ctx):
        cmd = click_app.get_command(ctx, name)
        if cmd is None:
            continue

        entry: dict[str, Any] = {
            "description": cmd.get_short_help_str(limit=120),
        }

        # Command group → list subcommands
        if hasattr(cmd, "list_commands"):
            subs: list[dict[str, str]] = []
            try:
                for sub_name in cmd.list_commands(ctx):
                    sub_cmd = cmd.get_command(ctx, sub_name)
                    if sub_cmd:
                        subs.append(
                            {
                                "name": sub_name,
                                "description": sub_cmd.get_short_help_str(limit=120),
                            }
                        )
            except Exception:  # noqa: BLE001
                pass
            entry["subcommands"] = subs
            entry["supports_json"] = True
        else:
            # Check if this command has a --json option
            has_json = any("--json" in (p.opts or []) for p in getattr(cmd, "params", []))
            entry["supports_json"] = has_json

        commands[name] = entry

    return commands


def _discover_installed_extras() -> dict[str, bool]:
    """Detect which optional extras are installed."""
    extras: dict[str, bool] = {}

    try:
        import duckdb  # noqa: F401
        import pyarrow  # noqa: F401

        extras["data"] = True
    except ImportError:
        extras["data"] = False

    try:
        import openai  # noqa: F401

        extras["llm"] = True
    except ImportError:
        extras["llm"] = False

    try:
        import psycopg  # noqa: F401

        extras["postgres"] = True
    except ImportError:
        extras["postgres"] = False

    return extras
