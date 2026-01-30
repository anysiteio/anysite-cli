"""Shared command execution helpers for CLI commands.

Provides unified execution logic for search/list commands and
single-item commands with Phase 2 features (streaming, batch,
progress, enhanced fields).
"""

import asyncio
import time
from pathlib import Path
from typing import Any

from anysite.api.client import create_client
from anysite.api.errors import AnysiteError
from anysite.batch.executor import BatchExecutor, BatchResult
from anysite.batch.input import InputParser
from anysite.batch.rate_limiter import RateLimiter
from anysite.cli.options import ErrorHandling, parse_exclude, parse_fields
from anysite.output.console import print_error, print_info, print_success
from anysite.output.formatters import OutputFormat, format_output
from anysite.output.templates import FilenameTemplate
from anysite.streaming.progress import ProgressTracker
from anysite.streaming.writer import StreamingWriter
from anysite.utils.fields import resolve_fields_preset


def _resolve_fields(
    fields: str | None,
    exclude: str | None,
    fields_preset: str | None,
) -> tuple[list[str] | None, list[str] | None]:
    """Resolve field selection from various sources.

    Returns:
        Tuple of (fields_to_include, fields_to_exclude)
    """
    include = parse_fields(fields)
    excl = parse_exclude(exclude)

    if fields_preset and not include:
        preset_fields = resolve_fields_preset(fields_preset)
        if preset_fields:
            include = preset_fields

    return include, excl


def _print_stats(stats: dict[str, Any], batch_result: BatchResult | None = None) -> None:
    """Print execution statistics."""
    lines = ["", "Statistics:"]
    lines.append(f"  Total records:    {stats.get('total', 0)}")
    lines.append(f"  Total time:       {stats.get('elapsed_seconds', 0):.1f}s")
    lines.append(f"  Records/second:   {stats.get('records_per_second', 0):.1f}")

    if batch_result:
        lines.append(f"  Succeeded:        {batch_result.succeeded}")
        if batch_result.failed > 0:
            lines.append(f"  Failed:           {batch_result.failed}")
        if batch_result.skipped > 0:
            lines.append(f"  Skipped:          {batch_result.skipped}")

    from anysite.output.console import error_console
    for line in lines:
        error_console.print(f"[dim]{line}[/dim]", style="dim")


async def execute_search_command(
    endpoint: str,
    payload: dict[str, Any],
    *,
    # Phase 1 options
    format: OutputFormat = OutputFormat.JSON,
    fields: str | None = None,
    output: Path | None = None,
    quiet: bool = False,
    # Phase 2: Enhanced fields
    exclude: str | None = None,
    compact: bool = False,
    fields_preset: str | None = None,
    # Phase 2: Streaming
    stream: bool = False,
    # Phase 2: Progress & feedback
    progress: bool | None = None,  # noqa: ARG001
    stats: bool = False,
    verbose: bool = False,
    # Phase 2: Output
    append: bool = False,
) -> None:
    """Execute a search/list command with Phase 2 features.

    Handles:
    - Streaming output (--stream)
    - Enhanced field selection (--exclude, --compact, --fields-preset)
    - Progress bars
    - Statistics
    """
    include_fields, excl_fields = _resolve_fields(fields, exclude, fields_preset)

    async with create_client() as client:
        if verbose:
            print_info(f"Requesting {endpoint} with {payload}")

        start_time = time.monotonic()
        data = await client.post(endpoint, data=payload)
        elapsed = time.monotonic() - start_time

        if verbose:
            count = len(data) if isinstance(data, list) else 1
            print_info(f"Received {count} records in {elapsed:.1f}s")

        # Streaming mode
        if stream and isinstance(data, list):
            writer = StreamingWriter(
                output=output,
                format=OutputFormat.JSONL,
                fields=include_fields,
                exclude=excl_fields,
                compact=compact,
                append=append,
            )
            with writer:
                for record in data:
                    writer.write(record)

            if not quiet and output:
                print_success(f"Streamed {writer.count} records to {output}")

        else:
            # Standard output
            format_output(
                data,
                format,
                include_fields,
                output,
                quiet,
                exclude=excl_fields,
                compact=compact,
                append=append,
            )

        # Show stats
        if stats and not quiet:
            total = len(data) if isinstance(data, list) else 1
            stat_data = {
                "total": total,
                "elapsed_seconds": round(elapsed, 2),
                "records_per_second": round(total / elapsed, 1) if elapsed > 0 else 0,
            }
            _print_stats(stat_data)


