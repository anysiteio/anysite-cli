"""DuckDB-based analytics for dataset Parquet files."""

from __future__ import annotations

import re
from typing import Any

from anysite.dataset.models import DatasetConfig
from anysite.dataset.storage import get_source_dir


def expand_dot_fields(fields_str: str) -> str:
    """Convert dot-notation field specs to DuckDB SQL expressions.

    Simple fields pass through unchanged.  Dotted fields are converted to
    ``json_extract_string`` calls so that nested values stored as JSON
    strings in Parquet can be extracted directly.

    Examples::

        "name, age"                  -> "name, age"
        "urn.value AS urn_id"        -> "json_extract_string(urn, '$.value') AS urn_id"
        "author.name"                -> "json_extract_string(author, '$.name')"
        "a.b.c"                      -> "json_extract_string(a, '$.b.c')"
    """
    parts: list[str] = []
    for spec in fields_str.split(","):
        spec = spec.strip()
        if not spec:
            continue

        # Detect optional AS alias (case-insensitive)
        alias = ""
        as_match = re.search(r"\s+[Aa][Ss]\s+(\w+)$", spec)
        if as_match:
            alias = f" AS {as_match.group(1)}"
            spec = spec[: as_match.start()]

        if "." in spec:
            col, rest = spec.split(".", 1)
            parts.append(f"json_extract_string({col}, '$.{rest}'){alias}")
        else:
            parts.append(f"{spec}{alias}")

    return ", ".join(parts)


def _get_duckdb() -> Any:
    import duckdb

    return duckdb


class DatasetAnalyzer:
    """Run SQL queries and analytics over dataset Parquet files using DuckDB."""

    def __init__(self, config: DatasetConfig) -> None:
        self.config = config
        self.base_path = config.storage_path()
        self._conn: Any = None

    def _get_conn(self) -> Any:
        """Get or create a DuckDB connection with views registered."""
        if self._conn is not None:
            return self._conn

        duckdb = _get_duckdb()
        self._conn = duckdb.connect(":memory:")
        self._register_views()
        return self._conn

    def _register_views(self) -> None:
        """Register a DuckDB view for each source's Parquet files."""
        conn = self._conn
        for source in self.config.sources:
            source_dir = get_source_dir(self.base_path, source.id)
            if source_dir.exists() and any(source_dir.glob("*.parquet")):
                parquet_glob = str(source_dir / "*.parquet")
                # Use safe identifier quoting
                view_name = source.id.replace("-", "_").replace(".", "_")
                conn.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_parquet('{parquet_glob}')"
                )

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> DatasetAnalyzer:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def query(self, sql: str) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as list of dicts.

        Args:
            sql: SQL query string.

        Returns:
            List of result dicts.
        """
        conn = self._get_conn()
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def stats(self, source_id: str) -> list[dict[str, Any]]:
        """Get column statistics for a source.

        Returns min, max, avg, null count, distinct count per column.
        """
        view_name = source_id.replace("-", "_").replace(".", "_")
        conn = self._get_conn()

        # Get column names and types
        info = conn.execute(f"DESCRIBE {view_name}").fetchall()
        results: list[dict[str, Any]] = []

        for col_name, col_type, *_ in info:
            stat: dict[str, Any] = {
                "column": col_name,
                "type": col_type,
            }
            quoted = f'"{col_name}"'
            # Count nulls and total
            row = conn.execute(
                f"SELECT COUNT(*) as total, "
                f"COUNT({quoted}) as non_null, "
                f"COUNT(DISTINCT {quoted}) as distinct_count "
                f"FROM {view_name}"
            ).fetchone()
            if row:
                stat["total"] = row[0]
                stat["non_null"] = row[1]
                stat["null_count"] = row[0] - row[1]
                stat["distinct"] = row[2]

            # Numeric stats
            if col_type in ("INTEGER", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT"):
                num_row = conn.execute(
                    f"SELECT MIN({quoted}), MAX({quoted}), AVG({quoted}) "
                    f"FROM {view_name}"
                ).fetchone()
                if num_row:
                    stat["min"] = num_row[0]
                    stat["max"] = num_row[1]
                    stat["avg"] = round(num_row[2], 2) if num_row[2] is not None else None

            results.append(stat)

        return results

    def profile(self) -> list[dict[str, Any]]:
        """Profile all sources: record count, completeness, duplicates.

        Returns:
            List of dicts with source-level quality metrics.
        """
        results: list[dict[str, Any]] = []
        conn = self._get_conn()

        for source in self.config.sources:
            view_name = source.id.replace("-", "_").replace(".", "_")
            source_dir = get_source_dir(self.base_path, source.id)

            if not source_dir.exists() or not any(source_dir.glob("*.parquet")):
                results.append({
                    "source": source.id,
                    "status": "no data",
                    "records": 0,
                })
                continue

            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()
                total = row[0] if row else 0

                # Get columns
                info = conn.execute(f"DESCRIBE {view_name}").fetchall()
                col_names = [c[0] for c in info]

                # Completeness: fraction of non-null values
                if col_names:
                    non_null_exprs = [f'COUNT("{c}")' for c in col_names]
                    counts_row = conn.execute(
                        f"SELECT {', '.join(non_null_exprs)} FROM {view_name}"
                    ).fetchone()
                    if counts_row and total > 0:
                        completeness = sum(counts_row) / (total * len(col_names))
                    else:
                        completeness = 0.0
                else:
                    completeness = 0.0

                results.append({
                    "source": source.id,
                    "status": "ok",
                    "records": total,
                    "columns": len(col_names),
                    "completeness": round(completeness * 100, 1),
                })
            except Exception as e:
                results.append({
                    "source": source.id,
                    "status": f"error: {e}",
                    "records": 0,
                })

        return results

    def list_views(self) -> list[str]:
        """List all registered view names."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_type = 'VIEW'"
        ).fetchall()
        return [r[0] for r in rows]

    def interactive_shell(self) -> None:
        """Run an interactive SQL shell."""
        from rich.console import Console

        console = Console()
        conn = self._get_conn()
        views = self.list_views()

        console.print("[bold]Anysite Dataset SQL Shell[/bold]")
        console.print(f"Available views: {', '.join(views)}")
        console.print("Type 'exit' or 'quit' to leave.\n")

        while True:
            try:
                sql = input("anysite> ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nBye!")
                break

            if not sql:
                continue
            if sql.lower() in ("exit", "quit", "\\q"):
                break

            try:
                result = conn.execute(sql)
                if result.description:
                    columns = [desc[0] for desc in result.description]
                    rows = result.fetchall()
                    if rows:
                        from rich.table import Table

                        table = Table()
                        for col in columns:
                            table.add_column(col)
                        for row in rows:
                            table.add_row(*[str(v) for v in row])
                        console.print(table)
                    else:
                        console.print("[dim]Empty result set[/dim]")
                else:
                    console.print("[green]OK[/green]")
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
