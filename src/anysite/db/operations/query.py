"""Query operations for database tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anysite.db.adapters.base import DatabaseAdapter


def execute_query(
    adapter: DatabaseAdapter,
    sql: str,
    params: tuple[Any, ...] | None = None,
) -> list[dict[str, Any]]:
    """Execute a SQL query and return results.

    Args:
        adapter: Connected database adapter.
        sql: SQL query string.
        params: Optional query parameters.

    Returns:
        List of row dictionaries.
    """
    return adapter.fetch_all(sql, params)


def execute_query_from_file(
    adapter: DatabaseAdapter,
    file_path: Path,
) -> list[dict[str, Any]]:
    """Execute a SQL query from a file.

    Args:
        adapter: Connected database adapter.
        file_path: Path to SQL file.

    Returns:
        List of row dictionaries.
    """
    sql = file_path.read_text().strip()
    return execute_query(adapter, sql)
