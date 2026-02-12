"""Agent discovery payload — two-level system for AI agents.

Level 1: ``echo '' | anysite`` → compact overview (~3-5 KB).
Level 2: ``echo '' | anysite <group>`` → full options, examples, tips.
"""

from __future__ import annotations

import sys
from collections import Counter
from typing import Any

# ── Rich descriptions for Level 1 ──────────────────────────────────────────

COMMAND_DESCRIPTIONS: dict[str, str] = {
    "api": (
        "Call any Anysite API endpoint with key=value parameters. "
        "Types are auto-converted via the schema cache. "
        "Supports single requests, batch input (--from-file / --stdin), "
        "parallel execution (--parallel), and streaming output."
    ),
    "describe": (
        "Explore the API catalog. Search endpoints by keyword (--search), "
        "or view full input/output schemas for a specific endpoint. "
        "Uses the local schema cache — run 'anysite schema update' first."
    ),
    "schema": (
        "Manage the local API schema cache. "
        "Run 'anysite schema update' to fetch the OpenAPI spec."
    ),
    "config": (
        "Manage CLI configuration: API key, default output format, "
        "and other settings stored in ~/.anysite/config.yaml."
    ),
    "db": (
        "Named database connections (SQLite, PostgreSQL, ClickHouse, MySQL). "
        "Add connections, insert/query data, inspect schemas, "
        "discover structure, and catalog databases with optional LLM descriptions."
    ),
    "dataset": (
        "Declarative multi-source data collection pipelines. "
        "Define sources in YAML, collect to Parquet, query with DuckDB, "
        "load into databases, diff snapshots, and schedule automated runs. "
        "Requires: pip install 'anysite-cli[data]'."
    ),
    "llm": (
        "LLM-powered analysis of collected dataset records. "
        "Summarize, classify, enrich, match, deduplicate, and generate text. "
        "Supports OpenAI and Anthropic providers with response caching. "
        "Requires: pip install 'anysite-cli[llm]'."
    ),
    "auth": (
        "Authenticate with Anysite via OAuth2 browser flow or API key. "
        "Check status, login, and logout."
    ),
}

# ── Curated examples and tips for Level 2 ───────────────────────────────────

