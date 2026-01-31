"""Load dataset Parquet data into a relational database with FK linking."""

from __future__ import annotations

import json
from typing import Any

from anysite.dataset.models import DatasetConfig, DatasetSource
from anysite.dataset.storage import get_source_dir, read_parquet
from anysite.db.adapters.base import DatabaseAdapter
from anysite.db.schema.inference import infer_table_schema


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
        return row
    else:
        # All fields minus exclusions
        return {k: v for k, v in record.items() if k not in exclude}


class DatasetDbLoader:
    """Load dataset Parquet data into a relational database.

    Handles:
    - Schema inference from Parquet records
    - Auto-increment primary keys (``id`` column)
    - Foreign key linking via provenance ``_input_value`` column
    - Dot-notation field extraction for JSON columns
    - Topological loading order (parents before children)
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
    ) -> dict[str, int]:
        """Load all sources into the database in dependency order.

        Args:
            source_filter: Only load this source (and dependencies).
            drop_existing: Drop tables before creating.
            dry_run: Show plan without executing.

        Returns:
            Mapping of source_id to number of rows loaded.
        """
        sources = self.config.topological_sort()

        if source_filter:
            from anysite.dataset.collector import _filter_sources
            sources = _filter_sources(sources, source_filter, self.config)

        results: dict[str, int] = {}

        for source in sources:
            count = self._load_source(
                source,
                drop_existing=drop_existing,
                dry_run=dry_run,
            )
            results[source.id] = count

        return results

    def _load_source(
        self,
        source: DatasetSource,
        *,
        drop_existing: bool = False,
        dry_run: bool = False,
    ) -> int:
        """Load a single source into the database."""
        source_dir = get_source_dir(self.base_path, source.id)
        if not source_dir.exists() or not any(source_dir.glob("*.parquet")):
            return 0

        raw_records = read_parquet(source_dir)
        if not raw_records:
            return 0

        table_name = _table_name_for(source)

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

            # Add FK column if this is a dependent source
            if parent_source_id and parent_fk_col:
                input_val = record.get("_input_value")
                parent_map = self._value_to_id.get(parent_source_id, {})
                if input_val is not None and str(input_val) in parent_map:
                    row[parent_fk_col] = parent_map[str(input_val)]
                else:
                    row[parent_fk_col] = None

            rows.append(row)

        if dry_run:
            return len(rows)

        # Determine the lookup field for children to reference this source
        # This is the field that child dependencies extract from this source
        lookup_field = self._get_child_lookup_field(source)

        # Create table
        if drop_existing and self.adapter.table_exists(table_name):
            self.adapter.execute(f"DROP TABLE {table_name}")

        if not self.adapter.table_exists(table_name):
            schema = infer_table_schema(table_name, rows)
            sql_types = schema.to_sql_types(self._dialect)
            # Add auto-increment id column
            col_defs = {"id": self._auto_id_type()}
            col_defs.update(sql_types)
            self.adapter.create_table(table_name, col_defs, primary_key="id")

        # Insert rows one at a time to capture auto-increment IDs for FK mapping
        value_map: dict[str, int] = {}
        for i, row in enumerate(rows):
            self.adapter.insert_batch(table_name, [row])
            # Get the last inserted id
            last_id = self._get_last_id(table_name)

            # Build value→id map for child sources
            if lookup_field and last_id is not None:
                raw_record = raw_records[i]
                lookup_val = _extract_dot_value(raw_record, lookup_field)
                if lookup_val is None:
                    lookup_val = raw_record.get(lookup_field)
                if lookup_val is not None:
                    value_map[str(lookup_val)] = last_id

        if value_map:
            self._value_to_id[source.id] = value_map

        return len(rows)

    def _get_child_lookup_field(self, source: DatasetSource) -> str | None:
        """Find which field children use to reference this source."""
        for other in self.config.sources:
            if other.dependency and other.dependency.from_source == source.id:
                return other.dependency.field
        return None

    def _auto_id_type(self) -> str:
        """Get the auto-increment ID column type for the dialect."""
        if self._dialect == "postgres":
            return "SERIAL"
        return "INTEGER"

    def _get_last_id(self, table_name: str) -> int | None:
        """Get the last inserted auto-increment ID."""
        row = self.adapter.fetch_one(
            f"SELECT MAX(id) as last_id FROM {table_name}"
        )
        if row:
            return row.get("last_id")
        return None
