"""Dataset collection orchestrator."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from anysite.api.client import create_client
from anysite.batch.executor import BatchExecutor
from anysite.batch.rate_limiter import RateLimiter
from anysite.cli.options import ErrorHandling
from anysite.dataset.errors import DatasetError
from anysite.dataset.models import DatasetConfig, DatasetSource
from anysite.dataset.storage import (
    MetadataStore,
    get_parquet_path,
    read_parquet,
    write_parquet,
)
from anysite.output.console import print_info, print_success, print_warning
from anysite.streaming.progress import ProgressTracker
from anysite.utils.fields import extract_field, parse_field_path


class CollectionPlan:
    """Describes what will be collected without executing."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add_step(
        self,
        source_id: str,
        endpoint: str,
        kind: str,
        params: dict[str, Any] | None = None,
        dependency: str | None = None,
        estimated_requests: int | None = None,
    ) -> None:
        self.steps.append({
            "source": source_id,
            "endpoint": endpoint,
            "kind": kind,
            "params": params or {},
            "dependency": dependency,
            "estimated_requests": estimated_requests,
        })


async def collect_dataset(
    config: DatasetConfig,
    *,
    config_dir: Path | None = None,
    source_filter: str | None = None,
    incremental: bool = False,
    dry_run: bool = False,
    quiet: bool = False,
) -> dict[str, int]:
    """Collect all sources in a dataset.

    Args:
        config: Dataset configuration.
        source_filter: If set, only collect this source (and its dependencies).
        incremental: Skip sources that already have data for today.
        dry_run: Show plan without executing.
        quiet: Suppress progress output.

    Returns:
        Dict mapping source_id to record count collected.
    """
    if config_dir is None:
        config_dir = Path.cwd()
    base_path = config.storage_path()
    metadata = MetadataStore(base_path)
    today = date.today()

    # Get execution order
    ordered = config.topological_sort()

    # Filter to requested source (and its dependencies)
    if source_filter:
        ordered = _filter_sources(ordered, source_filter, config)

    if dry_run:
        plan = _build_plan(ordered, config, base_path, metadata, incremental, today)
        return _print_plan(plan)

    results: dict[str, int] = {}

    for source in ordered:
        # Check incremental skip
        if incremental:
            parquet_path = get_parquet_path(base_path, source.id, today)
            if parquet_path.exists():
                if not quiet:
                    print_info(f"Skipping {source.id} (already collected today)")
                info = metadata.get_source_info(source.id)
                results[source.id] = info.get("record_count", 0) if info else 0
                continue

        if not quiet:
            print_info(f"Collecting {source.id} from {source.endpoint}...")

        if source.from_file is not None:
            file_base = config_dir if config_dir else Path.cwd()
            records = await _collect_from_file(source, config_dir=file_base, quiet=quiet)
        elif source.dependency is None:
            records = await _collect_independent(source)
        else:
            records = await _collect_dependent(source, base_path, quiet=quiet)

        # Write to Parquet
        parquet_path = get_parquet_path(base_path, source.id, today)
        count = write_parquet(records, parquet_path)
        metadata.update_source(source.id, count, today)
        results[source.id] = count

        if not quiet:
            print_success(f"Collected {count} records for {source.id}")

    return results


async def _collect_independent(source: DatasetSource) -> list[dict[str, Any]]:
    """Collect an independent source (single API call)."""
    async with create_client() as client:
        data = await client.post(source.endpoint, data=source.params)
    # API returns list[dict] or dict
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) else [{"data": data}]


