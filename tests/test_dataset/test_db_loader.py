"""Tests for dataset DB loader with SQLite in-memory adapter."""

import json
import pytest

from anysite.dataset.db_loader import DatasetDbLoader, LoadResult, _extract_dot_value, _filter_record
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

            assert results["profiles"].row_count == 2
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

            assert results["companies"].row_count == 2
            assert results["employees"].row_count == 3

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

            assert results["items"].ops == 1
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
            assert results["empty"].row_count == 0


class TestDiffBasedSync:
    """Test diff-based incremental sync when db_load.key is configured."""

    def _setup_two_snapshots(self, tmp_path, source_id, old_records, new_records):
        """Write two parquet snapshots for a source."""
        source_dir = get_source_dir(tmp_path / "data", source_id)
        write_parquet(old_records, source_dir / "2026-01-01.parquet")
        write_parquet(new_records, source_dir / "2026-01-02.parquet")

    def test_inserts_added_records(self, tmp_path):
        """New records in the latest snapshot are INSERTed."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[{"name": "Alice", "score": 90}],
            new_records=[
                {"name": "Alice", "score": 90},
                {"name": "Bob", "score": 80},
            ],
        )

        adapter = _sqlite_adapter()
        with adapter:
            # First load: full insert of latest (table doesn't exist yet)
            loader = DatasetDbLoader(config, adapter)
            results = loader.load_all()
            assert results["items"].row_count == 2

            # Simulate: drop and reload just the old snapshot to set up DB state
            adapter.execute("DROP TABLE items")
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader2 = DatasetDbLoader(config, adapter)
            loader2._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )
            rows = adapter.fetch_all("SELECT * FROM items")
            assert len(rows) == 1
            assert rows[0]["name"] == "Alice"

            # Now diff-based sync should INSERT Bob
            loader3 = DatasetDbLoader(config, adapter)
            results = loader3.load_all()
            assert results["items"].ops == 1  # 1 added

            rows = adapter.fetch_all("SELECT * FROM items ORDER BY name")
            assert len(rows) == 2
            assert rows[1]["name"] == "Bob"

    def test_deletes_removed_records(self, tmp_path):
        """Records missing from the latest snapshot are DELETEd."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[
                {"name": "Alice", "score": 90},
                {"name": "Bob", "score": 80},
            ],
            new_records=[{"name": "Alice", "score": 90}],
        )

        adapter = _sqlite_adapter()
        with adapter:
            # Set up DB with both records
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )
            rows = adapter.fetch_all("SELECT * FROM items")
            assert len(rows) == 2

            # Diff-based sync should DELETE Bob
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            assert results["items"].ops == 1  # 1 removed

            rows = adapter.fetch_all("SELECT * FROM items")
            assert len(rows) == 1
            assert rows[0]["name"] == "Alice"

    def test_updates_changed_records(self, tmp_path):
        """Records with changed values are UPDATEd."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[{"name": "Alice", "score": 90}],
            new_records=[{"name": "Alice", "score": 95}],
        )

        adapter = _sqlite_adapter()
        with adapter:
            # Set up DB with old data
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )
            rows = adapter.fetch_all("SELECT * FROM items")
            assert rows[0]["score"] == 90

            # Diff-based sync should UPDATE score
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            assert results["items"].ops == 1  # 1 changed

            rows = adapter.fetch_all("SELECT * FROM items")
            assert len(rows) == 1
            assert rows[0]["score"] == 95

    def test_combined_add_remove_update(self, tmp_path):
        """Test all three operations in a single sync."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[
                {"name": "Alice", "score": 90},
                {"name": "Bob", "score": 80},
            ],
            new_records=[
                {"name": "Alice", "score": 95},   # changed
                {"name": "Carol", "score": 70},    # added
                # Bob removed
            ],
        )

        adapter = _sqlite_adapter()
        with adapter:
            # Set up DB with old data
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )

            # Diff-based sync
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            assert results["items"].ops == 3  # 1 added + 1 removed + 1 changed

            rows = adapter.fetch_all("SELECT * FROM items ORDER BY name")
            assert len(rows) == 2
            names = [r["name"] for r in rows]
            assert "Alice" in names
            assert "Carol" in names
            assert "Bob" not in names
            alice = [r for r in rows if r["name"] == "Alice"][0]
            assert alice["score"] == 95

    def test_no_key_falls_back_to_full_insert(self, tmp_path):
        """Without db_load.key, load-db does full INSERT of latest snapshot."""
        sources = [
            DatasetSource(id="items", endpoint="/api/items"),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[{"name": "Alice", "score": 90}],
            new_records=[
                {"name": "Alice", "score": 95},
                {"name": "Bob", "score": 80},
            ],
        )

        adapter = _sqlite_adapter()
        with adapter:
            # First load creates table with latest snapshot
            loader = DatasetDbLoader(config, adapter)
            results = loader.load_all()
            assert results["items"].row_count == 2

            # Second load without key: truncate + full insert (no duplicates)
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            assert results["items"].ops == 2
            # Table is truncated before re-insert, no duplicates
            rows = adapter.fetch_all("SELECT * FROM items")
            assert len(rows) == 2


