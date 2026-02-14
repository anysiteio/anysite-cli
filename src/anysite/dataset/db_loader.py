"""Load dataset Parquet data into a relational database with FK linking."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from anysite.dataset.models import DatasetConfig, DatasetSource
from anysite.dataset.storage import get_source_dir, read_parquet
from anysite.db.adapters.base import DatabaseAdapter
from anysite.db.schema.inference import infer_table_schema
from anysite.db.utils.sanitize import sanitize_identifier

logger = logging.getLogger(__name__)


@dataclass
class LoadResult:
    """Result of loading a single source into the database."""

    ops: int  # number of SQL operations performed
    row_count: int  # actual rows in table after load


def _get_dialect(adapter: DatabaseAdapter) -> str:
    """Extract dialect string from adapter server info."""
    info = adapter.get_server_info()
    return info.get("type", "sqlite")


def _extract_dot_value(record: dict[str, Any], dot_path: str) -> Any:
    """Extract a value from a record using dot notation.

    Handles JSON strings stored in Parquet: if a field value is a JSON
    string, it is parsed and the remainder of the dot path traversed.
    """
    parts = dot_path.split(".")
    current: Any = record

    for part in parts:
        if isinstance(current, str):
            try:
                current = json.loads(current)
            except (json.JSONDecodeError, ValueError):
                return None

        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None

        if current is None:
            return None

    return current


def _apply_db_load_filter(
    records: list[dict[str, Any]],
    filter_expr: str,
) -> list[dict[str, Any]]:
    """Apply a db_load.filter expression to records.

    Uses JSON-string-aware dot access via ``_extract_dot_value`` so that
    filters work on nested fields stored as JSON strings in Parquet.
    """
    from anysite.dataset.transformer import parse_filter

    pred = parse_filter(filter_expr)
    if pred is None:
        return records

    # Build a JSON-aware wrapper: pre-parse JSON strings in dot-notation fields
    # so the filter predicate can traverse them.
    def _json_aware_pred(record: dict[str, Any]) -> bool:
        # For dot-notation fields in the filter, _get_dot_value in transformer.py
        # doesn't parse JSON strings. We pre-resolve them by expanding JSON-string
        # top-level fields into dicts.
        expanded = {}
        for k, v in record.items():
            if isinstance(v, str) and v.startswith("{"):
                try:
                    expanded[k] = json.loads(v)
                except (json.JSONDecodeError, ValueError):
                    expanded[k] = v
            else:
                expanded[k] = v
        return pred(expanded)

    return [r for r in records if _json_aware_pred(r)]


def _table_name_for(source: DatasetSource) -> str:
    """Get the DB table name for a source."""
    if source.db_load and source.db_load.table:
        return source.db_load.table
    return source.id.replace("-", "_").replace(".", "_")


def _filter_record(
    record: dict[str, Any],
    source: DatasetSource,
) -> dict[str, Any]:
    """Filter and transform a record based on db_load config.

    Applies field selection/exclusion and dot-notation extraction.
    """
    db_load = source.db_load
    exclude = set(db_load.exclude) if db_load else {"_input_value", "_parent_source"}

    if db_load and db_load.fields:
        # Explicit field list — extract each field
        row: dict[str, Any] = {}
        for field_spec in db_load.fields:
            # Parse "source_field AS alias" syntax
            alias = None
            upper = field_spec.upper()
            as_idx = upper.find(" AS ")
            if as_idx != -1:
                alias = field_spec[as_idx + 4:].strip()
                field_spec = field_spec[:as_idx].strip()

            col_name = alias or field_spec.replace(".", "_")

            if "." in field_spec:
                row[col_name] = _extract_dot_value(record, field_spec)
            else:
                row[col_name] = record.get(field_spec)

        # Auto-include key field if configured but not already in fields
        if db_load.key:
            existing_sources = set()
            for fs in db_load.fields:
                upper_fs = fs.upper()
                idx = upper_fs.find(" AS ")
                existing_sources.add(fs[:idx].strip() if idx != -1 else fs.strip())
            if db_load.key not in existing_sources:
                key_col = db_load.key.replace(".", "_")
                if "." in db_load.key:
                    row[key_col] = _extract_dot_value(record, db_load.key)
                else:
                    row[key_col] = record.get(db_load.key)

        return row
    else:
        # All fields minus exclusions
        return {k: v for k, v in record.items() if k not in exclude}


def _get_latest_parquet(base_path: Path, source_id: str) -> Path | None:
    """Return the path to the most recent snapshot for a source."""
    source_dir = get_source_dir(base_path, source_id)
    if not source_dir.exists():
        return None
    files = sorted(source_dir.glob("*.parquet"))
    return files[-1] if files else None


def _get_snapshot_for_date(base_path: Path, source_id: str, d: date) -> Path | None:
    """Return the parquet path for a specific snapshot date."""
    source_dir = get_source_dir(base_path, source_id)
    path = source_dir / f"{d.isoformat()}.parquet"
    return path if path.exists() else None


class DatasetDbLoader:
    """Load dataset Parquet data into a relational database.

    Supports diff-based incremental sync when ``db_load.key`` is configured:
    compares the two most recent snapshots and applies INSERT/DELETE/UPDATE
    to keep the database in sync.

    Falls back to full INSERT of the latest snapshot when no key is set
    or when the table doesn't exist yet.
    """

    def __init__(
        self,
        config: DatasetConfig,
        adapter: DatabaseAdapter,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.base_path = config.storage_path()
        self._dialect = _get_dialect(adapter)
        # Maps source_id -> {input_value -> db_id} for FK linking
        self._value_to_id: dict[str, dict[str, int]] = {}

    def load_all(
        self,
        *,
        source_filter: str | None = None,
        drop_existing: bool = False,
        dry_run: bool = False,
        snapshot: str | None = None,
    ) -> dict[str, LoadResult]:
        """Load all sources into the database in dependency order.

        Args:
            source_filter: Only load this source (and dependencies).
            drop_existing: Drop tables before creating, then full INSERT latest.
            dry_run: Show plan without executing.
            snapshot: Load a specific snapshot date (YYYY-MM-DD).

        Returns:
            Mapping of source_id to LoadResult with ops count and row count.
        """
        sources = self.config.topological_sort()

        if source_filter:
            from anysite.dataset.collector import _filter_sources
            sources = _filter_sources(sources, source_filter, self.config)

        results: dict[str, LoadResult] = {}

        for source in sources:
            result = self._load_source(
                source,
                drop_existing=drop_existing,
                dry_run=dry_run,
                snapshot=snapshot,
            )
            results[source.id] = result

        return results

    def _load_source(
        self,
        source: DatasetSource,
        *,
        drop_existing: bool = False,
        dry_run: bool = False,
        snapshot: str | None = None,
    ) -> LoadResult:
        """Load a single source into the database.

        Strategy:
        1. ``drop_existing``: drop table → full INSERT of latest snapshot
        2. ``snapshot``: full INSERT of that specific snapshot
        3. Table doesn't exist: full INSERT of latest snapshot
        4. Table exists + ``db_load.key`` set + ≥2 snapshots: diff-based sync
        5. Fallback: full INSERT of latest snapshot
        """
        table_name = _table_name_for(source)

        # Handle drop_existing
        if drop_existing and self.adapter.table_exists(table_name):
            self.adapter.execute(f"DROP TABLE {table_name}")

        # Determine which parquet to load
        if snapshot:
            snapshot_date = date.fromisoformat(snapshot)
            parquet_path = _get_snapshot_for_date(self.base_path, source.id, snapshot_date)
            if parquet_path is None:
                return LoadResult(ops=0, row_count=0)
            return self._full_insert(source, table_name, parquet_path, dry_run=dry_run)

        # Check if we can do diff-based sync
        diff_key = source.db_load.key if source.db_load else None
        table_exists = self.adapter.table_exists(table_name)

        if diff_key and table_exists and not drop_existing:
            from anysite.dataset.differ import DatasetDiffer
            differ = DatasetDiffer(self.base_path)
            dates = differ.available_dates(source.id)

            if len(dates) >= 2:
                return self._diff_sync(
                    source, table_name, diff_key, differ, dates, dry_run=dry_run
                )

        # Fallback: full INSERT of latest snapshot
        # If table already exists and no key for diff, truncate first to avoid duplicates
        if table_exists and not diff_key and not dry_run:
            if self._dialect == "clickhouse":
                self.adapter.execute(f"TRUNCATE TABLE {table_name}")
            else:
                self.adapter.execute(f"DELETE FROM {table_name}")
            logger.info("Truncated %s (no db_load.key for incremental sync)", table_name)

        latest = _get_latest_parquet(self.base_path, source.id)
        if latest is None:
            return LoadResult(ops=0, row_count=0)
        return self._full_insert(source, table_name, latest, dry_run=dry_run)

    def _full_insert(
        self,
        source: DatasetSource,
        table_name: str,
        parquet_path: Path,
        *,
        dry_run: bool = False,
    ) -> LoadResult:
        """Full INSERT: read parquet, transform, create table if needed, insert all rows."""
        raw_records = read_parquet(parquet_path)
        if not raw_records:
            return LoadResult(ops=0, row_count=0)

        # Apply db_load.filter to exclude records before loading
        if source.db_load and source.db_load.filter:
            raw_records = _apply_db_load_filter(raw_records, source.db_load.filter)
            if not raw_records:
                return LoadResult(ops=0, row_count=0)

        # Determine parent info for FK linking
        parent_source_id = None
        parent_fk_col = None
        if source.dependency:
            parent_source_id = source.dependency.from_source
            parent_fk_col = f"{parent_source_id.replace('-', '_').replace('.', '_')}_id"

        # Transform records
        rows: list[dict[str, Any]] = []
        for record in raw_records:
            row = _filter_record(record, source)

            if parent_source_id and parent_fk_col:
                input_val = record.get("_input_value")
                parent_map = self._value_to_id.get(parent_source_id, {})
                if input_val is not None and str(input_val) in parent_map:
                    row[parent_fk_col] = parent_map[str(input_val)]
                else:
                    row[parent_fk_col] = None

            rows.append(row)

        if dry_run:
            return LoadResult(ops=len(rows), row_count=len(rows))

        # Determine the lookup field for children to reference this source
        lookup_field = self._get_child_lookup_field(source)

        # Create table if needed
        if not self.adapter.table_exists(table_name):
            schema = infer_table_schema(table_name, rows)
            sql_types = schema.to_sql_types(self._dialect)
            col_defs = {"id": self._auto_id_type()}
            col_defs.update(sql_types)
            self.adapter.create_table(table_name, col_defs, primary_key="id")

        # For ClickHouse, pre-assign IDs (no auto-increment)
        if self._dialect == "clickhouse":
            start_id = (self._get_last_id(table_name) or 0) + 1
            for i, row in enumerate(rows):
                row["id"] = start_id + i

        # Insert rows one at a time to capture auto-increment IDs for FK mapping
        value_map: dict[str, int] = {}
        for i, row in enumerate(rows):
            self.adapter.insert_batch(table_name, [row])
            last_id = self._get_last_id(table_name)

            if lookup_field and last_id is not None:
                raw_record = raw_records[i]
                lookup_val = _extract_dot_value(raw_record, lookup_field)
                if lookup_val is None:
                    lookup_val = raw_record.get(lookup_field)
                if lookup_val is not None:
                    value_map[str(lookup_val)] = last_id

        if value_map:
            self._value_to_id[source.id] = value_map

        row_count = self._get_row_count(table_name)
        return LoadResult(ops=len(rows), row_count=row_count)

    def _diff_sync(
        self,
        source: DatasetSource,
        table_name: str,
        diff_key: str,
        differ: Any,
        dates: list[date],
        *,
        dry_run: bool = False,
    ) -> LoadResult:
        """Diff-based incremental sync: compare two most recent snapshots, apply delta."""
        result = differ.diff(source.id, diff_key)

        # Apply db_load.filter to added/changed records in diff
        if source.db_load and source.db_load.filter:
            result.added = _apply_db_load_filter(result.added, source.db_load.filter)
            result.changed = _apply_db_load_filter(result.changed, source.db_load.filter)

        total = 0
        sync_mode = source.db_load.sync if source.db_load else "full"

        if dry_run:
            count = len(result.added) + len(result.changed)
            if sync_mode == "full":
                count += len(result.removed)
            return LoadResult(ops=count, row_count=count)

        # Extract key value from a record (handles dot-notation)
        def _get_key_val(record: dict[str, Any]) -> Any:
            if "." in diff_key:
                return _extract_dot_value(record, diff_key)
            return record.get(diff_key)

        # Build field mapping for db_load.fields filtering
        field_mapping = self._get_db_field_mapping(source)

        # Determine the DB column name for the key
        if field_mapping and diff_key in field_mapping:
            db_key_col = field_mapping[diff_key]
        else:
            db_key_col = diff_key.replace(".", "_")

        # INSERT added records
        if result.added:
            for record in result.added:
                row = _filter_record(record, source)
                self.adapter.insert_batch(table_name, [row])
                total += 1

        # DELETE removed records (skipped in append mode)
        ph = self._placeholder()
        if result.removed and sync_mode == "full":
            safe_col = sanitize_identifier(db_key_col)
            for record in result.removed:
                key_val = _get_key_val(record)
                if key_val is not None:
                    if self._dialect == "clickhouse":
                        self.adapter.execute(
                            f"ALTER TABLE {table_name} DELETE WHERE {safe_col} = {ph}",
                            (str(key_val),),
                        )
                    else:
                        self.adapter.execute(
                            f"DELETE FROM {table_name} WHERE {safe_col} = {ph}",
                            (str(key_val),),
                        )
                    total += 1

        # UPDATE changed records
        if result.changed:
            safe_col = sanitize_identifier(db_key_col)
            for record in result.changed:
                key_val = _get_key_val(record)
                if key_val is None:
                    continue
                changed_fields = record.get("_changed_fields", [])
                if not changed_fields:
                    continue

                # Build SET clause — only include fields that exist in the DB
                set_parts = []
                params: list[Any] = []
                for field_name in changed_fields:
                    if field_mapping is not None:
                        if field_name not in field_mapping:
                            continue
                        db_col = field_mapping[field_name]
                    else:
                        db_col = field_name

                    if "." in field_name:
                        new_val = _extract_dot_value(record, field_name)
                    else:
                        new_val = record.get(field_name)

                    safe_field = sanitize_identifier(db_col)
                    set_parts.append(f"{safe_field} = {ph}")
                    params.append(new_val)

                if not set_parts:
                    continue

                params.append(str(key_val))
                if self._dialect == "clickhouse":
                    sql = (
                        f"ALTER TABLE {table_name} "
                        f"UPDATE {', '.join(set_parts)} "
                        f"WHERE {safe_col} = {ph}"
                    )
                else:
                    sql = (
                        f"UPDATE {table_name} "
                        f"SET {', '.join(set_parts)} "
                        f"WHERE {safe_col} = {ph}"
                    )
                self.adapter.execute(sql, tuple(params))
                total += 1

        row_count = self._get_row_count(table_name)
        return LoadResult(ops=total, row_count=row_count)

    def _get_child_lookup_field(self, source: DatasetSource) -> str | None:
        """Find which field children use to reference this source."""
        for other in self.config.sources:
            if other.dependency and other.dependency.from_source == source.id:
                return other.dependency.field
        return None

    def _get_db_field_mapping(self, source: DatasetSource) -> dict[str, str] | None:
        """Build mapping of parquet_field -> db_column from db_load.fields.

        Returns None if no explicit fields configured (all fields allowed).
        """
        db_load = source.db_load
        if not db_load or not db_load.fields:
            return None

        mapping: dict[str, str] = {}
        for field_spec in db_load.fields:
            alias = None
            upper = field_spec.upper()
            as_idx = upper.find(" AS ")
            if as_idx != -1:
                alias = field_spec[as_idx + 4:].strip()
                source_field = field_spec[:as_idx].strip()
            else:
                source_field = field_spec

            col_name = alias or source_field.replace(".", "_")
            mapping[source_field] = col_name

        # Auto-include key if not in explicit fields
        if db_load.key and db_load.key not in mapping:
            mapping[db_load.key] = db_load.key.replace(".", "_")

        return mapping

    def _placeholder(self) -> str:
        """Get the parameter placeholder for the dialect."""
        if self._dialect in ("postgres", "clickhouse"):
            return "%s"
        return "?"

    def _auto_id_type(self) -> str:
        """Get the auto-increment ID column type for the dialect."""
        if self._dialect == "postgres":
            return "SERIAL"
        if self._dialect == "clickhouse":
            return "Int64"
        return "INTEGER"

    def _get_row_count(self, table_name: str) -> int:
        """Get the current row count in a table."""
        row = self.adapter.fetch_one(
            f"SELECT COUNT(*) as c FROM {table_name}"
        )
        return row["c"] if row else 0

    def _get_last_id(self, table_name: str) -> int | None:
        """Get the last inserted auto-increment ID."""
        row = self.adapter.fetch_one(
            f"SELECT MAX(id) as last_id FROM {table_name}"
        )
        if row:
            return row.get("last_id")
        return None