async def _collect_from_file(
    source: DatasetSource,
    *,
    config_dir: Path,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Collect a source by iterating over values from an input file."""
    from anysite.batch.input import InputParser

    if not source.from_file:
        raise DatasetError(f"Source {source.id} has no from_file defined")
    if not source.input_key:
        raise DatasetError(f"Source {source.id} has from_file but no input_key defined")

    file_path = Path(source.from_file)
    if not file_path.is_absolute():
        file_path = config_dir / file_path
    if not file_path.exists():
        raise DatasetError(f"Input file not found: {file_path}")

    # Parse inputs from file
    raw_inputs = InputParser.from_file(file_path)
    if not raw_inputs:
        if not quiet:
            print_warning(f"No inputs found in {file_path}")
        return []

    # Extract specific field from CSV/JSONL dicts if file_field is set
    values: list[str] = []
    for inp in raw_inputs:
        if isinstance(inp, dict) and source.file_field:
            val = inp.get(source.file_field)
            if val is not None:
                values.append(str(val))
        elif isinstance(inp, str):
            values.append(inp)
        else:
            values.append(str(inp))

    if not values:
        if not quiet:
            print_warning(f"No values extracted from {file_path}")
        return []

    if not quiet:
        print_info(f"  Found {len(values)} inputs from {file_path.name}")

    return await _collect_batch(source, values, quiet=quiet)


async def _collect_batch(
    source: DatasetSource,
    values: list[Any],
    *,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run batch API calls for a list of input values."""
    limiter = RateLimiter(source.rate_limit) if source.rate_limit else None
    on_error = ErrorHandling(source.on_error) if source.on_error else ErrorHandling.SKIP

    tracker = ProgressTracker(
        total=len(values),
        description=f"Collecting {source.id}...",
        quiet=quiet,
    )

    async def _fetch_one(val: str | dict[str, Any]) -> Any:
        # Apply input_template if defined
        if source.input_template:
            input_val = _apply_template(source.input_template, val)
        else:
            input_val = val
        payload = {source.input_key: input_val, **source.params}  # type: ignore[dict-item]
        async with create_client() as client:
            return await client.post(source.endpoint, data=payload)

    executor = BatchExecutor(
        func=_fetch_one,
        parallel=source.parallel,
        on_error=on_error,
        rate_limiter=limiter,
        progress_callback=tracker.update,
    )

    with tracker:
        batch_result = await executor.execute(values)

    return _flatten_results(batch_result.results)


def _flatten_results(results: list[Any]) -> list[dict[str, Any]]:
    """Flatten batch results into a flat list of dicts."""
    all_records: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, list):
            all_records.extend(r for r in result if isinstance(r, dict))
        elif isinstance(result, dict):
            data = result.get("data", result)
            if isinstance(data, list):
                all_records.extend(r for r in data if isinstance(r, dict))
            elif isinstance(data, dict):
                all_records.append(data)
            else:
                all_records.append(result)
    return all_records