COMMAND_EXAMPLES: dict[str, dict[str, Any]] = {
    "db": {
        "tips": [
            "Use 'anysite describe --search <keyword>' to find API endpoints.",
            (
                "Pipe API results directly: "
                "anysite api /api/linkedin/user user=satyanadella "
                "| anysite db insert mydb --table users --stdin --auto-create"
            ),
            "Run 'anysite db discover <name>' after adding a connection to auto-catalog.",
        ],
        "subcommands": {
            "add": {
                "examples": [
                    "anysite db add local --type sqlite --path ./data.db",
                    (
                        "anysite db add prod --type postgres "
                        "--host db.example.com --database analytics "
                        "--user app --password-env DB_PASS"
                    ),
                    "anysite db add replica --type postgres --host replica.example.com --read-only",
                ],
            },
            "query": {
                "examples": [
                    'anysite db query mydb --sql "SELECT * FROM users LIMIT 10"',
                    'anysite db query mydb --sql "SELECT * FROM users" --format csv --output users.csv',
                ],
            },
            "insert": {
                "examples": [
                    "anysite db insert mydb --table users --stdin --auto-create < data.jsonl",
                    "anysite db insert mydb --table users --file data.jsonl --on-conflict replace --conflict-columns id",
                ],
            },
            "upsert": {
                "examples": [
                    "anysite db upsert mydb --table users --conflict-columns id --stdin",
                ],
            },
            "discover": {
                "examples": [
                    "anysite db discover mydb",
                    "anysite db discover mydb --with-llm",
                    "anysite db discover mydb --tables users,posts --sample-rows 10",
                ],
            },
            "catalog": {
                "examples": [
                    "anysite db catalog",
                    "anysite db catalog mydb --json",
                    "anysite db catalog mydb --table users",
                ],
            },
        },
    },
    "config": {
        "tips": [
            "Config file: ~/.anysite/config.yaml",
            "Use dot-notation for nested keys: anysite config set llm.default_provider openai",
        ],
        "subcommands": {
            "set": {
                "examples": [
                    "anysite config set api_key YOUR_API_KEY",
                    "anysite config set llm.default_provider openai",
                    "anysite config set llm.providers.openai.api_key sk-...",
                ],
            },
            "get": {"examples": ["anysite config get api_key"]},
            "list": {"examples": ["anysite config list --json"]},
        },
    },
    "llm": {
        "tips": [
            (
                "Configure provider first: "
                "anysite llm setup --provider openai --api-key sk-... --no-test"
            ),
            "Use --dry-run to preview prompts without calling the LLM.",
            "Responses are cached in ~/.anysite/llm_cache.db. Clear with: anysite llm cache-clear",
        ],
        "subcommands": {
            "setup": {
                "examples": [
                    "anysite llm setup --provider openai --api-key sk-... --no-test",
                    "anysite llm setup --provider anthropic --api-key-env ANTHROPIC_API_KEY",
                ],
            },
            "summarize": {
                "examples": [
                    'anysite llm summarize dataset.yaml --source profiles --fields "name,headline"',
                ],
            },
            "classify": {
                "examples": [
                    (
                        "anysite llm classify dataset.yaml --source posts "
                        '--categories "positive,negative,neutral"'
                    ),
                ],
            },
            "enrich": {
                "examples": [
                    (
                        "anysite llm enrich dataset.yaml --source posts "
                        '--add "sentiment:positive/negative/neutral" --add "language:string"'
                    ),
                ],
            },
            "generate": {
                "examples": [
                    (
                        "anysite llm generate dataset.yaml --source profiles "
                        '--prompt "Write intro for {name}" --temperature 0.7'
                    ),
                ],
            },
            "match": {
                "examples": [
                    "anysite llm match dataset.yaml --source-a profiles --source-b companies --top-k 3",
                ],
            },
            "deduplicate": {
                "examples": [
                    "anysite llm deduplicate dataset.yaml --source profiles --key name --threshold 0.8",
                ],
            },
        },
    },
    "dataset": {
        "tips": [
            "Start with 'anysite dataset init <name>' to generate a template YAML.",
            "Run 'anysite dataset guide' for full configuration reference with examples.",
            "Use --incremental to skip already-collected input values.",
            (
                "Collect and load in one step: "
                "anysite dataset collect dataset.yaml --load-db pg"
            ),
        ],
        "subcommands": {
            "init": {"examples": ["anysite dataset init my-dataset"]},
            "collect": {
                "examples": [
                    "anysite dataset collect dataset.yaml",
                    "anysite dataset collect dataset.yaml --source profiles --incremental",
                    "anysite dataset collect dataset.yaml --load-db pg --no-llm",
                    "anysite dataset collect dataset.yaml --dry-run",
                ],
            },
            "query": {
                "examples": [
                    'anysite dataset query dataset.yaml --sql "SELECT * FROM profiles LIMIT 10"',
                    (
                        "anysite dataset query dataset.yaml --source profiles "
                        '--fields "name, urn.value AS urn_id, headline"'
                    ),
                    "anysite dataset query dataset.yaml --interactive",
                ],
            },
            "load-db": {
                "examples": [
                    "anysite dataset load-db dataset.yaml -c pg --drop-existing",
                    "anysite dataset load-db dataset.yaml -c pg --snapshot 2026-01-15",
                ],
            },
            "diff": {
                "examples": [
                    "anysite dataset diff dataset.yaml --source profiles --key _input_value",
                    (
                        "anysite dataset diff dataset.yaml --source profiles "
                        '--key urn.value --fields "name,headline,follower_count"'
                    ),
                ],
            },
            "schedule": {
                "examples": [
                    "anysite dataset schedule dataset.yaml --incremental --load-db pg",
                    "anysite dataset schedule dataset.yaml --systemd",
                ],
            },
            "guide": {"examples": ["anysite dataset guide --list", "anysite dataset guide --section sources"]},
        },
    },
    "auth": {
        "tips": [
            "OAuth2 tokens are stored in ~/.anysite/tokens.json and auto-refresh.",
            "In CI/CD, use API key: anysite config set api_key YOUR_KEY",
        ],
        "subcommands": {
            "login": {
                "examples": [
                    "anysite auth login",
                    "anysite auth login --no-browser",
                    "anysite auth login --force",
                ],
            },
            "logout": {"examples": ["anysite auth logout --force"]},
            "status": {"examples": ["anysite auth status --json"]},
        },
    },
    "api": {
        "tips": [
            "Types are auto-converted using the schema cache (run 'anysite schema update').",
            "Use --from-file with --input-key for batch processing multiple values.",
            (
                "Pipe results to db: anysite api /api/linkedin/user user=X "
                "| anysite db insert mydb --table users --stdin --auto-create"
            ),
        ],
        "examples": [
            "anysite api /api/linkedin/user user=satyanadella",
            "anysite api /api/linkedin/search/users title=CTO count=100 --format csv",
            "anysite api /api/reddit/user user=spez --format table",
            "anysite api /api/linkedin/user --from-file users.txt --input-key user --parallel 5",
            'anysite api /api/linkedin/search/users title=CTO --fields "name,headline,urn.value"',
        ],
    },
    "describe": {
        "tips": [
            "Run 'anysite schema update' first to populate the local cache.",
            "Use 'anysite describe --json' to list all endpoints as JSON.",
            "Use 'anysite describe --json -q' for a compact path-only list.",
        ],
        "examples": [
            "anysite describe --json",
            "anysite describe linkedin.user",
            "anysite describe /api/linkedin/user",
            'anysite describe --search "company"',
            "anysite describe --json -q",
        ],
    },
    "schema": {
        "tips": [
            "Schema is cached at ~/.anysite/schema.json. Re-run 'update' to refresh.",
        ],
        "subcommands": {
            "update": {
                "examples": [
                    "anysite schema update",
                    "anysite schema update --json",
                ],
            },
        },
    },
}


