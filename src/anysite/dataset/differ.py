"""Compare two dataset snapshots to find added, removed, and changed records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from anysite.dataset.errors import DatasetError
from anysite.dataset.storage import get_source_dir


def _build_key_expr(key: str, all_columns: list[str]) -> tuple[str, str]:
    """Build a DuckDB key expression, supporting dot-notation for JSON fields.

    Returns:
        (key_expr, key_alias) — the SQL expression and a display alias.
        For simple keys: ('"field"', 'field')
        For dot-notation: ("json_extract_string(\"urn\", '$.value')", 'urn.value')
    """
    if "." not in key:
        if key not in all_columns:
            raise DatasetError(
                f"Key field '{key}' not found. "
                f"Available: {', '.join(all_columns)}"
            )
        return f'"{key}"', key

    root, rest = key.split(".", 1)
    if root not in all_columns:
        raise DatasetError(
            f"Root field '{root}' (from key '{key}') not found. "
            f"Available: {', '.join(all_columns)}"
        )
    return f"json_extract_string(\"{root}\", '$.{rest}')", key


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
    fields: list[str] | None = field(default=None)

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
            key: Field to match records by.  Supports dot-notation for
                JSON fields (e.g., ``urn.value``).
            from_date: Older snapshot date (default: second-to-last).
            to_date: Newer snapshot date (default: latest).
            fields: Only compare (and output) these fields (default: all).

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

            # Build key expression (supports dot-notation)
            key_expr, key_alias = _build_key_expr(key, all_columns)

            # Determine which fields to compare
            compare_fields = fields if fields else [
                c for c in all_columns if c != key and c != key.split(".")[0]
            ]
            # Filter to fields that actually exist
            compare_fields = [c for c in compare_fields if c in all_columns]

            # Determine output columns: if fields specified, restrict to key + fields
            if fields:
                output_columns = [key_alias] + [
                    f for f in fields if f in all_columns
                ]
            else:
                output_columns = None  # all columns

            # Added: in new but not in old
            added_records = self._query_added_removed(
                conn, "_new", "_old", key_expr, key_alias, all_columns, output_columns
            )

            # Removed: in old but not in new
            removed_records = self._query_added_removed(
                conn, "_old", "_new", key_expr, key_alias, all_columns, output_columns
            )

            # Changed: matching key, different values
            changed_records = self._find_changed(
                conn, key_expr, key_alias, compare_fields, all_columns, output_columns
            )

            # Count unchanged
            total_matched = conn.execute(
                f"SELECT COUNT(*) FROM _new n "
                f"JOIN _old o ON ({_requalify(key_expr, 'n')}) = ({_requalify(key_expr, 'o')})"
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
                fields=fields,
            )
        finally:
            conn.close()

    @staticmethod
    def _query_added_removed(
        conn: Any,
        present_view: str,
        absent_view: str,
        key_expr: str,
        key_alias: str,
        all_columns: list[str],
        output_columns: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Query records present in one view but not the other."""
        # Build SELECT list
        if output_columns:
            select_parts = []
            for col in output_columns:
                if col == key_alias and "." in col:
                    select_parts.append(f"{key_expr} AS \"{key_alias}\"")
                else:
                    select_parts.append(f'"{col}"')
            select_clause = ", ".join(select_parts)
        else:
            if "." in key_alias:
                select_clause = f"*, {key_expr} AS \"{key_alias}\""
            else:
                select_clause = "*"

        sql = (
            f"SELECT {select_clause} FROM {present_view} "
            f"WHERE ({key_expr}) NOT IN (SELECT ({key_expr}) FROM {absent_view})"
        )
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row, strict=False)) for row in rows]

    @staticmethod
    def _find_changed(
        conn: Any,
        key_expr: str,
        key_alias: str,
        compare_fields: list[str],
        all_columns: list[str],
        output_columns: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Find records that exist in both snapshots but have different values."""
        if not compare_fields:
            return []

        # Build WHERE clause: any compared field differs
        where_parts = []
        for col in compare_fields:
            qc = f'"{col}"'
            where_parts.append(f"n.{qc} IS DISTINCT FROM o.{qc}")
        where_clause = " OR ".join(where_parts)

        # Build JOIN condition
        join_key_n = _requalify(key_expr, "n")
        join_key_o = _requalify(key_expr, "o")
        join_cond = f"({join_key_n}) = ({join_key_o})"

        # Build SELECT: key + output fields + __old for compare fields
        if output_columns:
            # Restricted output
            select_parts = []
            for col in output_columns:
                if col == key_alias and "." in col:
                    select_parts.append(f"{_requalify(key_expr, 'n')} AS \"{key_alias}\"")
                else:
                    select_parts.append(f"n.\"{col}\"")
            for col in compare_fields:
                # Include __old for compare fields that are in output
                if col in [c for c in output_columns if c != key_alias]:
                    select_parts.append(f"o.\"{col}\" AS \"{col}__old\"")
        else:
            # Full output
            select_parts = []
            if "." in key_alias:
                select_parts.append(f"{_requalify(key_expr, 'n')} AS \"{key_alias}\"")
            else:
                select_parts.append(f"n.\"{key_alias}\"")
            for col in all_columns:
                if col == key_alias:
                    continue
                select_parts.append(f"n.\"{col}\"")
            for col in compare_fields:
                select_parts.append(f"o.\"{col}\" AS \"{col}__old\"")

        select_clause = ", ".join(select_parts)

        sql = (
            f"SELECT {select_clause} FROM _new n "
            f"JOIN _old o ON {join_cond} "
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
            # Fallback: DuckDB detected a change but Python comparison missed it
            if not changed_fields:
                changed_fields = list(compare_fields)
            record["_changed_fields"] = changed_fields

        return records


def _requalify(key_expr: str, prefix: str) -> str:
    """Requalify a key expression with a table alias prefix.

    For simple keys like '"field"', returns 'prefix."field"'.
    For json_extract_string("col", '$.path'), returns
    json_extract_string(prefix."col", '$.path').
    """
    if key_expr.startswith("json_extract_string("):
        # Replace the column reference inside json_extract_string
        inner = key_expr[len("json_extract_string("):]
        # inner looks like: "col", '$.path')
        col_end = inner.index(",")
        col = inner[:col_end].strip()
        rest = inner[col_end:]
        return f"json_extract_string({prefix}.{col}{rest}"
    return f"{prefix}.{key_expr}"


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
    # Handle complex types (dict, list) — compare via JSON serialization
    # to catch differences DuckDB sees but Python equality misses
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        try:
            return json.dumps(a, sort_keys=True, default=str) != json.dumps(
                b, sort_keys=True, default=str
            )
        except (TypeError, ValueError):
            pass
    return True


def format_diff_table(
    result: DiffResult,
    *,
    output_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Format a DiffResult into a flat list of dicts for table/json output.

    Each record gets a ``_diff`` column with value ``added``, ``removed``,
    or ``changed``.  For changed records in table mode, modified field
    values are formatted as ``old → new``.

    Args:
        result: The diff result.
        output_fields: If set, only include these fields (plus ``_diff`` and key).
    """
    allowed = _build_allowed_set(result.key, output_fields)
    rows: list[dict[str, Any]] = []

    for record in result.added:
        row = {"_diff": "added", **_filter_row(record, allowed)}
        rows.append(row)

    for record in result.removed:
        row = {"_diff": "removed", **_filter_row(record, allowed)}
        rows.append(row)

    for record in result.changed:
        row: dict[str, Any] = {"_diff": "changed"}
        changed_fields = record.get("_changed_fields", [])
        for k, v in record.items():
            if k == "_changed_fields":
                continue
            if k.endswith("__old"):
                continue
            if allowed and k not in allowed:
                continue
            # For changed fields, format as "old → new"
            if k in changed_fields:
                old_val = record.get(f"{k}__old")
                row[k] = f"{_format_val(old_val)} → {_format_val(v)}"
            else:
                row[k] = v
        rows.append(row)

    return rows


def format_diff_records(
    result: DiffResult,
    *,
    output_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Format a DiffResult for JSON/CSV output.

    Each record gets ``_diff`` column.  Changed records include both
    current values and ``field__old`` columns.

    Args:
        result: The diff result.
        output_fields: If set, only include these fields (plus ``_diff``, key, and ``__old``).
    """
    allowed = _build_allowed_set(result.key, output_fields)
    rows: list[dict[str, Any]] = []

    for record in result.added:
        rows.append({"_diff": "added", **_filter_row(record, allowed)})

    for record in result.removed:
        rows.append({"_diff": "removed", **_filter_row(record, allowed)})

    for record in result.changed:
        row: dict[str, Any] = {"_diff": "changed"}
        changed_fields = record.get("_changed_fields", [])
        row["_changed_fields"] = changed_fields
        for k, v in record.items():
            if k == "_changed_fields":
                continue
            if allowed and k not in allowed and not k.endswith("__old"):
                continue
            if k.endswith("__old") and allowed:
                base = k[: -len("__old")]
                if base not in allowed:
                    continue
            row[k] = v
        rows.append(row)

    return rows


def _build_allowed_set(key: str, output_fields: list[str] | None) -> set[str] | None:
    """Build the set of allowed field names for output filtering."""
    if not output_fields:
        return None
    allowed = set(output_fields)
    allowed.add(key)
    # Also add the root column for dot-notation keys
    if "." in key:
        allowed.add(key.split(".")[0])
    return allowed


def _filter_row(record: dict[str, Any], allowed: set[str] | None) -> dict[str, Any]:
    """Filter a record to only allowed fields."""
    if not allowed:
        return record
    return {k: v for k, v in record.items() if k in allowed}


def _format_val(v: Any) -> str:
    """Format a value for display, truncating long strings."""
    if v is None:
        return "null"
    s = str(v)
    if len(s) > 40:
        return s[:37] + "..."
    return s