async def _collect_dependent(
    source: DatasetSource,
    base_path: Path,
    *,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Collect a dependent source by reading parent data and making per-value requests."""
    dep = source.dependency
    if dep is None:
        raise DatasetError(f"Source {source.id} has no dependency defined")

    # Read parent data
    parent_dir = base_path / "raw" / dep.from_source
    parent_records = read_parquet(parent_dir)

    if not parent_records:
        if not quiet:
            print_warning(f"No parent data for {dep.from_source}, skipping {source.id}")
        return []

    # Extract values from parent
    values = _extract_values(parent_records, dep.field, dep.match_by, dep.dedupe)

    if not values:
        if not quiet:
            print_warning(f"No values extracted from {dep.from_source} for {source.id}")
        return []

    if not source.input_key:
        raise DatasetError(
            f"Source {source.id} has a dependency but no input_key defined"
        )

    return await _collect_batch(source, values, quiet=quiet)


def _apply_template(template: dict[str, Any], value: Any) -> dict[str, Any]:
    """Apply a template dict, replacing '{value}' placeholders with the actual value."""
    result: dict[str, Any] = {}
    for k, v in template.items():
        if isinstance(v, str) and v == "{value}":
            result[k] = str(value) if not isinstance(value, (dict, list)) else value
        elif isinstance(v, str) and "{value}" in v:
            result[k] = v.replace("{value}", str(value))
        elif isinstance(v, dict):
            result[k] = _apply_template(v, value)
        else:
            result[k] = v
    return result


def _try_parse_json(value: Any) -> Any:
    """Try to parse a JSON string back into a dict/list."""
    import json

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return value


def _extract_values(
    records: list[dict[str, Any]],
    field: str | None,
    match_by: str | None,
    dedupe: bool,
) -> list[Any]:
    """Extract values from parent records."""
    if match_by:
        field = match_by

    if not field:
        raise DatasetError("Dependency must specify either 'field' or 'match_by'")

    segments = parse_field_path(field)
    values: list[Any] = []

    for record in records:
        # Parquet stores nested objects as JSON strings — parse them back
        # so that dot-notation paths like "urn.value" work correctly
        parsed_record = {k: _try_parse_json(v) for k, v in record.items()}
        value = extract_field(parsed_record, segments)
        if value is not None:
            value = _try_parse_json(value)
            if isinstance(value, list):
                values.extend(value)
            else:
                values.append(value)

    if dedupe:
        seen: set[str] = set()
        unique: list[Any] = []
        for v in values:
            key = str(v)
            if key not in seen:
                seen.add(key)
                unique.append(v)
        values = unique

    return values


def _filter_sources(
    ordered: list[DatasetSource],
    source_filter: str,
    config: DatasetConfig,
) -> list[DatasetSource]:
    """Filter sources to only include the target and its transitive dependencies."""
    target = config.get_source(source_filter)
    if target is None:
        raise DatasetError(f"Source '{source_filter}' not found in dataset")

    # Collect all required source IDs (target + transitive deps)
    required: set[str] = set()
    stack = [source_filter]
    while stack:
        sid = stack.pop()
        if sid in required:
            continue
        required.add(sid)
        src = config.get_source(sid)
        if src and src.dependency:
            stack.append(src.dependency.from_source)

    return [s for s in ordered if s.id in required]


def _build_plan(
    ordered: list[DatasetSource],
    config: DatasetConfig,
    base_path: Path,
    metadata: MetadataStore,
    incremental: bool,
    today: date,
) -> CollectionPlan:
    """Build a dry-run plan."""
    plan = CollectionPlan()

    for source in ordered:
        if incremental:
            parquet_path = get_parquet_path(base_path, source.id, today)
            if parquet_path.exists():
                continue

        if source.from_file is not None:
            plan.add_step(
                source_id=source.id,
                endpoint=source.endpoint,
                kind="from_file",
                params={"file": source.from_file, "field": source.file_field},
            )
        elif source.dependency is None:
            plan.add_step(
                source_id=source.id,
                endpoint=source.endpoint,
                kind="independent",
                params=source.params,
            )
        else:
            # Estimate requests from parent data count
            parent_info = metadata.get_source_info(source.dependency.from_source)
            est = parent_info.get("record_count") if parent_info else None
            plan.add_step(
                source_id=source.id,
                endpoint=source.endpoint,
                kind="dependent",
                dependency=source.dependency.from_source,
                estimated_requests=est,
            )

    return plan


def _print_plan(plan: CollectionPlan) -> dict[str, int]:
    """Print the collection plan and return empty results."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Collection Plan")
    table.add_column("Step", style="bold")
    table.add_column("Source")
    table.add_column("Endpoint")
    table.add_column("Type")
    table.add_column("Depends On")
    table.add_column("Est. Requests")

    for i, step in enumerate(plan.steps, 1):
        table.add_row(
            str(i),
            step["source"],
            step["endpoint"],
            step["kind"],
            step.get("dependency") or "-",
            str(step.get("estimated_requests") or "?"),
        )

    console.print(table)
    return {}


def run_collect(
    config: DatasetConfig,
    **kwargs: Any,
) -> dict[str, int]:
    """Sync wrapper for collect_dataset."""
    return asyncio.run(collect_dataset(config, **kwargs))
