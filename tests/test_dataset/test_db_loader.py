"""Tests for dataset DB loader with SQLite in-memory adapter."""

import json

import pytest

from anysite.dataset.db_loader import DatasetDbLoader, _extract_dot_value, _filter_record
from anysite.dataset.models import (
    DatasetConfig,
    DatasetSource,
    DbLoadConfig,
    SourceDependency,
    StorageConfig,
)
from anysite.dataset.storage import get_source_dir, write_parquet
from anysite.db.adapters.sqlite import SQLiteAdapter
from anysite.db.config import ConnectionConfig, DatabaseType


def _sqlite_adapter():
    """Create an in-memory SQLite adapter."""
    config = ConnectionConfig(name="test", type=DatabaseType.SQLITE, path=":memory:")
    return SQLiteAdapter(config)


def _make_config(tmp_path, sources, storage_path=None):
    """Create a DatasetConfig with Parquet data on disk."""
    data_path = storage_path or (tmp_path / "data")
    return DatasetConfig(
        name="test",
        sources=sources,
        storage=StorageConfig(path=str(data_path)),
    )


class TestExtractDotValue:
    def test_simple_field(self):
        assert _extract_dot_value({"name": "Alice"}, "name") == "Alice"

    def test_nested_json_string(self):
        record = {"meta": json.dumps({"type": "user", "id": 42})}
        assert _extract_dot_value(record, "meta.type") == "user"
        assert _extract_dot_value(record, "meta.id") == 42

    def test_missing_field(self):
        assert _extract_dot_value({"name": "Alice"}, "age") is None

    def test_deep_nesting(self):
        record = {"data": json.dumps({"a": {"b": "deep"}})}
        assert _extract_dot_value(record, "data.a.b") == "deep"


class TestFilterRecord:
    def test_excludes_provenance_by_default(self):
        source = DatasetSource(id="test", endpoint="/api/test")
        record = {"name": "Alice", "_input_value": "x", "_parent_source": "p", "age": 30}
        result = _filter_record(record, source)
        assert result == {"name": "Alice", "age": 30}

    def test_explicit_fields(self):
        source = DatasetSource(
            id="test", endpoint="/api/test",
            db_load=DbLoadConfig(fields=["name", "age"]),
        )
        record = {"name": "Alice", "age": 30, "city": "SF"}
        result = _filter_record(record, source)
        assert result == {"name": "Alice", "age": 30}

    def test_dot_notation_fields(self):
        source = DatasetSource(
            id="test", endpoint="/api/test",
            db_load=DbLoadConfig(
                fields=["name", "meta.type AS role"],
            ),
        )
        record = {"name": "Alice", "meta": json.dumps({"type": "admin"})}
        result = _filter_record(record, source)
        assert result == {"name": "Alice", "role": "admin"}


