"""Shared CLI option definitions for all platform commands."""

import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from anysite.output.formatters import OutputFormat

# === Phase 1 Options (extracted from individual CLI modules) ===

FormatOption = Annotated[
    OutputFormat,
    typer.Option(
        "--format", "-f",
        help="Output format",
        case_sensitive=False,
    ),
]

FieldsOption = Annotated[
    str | None,
    typer.Option(
        "--fields",
        help="Comma-separated list of fields to include",
    ),
]

OutputOption = Annotated[
    Path | None,
    typer.Option(
        "--output", "-o",
        help="Save output to file",
    ),
]

QuietOption = Annotated[
    bool,
    typer.Option(
        "--quiet", "-q",
        help="Suppress non-data output",
    ),
]


# === Phase 2: Enhanced Field Selection ===

ExcludeOption = Annotated[
    str | None,
    typer.Option(
        "--exclude",
        help="Comma-separated list of fields to exclude",
        rich_help_panel="Output Options",
    ),
]

CompactOption = Annotated[
    bool,
    typer.Option(
        "--compact",
        help="Compact output (no indentation)",
        rich_help_panel="Output Options",
    ),
]

FieldsPresetOption = Annotated[
    str | None,
    typer.Option(
        "--fields-preset",
        help="Named field preset (minimal, contact, recruiting)",
        rich_help_panel="Output Options",
    ),
]


# === Phase 2: Streaming ===

StreamOption = Annotated[
    bool,
    typer.Option(
        "--stream/--no-stream",
        help="Stream output as JSONL (one record per line)",
        rich_help_panel="Output Options",
    ),
]


# === Phase 2: Output Enhancements ===

AppendOption = Annotated[
    bool,
    typer.Option(
        "--append",
        help="Append to existing output file",
        rich_help_panel="Output Options",
    ),
]

OutputDirOption = Annotated[
    Path | None,
    typer.Option(
        "--output-dir",
        help="Output directory (one file per record in batch mode)",
        rich_help_panel="Output Options",
    ),
]

FilenameTemplateOption = Annotated[
    str,
    typer.Option(
        "--filename-template",
        help="Filename template for batch output ({id}, {username}, {date}, {index})",
        rich_help_panel="Output Options",
    ),
]


# === Phase 2: Batch Input ===

FromFileOption = Annotated[
    Path | None,
    typer.Option(
        "--from-file",
        help="Read inputs from file (one per line, or JSONL/CSV)",
        rich_help_panel="Batch Input",
    ),
]

StdinOption = Annotated[
    bool,
    typer.Option(
        "--stdin",
        help="Read inputs from stdin",
        rich_help_panel="Batch Input",
    ),
]

ParallelOption = Annotated[
    int,
    typer.Option(
        "--parallel", "-j",
        help="Number of parallel requests",
        rich_help_panel="Batch Input",
    ),
]

DelayOption = Annotated[
    float,
    typer.Option(
        "--delay",
        help="Delay between requests in seconds",
        rich_help_panel="Batch Input",
    ),
]


class ErrorHandling(str, Enum):
    """Error handling modes for batch operations."""

    STOP = "stop"
    SKIP = "skip"
    RETRY = "retry"


OnErrorOption = Annotated[
    ErrorHandling,
    typer.Option(
        "--on-error",
        help="Error handling mode: stop, skip, or retry",
        rich_help_panel="Batch Input",
    ),
]


# === Phase 2: Rate Limiting ===

RateLimitOption = Annotated[
    str | None,
    typer.Option(
        "--rate-limit",
        help="Rate limit (e.g., '10/s', '100/m', '1000/h')",
        rich_help_panel="Advanced",
    ),
]


# === Phase 2: Progress & Feedback ===

ProgressOption = Annotated[
    bool | None,
    typer.Option(
        "--progress/--no-progress",
        help="Show progress bar",
        rich_help_panel="Advanced",
    ),
]

StatsOption = Annotated[
    bool,
    typer.Option(
        "--stats",
        help="Show statistics after completion",
        rich_help_panel="Advanced",
    ),
]

VerboseOption = Annotated[
    bool,
    typer.Option(
        "--verbose",
        help="Verbose output with debug information",
        rich_help_panel="Advanced",
    ),
]


def parse_fields(fields: str | None) -> list[str] | None:
    """Parse comma-separated fields string.

    Args:
        fields: Comma-separated field names or None

    Returns:
        List of field names or None
    """
    if not fields:
        return None
    return [f.strip() for f in fields.split(",")]


def parse_exclude(exclude: str | None) -> list[str] | None:
    """Parse comma-separated exclude fields string.

    Args:
        exclude: Comma-separated field names to exclude or None

    Returns:
        List of field names or None
    """
    if not exclude:
        return None
    return [f.strip() for f in exclude.split(",")]


def is_stdin_piped() -> bool:
    """Check if stdin has piped data."""
    return not sys.stdin.isatty()