# ── Pipe detection ──────────────────────────────────────────────────────────


def is_pipe_mode() -> bool:
    """Check if stdout is a real pipe (not a test runner StringIO)."""
    from anysite.main import state

    if state.get("human"):
        return False
    try:
        sys.stdout.fileno()
        return not sys.stdout.isatty()
    except (AttributeError, OSError):
        return False


# ── Level 1 — compact root discovery ───────────────────────────────────────


def build_discovery_payload(ctx: Any) -> dict[str, Any]:
    """Build the compact Level 1 discovery JSON for AI agents.

    Args:
        ctx: Typer/Click context from the root command callback.
    """
    from anysite import __version__

    return {
        "ok": True,
        "result": {
            "tool": "anysite-cli",
            "version": __version__,
            "skill": "anysite-skills:anysite-cli",
            "status": _collect_status(),
            "agent_protocol": {
                "auto_json": (
                    "JSON output is automatic when stdout is not a TTY. "
                    "Every command returns a JSON envelope."
                ),
                "force_json": "Pass --json on any command to force JSON output.",
                "force_human": "Pass --human global flag to force human-readable output.",
                "non_interactive": (
                    "Interactive prompts are auto-disabled when stdin is not a TTY. "
                    "Or pass --non-interactive explicitly."
                ),
                "discovery": (
                    "This is the Level 1 overview. "
                    "For detailed options and examples, run: "
                    "echo '' | anysite <group>"
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
            "commands": _discover_commands_compact(ctx),
            "installed_extras": _discover_installed_extras(),
        },
        "meta": {"version": __version__},
    }


def _discover_commands_compact(ctx: Any) -> dict[str, Any]:
    """Level 1: commands with descriptions only, no full options for any command."""
    click_app = ctx.command
    if not hasattr(click_app, "list_commands"):
        return {}

    commands: dict[str, Any] = {}
    for name in click_app.list_commands(ctx):
        cmd = click_app.get_command(ctx, name)
        if cmd is None:
            continue

        description = COMMAND_DESCRIPTIONS.get(name, cmd.get_short_help_str(limit=120))
        entry: dict[str, Any] = {"description": description}

        if hasattr(cmd, "list_commands"):
            # Command group — list subcommands with one-line descriptions
            subs: dict[str, str] = {}
            try:
                for sub_name in cmd.list_commands(ctx):
                    sub_cmd = cmd.get_command(ctx, sub_name)
                    if sub_cmd is not None:
                        subs[sub_name] = sub_cmd.get_short_help_str(limit=120)
            except Exception:  # noqa: BLE001
                pass
            entry["subcommands"] = subs

        entry["detail_command"] = f"echo '' | anysite {name}"
        commands[name] = entry

    return commands


# ── Level 2 — per-group detail ──────────────────────────────────────────────


def build_command_detail(group_name: str, ctx: Any) -> dict[str, Any]:
    """Build Level 2 detail JSON for a specific command group.

    Args:
        group_name: CLI group name (e.g. ``"db"``, ``"llm"``).
        ctx: Typer/Click context from the group's callback.
    """
    from anysite import __version__

    click_group = ctx.command

    # Factor common options
    common_opts, per_cmd_opts = _factor_common_options(click_group, ctx)

    # Get curated detail
    curated = COMMAND_EXAMPLES.get(group_name, {})

    subcommands: dict[str, Any] = {}
    for sub_name in click_group.list_commands(ctx):
        sub_cmd = click_group.get_command(ctx, sub_name)
        if sub_cmd is None:
            continue

        sub_entry: dict[str, Any] = {
            "description": sub_cmd.get_short_help_str(limit=200),
        }

        # Unique options (common ones factored out)
        unique_params = per_cmd_opts.get(sub_name)
        if unique_params:
            sub_entry["options"] = unique_params

        # Curated examples
        curated_subs = curated.get("subcommands", {})
        if sub_name in curated_subs:
            detail = curated_subs[sub_name]
            if detail.get("examples"):
                sub_entry["examples"] = detail["examples"]
            if detail.get("notes"):
                sub_entry["notes"] = detail["notes"]

        subcommands[sub_name] = sub_entry

    result: dict[str, Any] = {
        "group": group_name,
        "description": COMMAND_DESCRIPTIONS.get(
            group_name, click_group.help or ""
        ),
    }

    if common_opts:
        result["common_options"] = common_opts

    result["subcommands"] = subcommands

    if curated.get("tips"):
        result["tips"] = curated["tips"]

    return {
        "ok": True,
        "result": result,
        "meta": {"version": __version__, "command": f"anysite {group_name}"},
    }


def build_single_command_detail(cmd_name: str, click_cmd: Any) -> dict[str, Any]:
    """Build Level 2 detail JSON for a single (non-group) command.

    Used for top-level commands like ``api`` and ``describe`` that have
    no subcommands.

    Args:
        cmd_name: CLI command name (e.g. ``"api"``, ``"describe"``).
        click_cmd: The Click command object.
    """
    from anysite import __version__

    curated = COMMAND_EXAMPLES.get(cmd_name, {})

    result: dict[str, Any] = {
        "command": cmd_name,
        "description": COMMAND_DESCRIPTIONS.get(cmd_name, click_cmd.help or ""),
    }

    params = _serialize_params(click_cmd)
    if params:
        result["options"] = params

    if curated.get("examples"):
        result["examples"] = curated["examples"]

    if curated.get("tips"):
        result["tips"] = curated["tips"]

    return {
        "ok": True,
        "result": result,
        "meta": {"version": __version__, "command": f"anysite {cmd_name}"},
    }


def _factor_common_options(
    click_group: Any, ctx: Any
) -> tuple[list[dict[str, Any]] | None, dict[str, list[dict[str, Any]]]]:
    """Factor out options that appear on many subcommands.

    Returns:
        (common_options, per_command_unique_options)
    """
    sub_names = click_group.list_commands(ctx)
    all_opts: dict[str, dict[str, Any]] = {}
    opt_counts: Counter[str] = Counter()
    per_cmd_all: dict[str, list[dict[str, Any]]] = {}

    for sub_name in sub_names:
        sub_cmd = click_group.get_command(ctx, sub_name)
        if sub_cmd is None:
            continue
        params = _serialize_params(sub_cmd) or []
        per_cmd_all[sub_name] = params
        for p in params:
            pname = p["name"]
            opt_counts[pname] += 1
            if pname not in all_opts:
                all_opts[pname] = p

    # Options on ≥50% of subcommands are common
    threshold = max(2, len(sub_names) // 2)
    common_names = {name for name, count in opt_counts.items() if count >= threshold}

    common = [all_opts[n] for n in common_names] if common_names else None

    per_cmd_unique: dict[str, list[dict[str, Any]]] = {}
    for sub_name, params in per_cmd_all.items():
        unique = [p for p in params if p["name"] not in common_names]
        if unique:
            per_cmd_unique[sub_name] = unique

    return common, per_cmd_unique


# ── Status collection ────────────────────────────────────────────────────────


def _collect_status() -> dict[str, Any]:
    """Collect runtime status: auth, LLM config, database connections."""
    status: dict[str, Any] = {}

    # Auth
    try:
        import os

        from anysite.auth.token_store import TokenStore

        store = TokenStore()
        token = store.load()
        if token is not None and not token.is_expired:
            from datetime import UTC, datetime

            days = (token.expires_at - datetime.now(UTC)).days
            status["auth"] = {
                "method": "oauth2",
                "status": "active",
                "expires_in_days": days,
            }
        elif token is not None:
            status["auth"] = {"method": "oauth2", "status": "expired"}
        elif os.environ.get("ANYSITE_API_KEY"):
            status["auth"] = {
                "method": "api_key",
                "source": "environment",
                "status": "configured",
            }
        else:
            from anysite.config import get_settings

            s = get_settings()
            if s.api_key:
                status["auth"] = {
                    "method": "api_key",
                    "source": "config",
                    "status": "configured",
                }
            else:
                status["auth"] = {"method": "none", "status": "not_authenticated"}
    except Exception:  # noqa: BLE001
        status["auth"] = {"method": "none", "status": "unknown"}

    # LLM
    try:
        from anysite.llm import load_llm_config

        cfg = load_llm_config()
        prov = cfg.providers.get(cfg.default_provider)
        status["llm"] = {
            "configured": True,
            "provider": cfg.default_provider,
            "model": prov.default_model if prov else None,
        }
    except Exception:  # noqa: BLE001
        status["llm"] = {"configured": False}

    # Databases
    try:
        from anysite.db.manager import ConnectionManager

        conns = ConnectionManager().list()
        status["databases"] = [
            {
                "name": c.name,
                "type": c.type.value,
                **({"read_only": True} if c.read_only else {}),
            }
            for c in conns
        ]
    except Exception:  # noqa: BLE001
        status["databases"] = []

    # Schema cache
    try:
        from anysite.config.paths import get_schema_cache_path

        cache_path = get_schema_cache_path()
        if cache_path.exists():
            import json as _json

            data = _json.loads(cache_path.read_text())
            endpoint_count = len(data.get("endpoints", {}))
            status["schema"] = {
                "cached": True,
                "endpoints": endpoint_count,
            }
        else:
            status["schema"] = {
                "cached": False,
                "action_required": "Run 'anysite schema update' to fetch the API catalog. "
                "This is needed for 'anysite describe' and auto-typing in 'anysite api'.",
            }
    except Exception:  # noqa: BLE001
        status["schema"] = {"cached": False}

    return status


# ── Command introspection (shared by both levels) ───────────────────────────


def _param_type_str(click_type: Any) -> str:
    """Convert a Click type to a simple string label."""
    name = click_type.name.lower()
    return {
        "text": "string",
        "string": "string",
        "int": "integer",
        "integer": "integer",
        "float": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "path": "path",
        "choice": "choice",
        "uuid": "string",
        "filename": "path",
    }.get(name, "string")


def _serialize_params(cmd: Any) -> list[dict[str, Any]] | None:
    """Extract CLI parameters from a Click command for agent discovery."""
    params = getattr(cmd, "params", [])
    if not params:
        return None

    result: list[dict[str, Any]] = []
    for p in params:
        if p.name == "help":
            continue

        # Derive a clean name from the longest --flag (strip leading dashes)
        if p.param_type_name == "option" and p.opts:
            clean_name = max(p.opts, key=len).lstrip("-")
        else:
            clean_name = p.human_readable_name

        is_flag = getattr(p, "is_flag", False)

        entry: dict[str, Any] = {
            "name": clean_name,
            "type": "boolean" if is_flag else _param_type_str(p.type),
        }

        if p.param_type_name == "option":
            entry["opts"] = p.opts
            if is_flag:
                entry["is_flag"] = True
        else:
            entry["param_type"] = "argument"

        if p.required:
            entry["required"] = True

        if p.default is not None and not p.required:
            entry["default"] = p.default

        if getattr(p, "help", None):
            entry["help"] = p.help

        if hasattr(p.type, "choices"):
            entry["choices"] = list(p.type.choices)

        if getattr(p, "multiple", False):
            entry["multiple"] = True

        result.append(entry)

    return result or None


# ── Installed extras ─────────────────────────────────────────────────────────


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

    try:
        import clickhouse_connect  # noqa: F401

        extras["clickhouse"] = True
    except ImportError:
        extras["clickhouse"] = False

    try:
        import pymysql  # noqa: F401

        extras["mysql"] = True
    except ImportError:
        extras["mysql"] = False

    return extras
