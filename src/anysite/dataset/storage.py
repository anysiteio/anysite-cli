"""Parquet storage layer for dataset records."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def write_parquet(
    records: list[dict[str, Any]],
    path: Path,
) -> int:
    """Write records to a Parquet file.

    Args:
        records: List of dicts to write.
        path: Output file path.

    Returns:
        Number of records written.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not records:
        return 0

    # Normalize: flatten nested structures to JSON strings for non-scalar types
    normalized = _normalize_records(records)

    table = pa.Table.from_pylist(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return len(records)


def _normalize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize records for Parquet compatibility.

    Converts nested dicts/lists to JSON strings so that pyarrow
    can infer a consistent schema across heterogeneous records.
    """
    if not records:
        return records

    result = []
    for record in records:
        normalized: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, (dict, list)):
                normalized[key] = json.dumps(value, default=str)
            else:
                normalized[key] = value
        result.append(normalized)
    return result


def read_parquet(path: Path) -> list[dict[str, Any]]:
    """Read records from a Parquet file or directory of Parquet files.

    Args:
        path: Parquet file or directory containing .parquet files.

    Returns:
        List of dicts.
    """
    import pyarrow.parquet as pq

    if path.is_dir():
        files = sorted(path.glob("*.parquet"))
        if not files:
            return []
        tables = [pq.read_table(f) for f in files]
        import pyarrow as pa

        table = pa.concat_tables(tables)
    else:
        if not path.exists():
            return []
        table = pq.read_table(path)

    return table.to_pylist()


def get_source_dir(base_path: Path, source_id: str) -> Path:
    """Get the raw data directory for a source."""
    return base_path / "raw" / source_id


def get_parquet_path(base_path: Path, source_id: str, collected_date: date | None = None) -> Path:
    """Get the Parquet file path for a source on a given date."""
    if collected_date is None:
        collected_date = date.today()
    source_dir = get_source_dir(base_path, source_id)
    return source_dir / f"{collected_date.isoformat()}.parquet"


class MetadataStore:
    """Read/write metadata.json for dataset state tracking."""

    def __init__(self, base_path: Path) -> None:
        self.path = base_path / "metadata.json"

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)  # type: ignore[no-any-return]
        return {"sources": {}}

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def update_source(
        self,
        source_id: str,
        record_count: int,
        collected_date: date | None = None,
    ) -> None:
        """Update metadata for a collected source."""
        if collected_date is None:
            collected_date = date.today()

        data = self.load()
        sources = data.setdefault("sources", {})
        sources[source_id] = {
            "last_collected": collected_date.isoformat(),
            "record_count": record_count,
        }
        data["last_run"] = collected_date.isoformat()
        self.save(data)

    def get_source_info(self, source_id: str) -> dict[str, Any] | None:
        """Get metadata for a specific source."""
        data = self.load()
        return data.get("sources", {}).get(source_id)

    def get_all_sources(self) -> dict[str, Any]:
        """Get metadata for all sources."""
        data = self.load()
        return data.get("sources", {})

    def update_collected_inputs(
        self, source_id: str, inputs: list[str]
    ) -> None:
        """Append collected input values to metadata for dedup tracking."""
        data = self.load()
        sources = data.setdefault("sources", {})
        source_info = sources.setdefault(source_id, {})
        existing = set(source_info.get("collected_inputs", []))
        existing.update(str(v) for v in inputs)
        source_info["collected_inputs"] = sorted(existing)
        self.save(data)

    def get_collected_inputs(self, source_id: str) -> set[str]:
        """Get the set of already-collected input values for a source."""
        info = self.get_source_info(source_id)
        if info and "collected_inputs" in info:
            return set(info["collected_inputs"])
        return set()

    def reset_collected_inputs(self, source_id: str) -> None:
        """Clear collected input tracking for a source (forces re-collection)."""
        data = self.load()
        source_info = data.get("sources", {}).get(source_id, {})
        if "collected_inputs" in source_info:
            del source_info["collected_inputs"]
            self.save(data)