class TestSnapshotLoading:
    """Test --snapshot flag for loading a specific date."""

    def test_load_specific_snapshot(self, tmp_path):
        sources = [
            DatasetSource(id="items", endpoint="/api/items"),
        ]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet(
            [{"name": "Alice", "score": 90}],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [{"name": "Alice", "score": 95}, {"name": "Bob", "score": 80}],
            source_dir / "2026-01-02.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            # Load the older snapshot specifically
            loader = DatasetDbLoader(config, adapter)
            results = loader.load_all(snapshot="2026-01-01")
            assert results["items"].row_count == 1

            rows = adapter.fetch_all("SELECT * FROM items")
            assert len(rows) == 1
            assert rows[0]["name"] == "Alice"
            assert rows[0]["score"] == 90

    def test_snapshot_not_found(self, tmp_path):
        sources = [DatasetSource(id="items", endpoint="/api/items")]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet([{"name": "A"}], source_dir / "2026-01-01.parquet")

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            results = loader.load_all(snapshot="2026-12-31")
            assert results["items"].row_count == 0


class TestDropExistingWithDiffKey:
    """Test --drop-existing forces full insert even with db_load.key."""

    def test_drop_existing_ignores_diff(self, tmp_path):
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet(
            [{"name": "Alice", "score": 90}],
            source_dir / "2026-01-01.parquet",
        )
        write_parquet(
            [{"name": "Alice", "score": 95}, {"name": "Bob", "score": 80}],
            source_dir / "2026-01-02.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            # Initial load
            loader = DatasetDbLoader(config, adapter)
            loader.load_all()

            # Drop and reload — should full insert latest, not diff
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all(drop_existing=True)
            assert results["items"].row_count == 2

            rows = adapter.fetch_all("SELECT * FROM items ORDER BY name")
            assert len(rows) == 2
            assert rows[0]["name"] == "Alice"
            assert rows[0]["score"] == 95


class TestAppendSyncMode:
    """Test sync: append skips DELETE but still INSERTs and UPDATEs."""

    def _setup_two_snapshots(self, tmp_path, source_id, old_records, new_records):
        source_dir = get_source_dir(tmp_path / "data", source_id)
        write_parquet(old_records, source_dir / "2026-01-01.parquet")
        write_parquet(new_records, source_dir / "2026-01-02.parquet")

    def test_append_keeps_removed_records(self, tmp_path):
        """With sync: append, records missing from new snapshot are NOT deleted."""
        sources = [
            DatasetSource(
                id="posts", endpoint="/api/posts",
                db_load=DbLoadConfig(key="uid", sync="append"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "posts",
            old_records=[
                {"uid": "a", "text": "Hello", "likes": 10},
                {"uid": "b", "text": "World", "likes": 5},
                {"uid": "c", "text": "Bye", "likes": 3},
            ],
            new_records=[
                {"uid": "a", "text": "Hello", "likes": 15},  # changed
                {"uid": "d", "text": "New post", "likes": 0},  # added
                # b and c removed from snapshot
            ],
        )

        adapter = _sqlite_adapter()
        with adapter:
            # Set up DB with old data
            source_dir = get_source_dir(tmp_path / "data", "posts")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "posts", source_dir / "2026-01-01.parquet"
            )
            assert len(adapter.fetch_all("SELECT * FROM posts")) == 3

            # Diff sync with append mode
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            # 1 added + 1 changed = 2 (no deletes)
            assert results["posts"].ops == 2

            rows = adapter.fetch_all("SELECT * FROM posts ORDER BY uid")
            assert len(rows) == 4  # 3 original + 1 added, none deleted
            uids = [r["uid"] for r in rows]
            assert "a" in uids  # updated
            assert "b" in uids  # kept (not deleted)
            assert "c" in uids  # kept (not deleted)
            assert "d" in uids  # added

            # Verify update applied
            a_row = [r for r in rows if r["uid"] == "a"][0]
            assert a_row["likes"] == 15

    def test_full_sync_deletes_removed_records(self, tmp_path):
        """With sync: full (default), removed records ARE deleted."""
        sources = [
            DatasetSource(
                id="posts", endpoint="/api/posts",
                db_load=DbLoadConfig(key="uid", sync="full"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "posts",
            old_records=[
                {"uid": "a", "text": "Hello", "likes": 10},
                {"uid": "b", "text": "World", "likes": 5},
            ],
            new_records=[
                {"uid": "a", "text": "Hello", "likes": 15},
                # b removed
            ],
        )

        adapter = _sqlite_adapter()
        with adapter:
            source_dir = get_source_dir(tmp_path / "data", "posts")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "posts", source_dir / "2026-01-01.parquet"
            )
            assert len(adapter.fetch_all("SELECT * FROM posts")) == 2

            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            assert results["posts"].ops == 2  # 1 changed + 1 removed

            rows = adapter.fetch_all("SELECT * FROM posts")
            assert len(rows) == 1
            assert rows[0]["uid"] == "a"


class TestPostgresPlaceholders:
    """Test that diff-based sync uses %s placeholders for postgres dialect."""

    def _setup_two_snapshots(self, tmp_path, source_id, old_records, new_records):
        source_dir = get_source_dir(tmp_path / "data", source_id)
        write_parquet(old_records, source_dir / "2026-01-01.parquet")
        write_parquet(new_records, source_dir / "2026-01-02.parquet")

    def test_delete_uses_percent_s(self, tmp_path):
        """DELETE query uses %s placeholder for postgres."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name", sync="full"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[
                {"name": "Alice", "score": 90},
                {"name": "Bob", "score": 80},
            ],
            new_records=[{"name": "Alice", "score": 90}],
        )

        # Use real SQLite adapter for initial load, then mock for diff sync
        adapter = _sqlite_adapter()
        with adapter:
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )

            # Patch dialect to postgres and spy on execute
            loader2 = DatasetDbLoader(config, adapter)
            loader2._dialect = "postgres"
            original_execute = adapter.execute
            calls = []

            def spy_execute(sql, params=None):
                calls.append((sql, params))
                # Replace %s with ? for SQLite execution
                original_execute(sql.replace("%s", "?"), params)

            adapter.execute = spy_execute
            loader2.load_all()

            # Verify DELETE used %s
            delete_calls = [c for c in calls if "DELETE" in c[0]]
            assert len(delete_calls) == 1
            assert "%s" in delete_calls[0][0]
            assert "?" not in delete_calls[0][0]

    def test_update_uses_percent_s(self, tmp_path):
        """UPDATE query uses %s placeholders for postgres."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name"),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[{"name": "Alice", "score": 90}],
            new_records=[{"name": "Alice", "score": 95}],
        )

        adapter = _sqlite_adapter()
        with adapter:
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )

            loader2 = DatasetDbLoader(config, adapter)
            loader2._dialect = "postgres"
            original_execute = adapter.execute
            calls = []

            def spy_execute(sql, params=None):
                calls.append((sql, params))
                original_execute(sql.replace("%s", "?"), params)

            adapter.execute = spy_execute
            loader2.load_all()

            update_calls = [c for c in calls if "UPDATE" in c[0]]
            assert len(update_calls) == 1
            assert "%s" in update_calls[0][0]
            assert "?" not in update_calls[0][0]


class TestUpdateFieldFiltering:
    """Test that UPDATE only targets fields present in db_load.fields."""

    def _setup_two_snapshots(self, tmp_path, source_id, old_records, new_records):
        source_dir = get_source_dir(tmp_path / "data", source_id)
        write_parquet(old_records, source_dir / "2026-01-01.parquet")
        write_parquet(new_records, source_dir / "2026-01-02.parquet")

    def test_update_only_db_load_fields(self, tmp_path):
        """UPDATE should skip fields not in db_load.fields."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name", fields=["name", "score"]),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[{"name": "Alice", "score": 90, "extra": "old"}],
            new_records=[{"name": "Alice", "score": 95, "extra": "new"}],
        )

        adapter = _sqlite_adapter()
        with adapter:
            # Full insert only creates columns from db_load.fields
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )

            # Table should only have id, name, score (no extra)
            schema = adapter.get_table_schema("items")
            col_names = [c["name"] for c in schema]
            assert "extra" not in col_names
            assert "score" in col_names

            # Diff sync — extra changed but should be skipped
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            assert results["items"].ops == 1  # score changed

            rows = adapter.fetch_all("SELECT * FROM items")
            assert rows[0]["score"] == 95

    def test_update_with_dot_notation_alias(self, tmp_path):
        """UPDATE uses correct DB column name for aliased dot-notation fields."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(
                    key="meta.id",
                    fields=["meta.id AS meta_id", "text", "count"],
                ),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[
                {"meta": json.dumps({"id": "x1"}), "text": "hello", "count": 5, "other": "a"},
            ],
            new_records=[
                {"meta": json.dumps({"id": "x1"}), "text": "updated", "count": 10, "other": "b"},
            ],
        )

        adapter = _sqlite_adapter()
        with adapter:
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )

            rows = adapter.fetch_all("SELECT * FROM items")
            assert rows[0]["meta_id"] == "x1"
            assert rows[0]["text"] == "hello"

            # Diff sync — text and count changed, other should be skipped
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()

            rows = adapter.fetch_all("SELECT * FROM items")
            assert rows[0]["text"] == "updated"
            assert rows[0]["count"] == 10

    def test_update_skipped_when_no_db_fields_changed(self, tmp_path):
        """If only non-DB fields changed, no UPDATE should happen."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name", fields=["name", "score"]),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[{"name": "Alice", "score": 90, "extra": "old"}],
            # score unchanged, only extra changed
            new_records=[{"name": "Alice", "score": 90, "extra": "new"}],
        )

        adapter = _sqlite_adapter()
        with adapter:
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )

            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            # extra is not in db_load.fields, so no actual update
            assert results["items"].ops == 0

            rows = adapter.fetch_all("SELECT * FROM items")
            assert len(rows) == 1
            assert rows[0]["score"] == 90


class TestAutoIncludeKey:
    """Test that db_load.key is auto-included in db_load.fields when not explicitly listed."""

    def _setup_two_snapshots(self, tmp_path, source_id, old_records, new_records):
        source_dir = get_source_dir(tmp_path / "data", source_id)
        write_parquet(old_records, source_dir / "2026-01-01.parquet")
        write_parquet(new_records, source_dir / "2026-01-02.parquet")

    def test_key_auto_included_in_fields(self, tmp_path):
        """db_load.fields = [url, text], key = name → name column auto-created."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name", fields=["url", "text"]),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[{"name": "Alice", "url": "http://a", "text": "hello"}],
            new_records=[
                {"name": "Alice", "url": "http://a", "text": "updated"},
                {"name": "Bob", "url": "http://b", "text": "new"},
            ],
        )

        adapter = _sqlite_adapter()
        with adapter:
            # First load — full insert of old snapshot to set up DB
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )

            # Verify name column was auto-created
            schema = adapter.get_table_schema("items")
            col_names = [c["name"] for c in schema]
            assert "name" in col_names
            assert "url" in col_names
            assert "text" in col_names

            rows = adapter.fetch_all("SELECT * FROM items")
            assert rows[0]["name"] == "Alice"

            # Diff sync should work — key column exists
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            assert results["items"].ops == 2  # 1 added + 1 changed

            rows = adapter.fetch_all("SELECT * FROM items ORDER BY name")
            assert len(rows) == 2
            assert rows[0]["name"] == "Alice"
            assert rows[0]["text"] == "updated"
            assert rows[1]["name"] == "Bob"

    def test_dot_key_auto_included(self, tmp_path):
        """db_load.fields = [text], key = meta.id → meta_id column auto-created."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="meta.id", fields=["text"]),
            ),
        ]
        config = _make_config(tmp_path, sources)

        self._setup_two_snapshots(
            tmp_path, "items",
            old_records=[
                {"meta": json.dumps({"id": "x1"}), "text": "hello"},
            ],
            new_records=[
                {"meta": json.dumps({"id": "x1"}), "text": "updated"},
                {"meta": json.dumps({"id": "x2"}), "text": "new"},
            ],
        )

        adapter = _sqlite_adapter()
        with adapter:
            source_dir = get_source_dir(tmp_path / "data", "items")
            loader = DatasetDbLoader(config, adapter)
            loader._full_insert(
                sources[0], "items", source_dir / "2026-01-01.parquet"
            )

            # Verify meta_id column was auto-created
            schema = adapter.get_table_schema("items")
            col_names = [c["name"] for c in schema]
            assert "meta_id" in col_names
            assert "text" in col_names

            rows = adapter.fetch_all("SELECT * FROM items")
            assert rows[0]["meta_id"] == "x1"

            # Diff sync should work
            loader2 = DatasetDbLoader(config, adapter)
            results = loader2.load_all()
            assert results["items"].ops == 2  # 1 added + 1 changed

            rows = adapter.fetch_all("SELECT * FROM items ORDER BY meta_id")
            assert len(rows) == 2
            assert rows[0]["meta_id"] == "x1"
            assert rows[0]["text"] == "updated"
            assert rows[1]["meta_id"] == "x2"

    def test_key_already_in_fields_not_duplicated(self, tmp_path):
        """If key is already in fields, it should not be added twice."""
        sources = [
            DatasetSource(
                id="items", endpoint="/api/items",
                db_load=DbLoadConfig(key="name", fields=["name", "score"]),
            ),
        ]
        config = _make_config(tmp_path, sources)

        source_dir = get_source_dir(tmp_path / "data", "items")
        write_parquet(
            [{"name": "Alice", "score": 90}],
            source_dir / "2026-01-01.parquet",
        )

        adapter = _sqlite_adapter()
        with adapter:
            loader = DatasetDbLoader(config, adapter)
            loader.load_all()

            rows = adapter.fetch_all("SELECT * FROM items")
            assert rows[0]["name"] == "Alice"
            assert rows[0]["score"] == 90