async def execute_single_command(
    endpoint: str,
    payload: dict[str, Any],
    *,
    # Phase 1 options
    format: OutputFormat = OutputFormat.JSON,
    fields: str | None = None,
    output: Path | None = None,
    quiet: bool = False,
    # Phase 2: Batch input
    from_file: Path | None = None,
    stdin: bool = False,
    parallel: int = 1,
    delay: float = 0.0,
    on_error: ErrorHandling = ErrorHandling.STOP,
    # Phase 2: Enhanced fields
    exclude: str | None = None,
    compact: bool = False,
    fields_preset: str | None = None,
    # Phase 2: Rate limiting
    rate_limit: str | None = None,
    # Phase 2: Progress & feedback
    progress: bool | None = None,
    stats: bool = False,
    verbose: bool = False,
    # Phase 2: Output
    append: bool = False,
    output_dir: Path | None = None,
    filename_template: str = "{id}",
    # Batch-specific
    input_key: str = "user",
    extra_payload: dict[str, Any] | None = None,
) -> None:
    """Execute a single-item command with optional batch support.

    Handles:
    - Batch input from file or stdin (--from-file, --stdin)
    - Parallel execution (--parallel)
    - Rate limiting (--rate-limit)
    - Per-file output (--output-dir)
    - Progress bars
    """
    include_fields, excl_fields = _resolve_fields(fields, exclude, fields_preset)

    # Check for batch mode
    is_batch = from_file is not None or stdin

    if not is_batch:
        # Single request (backward compatible path)
        async with create_client() as client:
            if verbose:
                print_info(f"Requesting {endpoint} with {payload}")

            start_time = time.monotonic()
            data = await client.post(endpoint, data=payload)
            elapsed = time.monotonic() - start_time

            if verbose:
                print_info(f"Received response in {elapsed:.1f}s")

            format_output(
                data,
                format,
                include_fields,
                output,
                quiet,
                exclude=excl_fields,
                compact=compact,
                append=append,
            )

            if stats and not quiet:
                total = len(data) if isinstance(data, list) else 1
                stat_data = {
                    "total": total,
                    "elapsed_seconds": round(elapsed, 2),
                    "records_per_second": round(total / elapsed, 1) if elapsed > 0 else 0,
                }
                _print_stats(stat_data)

        return

    # Batch mode
    inputs = InputParser.from_file(from_file) if from_file else InputParser.from_stdin()

    if not inputs:
        if not quiet:
            print_error("No inputs found")
        return

    if verbose:
        print_info(f"Processing {len(inputs)} inputs (parallel={parallel})")

    # Setup rate limiter
    limiter = RateLimiter(rate_limit) if rate_limit else None

    # Setup progress
    tracker = ProgressTracker(
        total=len(inputs),
        description="Processing...",
        show=progress,
        quiet=quiet,
    )

    # Create the async fetch function
    async def _fetch_one(inp: str | dict[str, Any]) -> Any:
        # Determine the input value
        if isinstance(inp, dict):
            val = inp.get(input_key, inp.get("value", str(list(inp.values())[0])))
        else:
            val = inp

        request_payload = {input_key: val}
        if extra_payload:
            request_payload.update(extra_payload)

        async with create_client() as client:
            return await client.post(endpoint, data=request_payload)

    # Execute batch
    executor = BatchExecutor(
        func=_fetch_one,
        parallel=parallel,
        delay=delay,
        on_error=on_error,
        rate_limiter=limiter,
        progress_callback=tracker.update,
    )

    with tracker:
        batch_result = await executor.execute(inputs)

    # Output results
    if output_dir:
        # Per-file output
        output_dir.mkdir(parents=True, exist_ok=True)
        ext_map = {
            OutputFormat.JSON: ".json",
            OutputFormat.JSONL: ".jsonl",
            OutputFormat.CSV: ".csv",
            OutputFormat.TABLE: ".json",
        }
        template = FilenameTemplate(
            filename_template,
            extension=ext_map.get(format, ".json"),
        )

        for i, result in enumerate(batch_result.results):
            inp = inputs[i] if i < len(inputs) else ""
            input_val = inp if isinstance(inp, str) else str(list(inp.values())[0]) if isinstance(inp, dict) else str(inp)
            filename = template.resolve(
                record=result,
                index=i,
                input_value=input_val,
            )
            filepath = output_dir / filename
            format_output(
                result,
                format,
                include_fields,
                filepath,
                quiet=True,
                exclude=excl_fields,
                compact=compact,
            )

        if not quiet:
            print_success(f"Saved {len(batch_result.results)} files to {output_dir}/")

    else:
        # Collect all results and output together
        all_results = []
        for result in batch_result.results:
            if isinstance(result, list):
                all_results.extend(result)
            elif isinstance(result, dict) and "data" in result:
                data = result["data"]
                if isinstance(data, list):
                    all_results.extend(data)
                else:
                    all_results.append(data)
            else:
                all_results.append(result)

        format_output(
            all_results,
            format,
            include_fields,
            output,
            quiet,
            exclude=excl_fields,
            compact=compact,
            append=append,
        )

    # Show stats
    if stats and not quiet:
        _print_stats(tracker.get_stats(), batch_result)


def run_search_command(
    endpoint: str,
    payload: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Sync wrapper for execute_search_command.

    Catches AnysiteError and exits with proper error message.
    """
    import typer

    try:
        asyncio.run(execute_search_command(endpoint, payload, **kwargs))
    except AnysiteError as e:
        print_error(str(e))
        raise typer.Exit(1) from None


def run_single_command(
    endpoint: str,
    payload: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Sync wrapper for execute_single_command.

    Catches AnysiteError and exits with proper error message.
    """
    import typer

    try:
        asyncio.run(execute_single_command(endpoint, payload, **kwargs))
    except AnysiteError as e:
        print_error(str(e))
        raise typer.Exit(1) from None
    except (FileNotFoundError, ValueError) as e:
        print_error(str(e))
        raise typer.Exit(1) from None
