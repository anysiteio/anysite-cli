"""Compare two dataset snapshots to find added, removed, and changed records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from anysite.dataset.errors import DatasetError
from anysite.dataset.storage import get_source_dir


@dataclass
class DiffResult:
    """Result of comparing two dataset snapshots."""

    source_id: str
    from_date: date
    to_date: date
    key: str
    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    unchanged_count: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


class DatasetDiffer:
    """Compare two Parquet snapshots for a dataset source."""

    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path

    def available_dates(self, source_id: str) -> list[date]:
        """List available snapshot dates for a source, sorted ascending."""
        source_dir = get_source_dir(self.base_path, source_id)
        if not source_dir.exists():
            return []

        dates: list[date] = []
        for f in sorted(source_dir.glob("*.parquet")):
            try:
                dates.append(date.fromisoformat(f.stem))
            except ValueError:
                continue
        return dates

    def diff(
        self,
        source_id: str,
        key: str,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        fields: list[str] | None = None,
    ) -> DiffResult:
        """Compare two snapshots using DuckDB.

        Args:
            source_id: Source to compare.
            key: Field to match records by (e.g., ``_input_value``, ``urn``).
            from_date: Older snapshot date (default: second-to-last).
            to_date: Newer snapshot date (default: latest).
            fields: Only compare these fields (default: all).

        Returns:
            DiffResult with added, removed, changed lists.
        """
        from_date, to_date = self._resolve_dates(source_id, from_date, to_date)
        source_dir = get_source_dir(self.base_path, source_id)
        old_path = source_dir / f"{from_date.isoformat()}.parquet"
        new_path = source_dir / f"{to_date.isoformat()}.parquet"

        if not old_path.exists():
            raise DatasetError(
                f"No snapshot for {source_id} on {from_date.isoformat()}"
            )
        if not new_path.exists():
            raise DatasetError(
                f"No snapshot for {source_id} on {to_date.isoformat()}"
            )

        return self._diff_with_duckdb(
            source_id, key, old_path, new_path, from_date, to_date, fields
        )

    def _resolve_dates(
        self,
        source_id: str,
        from_date: date | None,
        to_date: date | None,
    ) -> tuple[date, date]:
        """Resolve from/to dates, defaulting to two most recent snapshots."""
        if from_date and to_date:
            return from_date, to_date

        dates = self.available_dates(source_id)
        if len(dates) < 2:
            raise DatasetError(
                f"Need at least 2 snapshots to diff, "
                f"found {len(dates)} for {source_id}"
            )

        if to_date and not from_date:
            # Find the date just before to_date
            earlier = [d for d in dates if d < to_date]
            if not earlier:
                raise DatasetError(
                    f"No snapshot before {to_date.isoformat()} for {source_id}"
                )
            return earlier[-1], to_date

        if from_date and not to_date:
            # Find the date just after from_date
            later = [d for d in dates if d > from_date]
            if not later:
                raise DatasetError(
                    f"No snapshot after {from_date.isoformat()} for {source_id}"
                )
            return from_date, later[0]

        # Both None — use two most recent
        return dates[-2], dates[-1]

    def _diff_with_duckdb(
        self,
        source_id: str,
        key: str,
        old_path: Path,
        new_path: Path,
        from_date: date,
        to_date: date,
        fields: list[str] | None,
    ) -> DiffResult:
        """Run diff queries using DuckDB."""
        import duckdb

        conn = duckdb.connect(":memory:")
        try:
            conn.execute(
                f"CREATE VIEW _old AS SELECT * FROM read_parquet('{old_path}')"
            )
            conn.execute(
                f"CREATE VIEW _new AS SELECT * FROM read_parquet('{new_path}')"
            )

            # Get all column names from the new snapshot
            info = conn.execute("DESCRIBE _new").fetchall()
            all_columns = [col[0] for col in info]

            if key not in all_columns:
                raise DatasetError(
                    f"Key field '{key}' not found in {source_id}. "
                    f"Available: {', '.join(all_columns)}"
                )

            # Determine which fields to compare
            compare_fields = fields if fields else [
                c for c in all_columns if c != key
            ]
            # Filter to fields that actually exist
            compare_fields = [c for c in compare_fields if c in all_columns]

            quoted_key = f'"{key}"'

            # Added: in new but not in old
            added = conn.execute(
                f"SELECT * FROM _new "
                f"WHERE {quoted_key} NOT IN (SELECT {quoted_key} FROM _old)"
            ).fetchall()
            added_cols = [d[0] for d in conn.execute(
                "DESCRIBE _new"
            ).fetchall()]
            added_records = [dict(zip(added_cols, row, strict=False)) for row in added]

            # Removed: in old but not in new
            removed = conn.execute(
                f"SELECT * FROM _old "
                f"WHERE {quoted_key} NOT IN (SELECT {quoted_key} FROM _new)"
            ).fetchall()
            removed_cols = [d[0] for d in conn.execute(
                "DESCRIBE _old"
            ).fetchall()]
            removed_records = [dict(zip(removed_cols, row, strict=False)) for row in removed]

            # Changed: matching key, different values
            changed_records = self._find_changed(
                conn, key, compare_fields, all_columns
            )

            # Count unchanged
            total_matched = conn.execute(
                f"SELECT COUNT(*) FROM _new n "
                f"JOIN _old o ON n.{quoted_key} = o.{quoted_key}"
            ).fetchone()
            matched_count = total_matched[0] if total_matched else 0
            unchanged_count = matched_count - len(changed_records)

            return DiffResult(
                source_id=source_id,
                from_date=from_date,
                to_date=to_date,
                key=key,
                added=added_records,
                removed=removed_records,
                changed=changed_records,
                unchanged_count=unchanged_count,
            )
        finally:
            conn.close()

    def _find_changed(
        self,
        conn: Any,
        key: str,
        compare_fields: list[str],
        all_columns: list[str],
    ) -> list[dict[str, Any]]:
        """Find records that exist in both snapshots but have different values."""
        if not compare_fields:
            return []

        quoted_key = f'"{key}"'

        # Build WHERE clause: any compared field differs
        where_parts = []
        for col in compare_fields:
            qc = f'"{col}"'
            where_parts.append(f"n.{qc} IS DISTINCT FROM o.{qc}")
        where_clause = " OR ".join(where_parts)

        # Select new values + old values for compared fields
        select_parts = [f"n.{quoted_key}"]
        for col in all_columns:
            if col != key:
                qc = f'"{col}"'
                select_parts.append(f"n.{qc}")
        for col in compare_fields:
            qc = f'"{col}"'
            select_parts.append(f"o.{qc} AS \"{col}__old\"")

        select_clause = ", ".join(select_parts)

        sql = (
            f"SELECT {select_clause} FROM _new n "
            f"JOIN _old o ON n.{quoted_key} = o.{quoted_key} "
            f"WHERE {where_clause}"
        )

        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        records = [dict(zip(columns, row, strict=False)) for row in rows]

        # Add _changed_fields metadata to each record
        for record in records:
            changed_fields = []
            for col in compare_fields:
                old_key = f"{col}__old"
                new_val = record.get(col)
                old_val = record.get(old_key)
                if _values_differ(new_val, old_val):
                    changed_fields.append(col)
            record["_changed_fields"] = changed_fields

        return records


def _values_differ(a: Any, b: Any) -> bool:
    """Compare two values, treating JSON strings as equivalent to their parsed form."""
    if a == b:
        return False
    # Handle JSON string comparison
    if isinstance(a, str) and isinstance(b, str):
        try:
            return json.loads(a) != json.loads(b)
        except (json.JSONDecodeError, ValueError):
            pass
    return True


def format_diff_table(result: DiffResult) -> list[dict[str, Any]]:
    """Format a DiffResult into a flat list of dicts for table/json output.

    Each record gets a ``_diff`` column with value ``added``, ``removed``,
    or ``changed``.  For changed records in table mode, modified field
    values are formatted as ``old → new``.
    """
    rows: list[dict[str, Any]] = []

    for record in result.added:
        row = {"_diff": "added", **record}
        rows.append(row)

    for record in result.removed:
        row = {"_diff": "removed", **record}
        rows.append(row)

    for record in result.changed:
        row: dict[str, Any] = {"_diff": "changed"}
        changed_fields = record.get("_changed_fields", [])
        for k, v in record.items():
            if k == "_changed_fields":
                continue
            if k.endswith("__old"):
                continue
            # For changed fields, format as "old → new"
            if k in changed_fields:
                old_val = record.get(f"{k}__old")
                row[k] = f"{_format_val(old_val)} → {_format_val(v)}"
            else:
                row[k] = v
        rows.append(row)

    return rows


def format_diff_records(result: DiffResult) -> list[dict[str, Any]]:
    """Format a DiffResult for JSON/CSV output.

    Each record gets ``_diff`` column.  Changed records include both
    current values and ``field__old`` columns.
    """
    rows: list[dict[str, Any]] = []

    for record in result.added:
        rows.append({"_diff": "added", **record})

    for record in result.removed:
        rows.append({"_diff": "removed", **record})

    for record in result.changed:
        row = {"_diff": "changed"}
        for k, v in record.items():
            if k == "_changed_fields":
                continue
            row[k] = v
        rows.append(row)

    return rows


def _format_val(v: Any) -> str:
    """Format a value for display, truncating long strings."""
    if v is None:
        return "null"
    s = str(v)
    if len(s) > 40:
        return s[:37] + "..."
    return s