class TestLoadSingleSource:
    def test_creates_table_and_inserts(self, tmp_path):
        sources = [DatasetSource(id="profiles", endpoint="/api/profiles")]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "profiles")
        write_parquet(
            [
                {"name": "Alice", "age": 30},
                {"name": "Bob", "age": 25},
            ],
            source_dir / "2026-01-01.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            results = loader.load_all()

            assert results["profiles"] == 2
            assert adapter.table_exists("profiles")

            rows = adapter.fetch_all("SELECT * FROM profiles ORDER BY id")
            assert len(rows) == 2
            assert rows[0]["name"] == "Alice"
            assert rows[1]["name"] == "Bob"
            # Auto-increment id column
            assert rows[0]["id"] == 1
            assert rows[1]["id"] == 2

    def test_schema_inferred_correctly(self, tmp_path):
        sources = [DatasetSource(id="items", endpoint="/api/items")]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet(
            [{"count": 42, "active": True, "label": "test"}],
            source_dir / "2026-01-01.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            loader.load_all()

            schema = adapter.get_table_schema("items")
            col_names = [c["name"] for c in schema]
            assert "id" in col_names
            assert "count" in col_names
            assert "active" in col_names
            assert "label" in col_names


class TestForeignKeyLinking:
    def test_parent_child_fk(self, tmp_path):
        """Child records get correct FK to parent via _input_value."""
        sources = [
            DatasetSource(id="companies", endpoint="/api/companies"),
            DatasetSource(
                id="employees",
                endpoint="/api/employees",
                dependency=SourceDependency(from_source="companies", field="urn"),
                input_key="company_urn",
            ),
        ]
        config = _make_config(tmp_path, sources)

        # Write parent data
        companies_dir = get_source_dir(tmp_path / "data", "companies")
        write_parquet(
            [
                {"urn": "c1", "name": "Acme"},
                {"urn": "c2", "name": "Globex"},
            ],
            companies_dir / "2026-01-01.parquet",
        )

        # Write child data with provenance
        employees_dir = get_source_dir(tmp_path / "data", "employees")
        write_parquet(
            [
                {"name": "Alice", "_input_value": "c1", "_parent_source": "companies"},
                {"name": "Bob", "_input_value": "c1", "_parent_source": "companies"},
                {"name": "Carol", "_input_value": "c2", "_parent_source": "companies"},
            ],
            employees_dir / "2026-01-01.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            results = loader.load_all()

            assert results["companies"] == 2
            assert results["employees"] == 3

            # Verify FK values
            employees = adapter.fetch_all(
                "SELECT name, companies_id FROM employees ORDER BY name"
            )
            # Alice and Bob → company c1 (id=1), Carol → company c2 (id=2)
            assert employees[0]["name"] == "Alice"
            assert employees[0]["companies_id"] == 1
            assert employees[1]["name"] == "Bob"
            assert employees[1]["companies_id"] == 1
            assert employees[2]["name"] == "Carol"
            assert employees[2]["companies_id"] == 2

    def test_no_provenance_fk_is_null(self, tmp_path):
        """Records without _input_value get NULL FK."""
        sources = [
            DatasetSource(id="parent", endpoint="/api/parent"),
            DatasetSource(
                id="child",
                endpoint="/api/child",
                dependency=SourceDependency(from_source="parent", field="key"),
                input_key="parent_key",
            ),
        ]
        config = _make_config(tmp_path, sources)

        parent_dir = get_source_dir(tmp_path / "data", "parent")
        write_parquet([{"key": "k1", "name": "P1"}], parent_dir / "2026-01-01.parquet")

        child_dir = get_source_dir(tmp_path / "data", "child")
        # No _input_value column — old data before provenance tracking
        write_parquet(
            [{"name": "C1", "value": 10}],
            child_dir / "2026-01-01.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            loader.load_all()

            rows = adapter.fetch_all("SELECT * FROM child")
            assert len(rows) == 1
            assert rows[0]["parent_id"] is None


class TestDbLoadConfig:
    def test_field_selection(self, tmp_path):
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(fields=["name", "score"]),
            ),
        ]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet(
            [{"name": "A", "score": 95, "extra": "ignored"}],
            source_dir / "2026-01-01.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            loader.load_all()

            rows = adapter.fetch_all("SELECT * FROM items")
            assert "name" in rows[0]
            assert "score" in rows[0]
            assert "extra" not in rows[0]

    def test_dot_notation_extraction(self, tmp_path):
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(
                    fields=["name", "meta.type AS role", "meta.id AS uid"],
                ),
            ),
        ]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet(
            [
                {"name": "Alice", "meta": json.dumps({"type": "admin", "id": 42})},
                {"name": "Bob", "meta": json.dumps({"type": "user", "id": 99})},
            ],
            source_dir / "2026-01-01.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            loader.load_all()

            rows = adapter.fetch_all("SELECT * FROM items ORDER BY id")
            assert rows[0]["role"] == "admin"
            assert rows[0]["uid"] == 42
            assert rows[1]["role"] == "user"

    def test_custom_table_name(self, tmp_path):
        sources = [
            DatasetSource(
                id="linkedin-profiles", endpoint="/api/profiles",
                db_load=DbLoadConfig(table="people"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "linkedin-profiles")
        write_parquet([{"name": "Alice"}], source_dir / "2026-01-01.parquet")

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            loader.load_all()

            assert adapter.table_exists("people")
            assert not adapter.table_exists("linkedin_profiles")


class TestDryRun:
    def test_no_tables_created(self, tmp_path):
        sources = [DatasetSource(id="items", endpoint="/api/items")]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet([{"name": "A"}], source_dir / "2026-01-01.parquet")

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            results = loader.load_all(dry_run=True)

            assert results["items"] == 1
            assert not adapter.table_exists("items")


class TestDropExisting:
    def test_drop_and_recreate(self, tmp_path):
        sources = [DatasetSource(id="items", endpoint="/api/items")]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet([{"name": "A"}], source_dir / "2026-01-01.parquet")

        adapter = _sqlite_adapter()
        with adapter:
            # First load
            loader = DatasetDbLoader(config, adapter)
            loader.load_all()
            assert adapter.fetch_one("SELECT COUNT(*) as c FROM items")["c"] == 1

            # Second load with drop
            loader2 = DatasetDbLoader(config, adapter)
            loader2.load_all(drop_existing=True)
            assert adapter.fetch_one("SELECT COUNT(*) as c FROM items")["c"] == 1


class TestEmptySource:
    def test_no_parquet_returns_zero(self, tmp_path):
        sources = [DatasetSource(id="empty", endpoint="/api/empty")]
        config = _make_config(tmp_path, sources)

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            results = loader.load_all()
            assert results["empty"] == 0
