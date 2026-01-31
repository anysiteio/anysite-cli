"""Insert operations for streaming JSON data into database tables."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any, TextIO

from anysite.db.adapters.base import DatabaseAdapter
from anysite.db.config import OnConflict
from anysite.db.schema.inference import infer_table_schema
from anysite.db.utils.sanitize import sanitize_table_name


def insert_from_stream(
    adapter: DatabaseAdapter,
    table: str,
    stream: TextIO | IO[str],
    on_conflict: OnConflict = OnConflict.ERROR,
    conflict_columns: list[str] | None = None,
    auto_create: bool = False,
    primary_key: str | None = None,
    batch_size: int = 100,
    quiet: bool = False,
) -> int:
    """Read JSONL from a stream and insert rows into a database table.

    Each line is parsed as a JSON object. If the input is a JSON array,
    the array elements are used as rows.

    Args:
        adapter: Connected database adapter.
        table: Target table name.
        stream: Input stream (stdin or file).
        on_conflict: Conflict resolution strategy.
        conflict_columns: Columns for upsert conflict detection.
        auto_create: Create the table automatically if it doesn't exist.
        primary_key: Primary key column for auto-created tables.
        batch_size: Number of rows per batch insert.
        quiet: Suppress progress output.

    Returns:
        Total number of rows inserted.
    """
    rows = _read_json_stream(stream)
    if not rows:
        return 0

    # Auto-create table if requested
    if auto_create and not adapter.table_exists(table):
        schema = infer_table_schema(table, rows)
        dialect = _get_dialect(adapter)
        sql_types = schema.to_sql_types(dialect)
        adapter.create_table(table, sql_types, primary_key=primary_key)
        if not quiet:
            import typer

            safe = sanitize_table_name(table)
            typer.echo(f"Created table {safe} with {len(sql_types)} columns", err=True)

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        count = adapter.insert_batch(
            table, batch, on_conflict=on_conflict, conflict_columns=conflict_columns
        )
        total += count

    return total


def _read_json_stream(stream: TextIO | IO[str]) -> list[dict[str, Any]]:
    """Read JSON or JSONL data from a stream.

    Handles three formats:
    1. JSON array: [{"a": 1}, {"b": 2}]
    2. JSONL: one JSON object per line
    3. Single JSON object: {"a": 1}

    Args:
        stream: Input stream.

    Returns:
        List of row dictionaries.
    """
    content = stream.read().strip()
    if not content:
        return []

    # Try parsing as a JSON array or single object first
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        elif isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass

    # Parse as JSONL (one JSON object per line)
    rows: list[dict[str, Any]] = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            continue

    return rows


def insert_from_file(
    adapter: DatabaseAdapter,
    table: str,
    file_path: Path,
    on_conflict: OnConflict = OnConflict.ERROR,
    conflict_columns: list[str] | None = None,
    auto_create: bool = False,
    primary_key: str | None = None,
    batch_size: int = 100,
    quiet: bool = False,
) -> int:
    """Read JSONL from a file and insert rows into a database table.

    Args:
        adapter: Connected database adapter.
        table: Target table name.
        file_path: Path to JSONL/JSON file.
        on_conflict: Conflict resolution strategy.
        conflict_columns: Columns for upsert conflict detection.
        auto_create: Create the table automatically if it doesn't exist.
        primary_key: Primary key column for auto-created tables.
        batch_size: Number of rows per batch insert.
        quiet: Suppress progress output.

    Returns:
        Total number of rows inserted.
    """
    with open(file_path) as f:
        return insert_from_stream(
            adapter,
            table,
            f,
            on_conflict=on_conflict,
            conflict_columns=conflict_columns,
            auto_create=auto_create,
            primary_key=primary_key,
            batch_size=batch_size,
            quiet=quiet,
        )


def insert_from_stdin(
    adapter: DatabaseAdapter,
    table: str,
    on_conflict: OnConflict = OnConflict.ERROR,
    conflict_columns: list[str] | None = None,
    auto_create: bool = False,
    primary_key: str | None = None,
    batch_size: int = 100,
    quiet: bool = False,
) -> int:
    """Read JSONL from stdin and insert rows.

    Args:
        adapter: Connected database adapter.
        table: Target table name.
        on_conflict: Conflict resolution strategy.
        conflict_columns: Columns for upsert conflict detection.
        auto_create: Create the table automatically if it doesn't exist.
        primary_key: Primary key column for auto-created tables.
        batch_size: Number of rows per batch insert.
        quiet: Suppress progress output.

    Returns:
        Total number of rows inserted.
    """
    return insert_from_stream(
        adapter,
        table,
        sys.stdin,
        on_conflict=on_conflict,
        conflict_columns=conflict_columns,
        auto_create=auto_create,
        primary_key=primary_key,
        batch_size=batch_size,
        quiet=quiet,
    )


def _get_dialect(adapter: DatabaseAdapter) -> str:
    """Get the SQL dialect name from an adapter."""
    info = adapter.get_server_info()
    return info.get("type", "sqlite")
