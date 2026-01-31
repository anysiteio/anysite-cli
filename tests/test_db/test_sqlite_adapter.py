"""Tests for SQLite adapter."""

import pytest

from anysite.db.adapters.sqlite import SQLiteAdapter
from anysite.db.config import ConnectionConfig, DatabaseType, OnConflict


@pytest.fixture
def config():
    return ConnectionConfig(name="test", type=DatabaseType.SQLITE, path=":memory:")


@pytest.fixture
def adapter(config):
    """Create a connected in-memory SQLite adapter."""
    a = SQLiteAdapter(config)
    a.connect()
    yield a
    a.disconnect()


class TestSQLiteAdapter:
    def test_connect_disconnect(self, config):
        adapter = SQLiteAdapter(config)
        adapter.connect()
        assert adapter._conn is not None
        adapter.disconnect()
        assert adapter._conn is None

    def test_context_manager(self, config):
        with SQLiteAdapter(config) as adapter:
            assert adapter._conn is not None
        assert adapter._conn is None

    def test_execute(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        assert adapter.table_exists("test")

    def test_fetch_one(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        adapter.execute("INSERT INTO test VALUES (1, 'alice')")
        row = adapter.fetch_one("SELECT * FROM test WHERE id = ?", (1,))
        assert row is not None
        assert row["id"] == 1
        assert row["name"] == "alice"

    def test_fetch_one_none(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER)")
        assert adapter.fetch_one("SELECT * FROM test") is None

    def test_fetch_all(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        adapter.execute("INSERT INTO test VALUES (1, 'alice')")
        adapter.execute("INSERT INTO test VALUES (2, 'bob')")
        rows = adapter.fetch_all("SELECT * FROM test ORDER BY id")
        assert len(rows) == 2
        assert rows[0]["name"] == "alice"
        assert rows[1]["name"] == "bob"

    def test_insert_batch(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        count = adapter.insert_batch("test", rows)
        assert count == 2

        result = adapter.fetch_all("SELECT * FROM test ORDER BY id")
        assert len(result) == 2

    def test_insert_batch_empty(self, adapter):
        assert adapter.insert_batch("test", []) == 0

    def test_insert_batch_complex_values(self, adapter):
        """Complex types (dict, list) should be serialized to JSON."""
        adapter.execute("CREATE TABLE test (id INTEGER, data TEXT)")
        rows = [{"id": 1, "data": {"nested": "value"}}]
        adapter.insert_batch("test", rows)
        result = adapter.fetch_one("SELECT * FROM test")
        assert result is not None
        import json
        assert json.loads(result["data"]) == {"nested": "value"}

    def test_insert_batch_on_conflict_ignore(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        adapter.insert_batch("test", [{"id": 1, "name": "alice"}])
        # Insert duplicate with IGNORE
        adapter.insert_batch(
            "test",
            [{"id": 1, "name": "bob"}],
            on_conflict=OnConflict.IGNORE,
        )
        result = adapter.fetch_one("SELECT * FROM test WHERE id = 1")
        assert result["name"] == "alice"  # unchanged

    def test_insert_batch_on_conflict_replace(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        adapter.insert_batch("test", [{"id": 1, "name": "alice"}])
        adapter.insert_batch(
            "test",
            [{"id": 1, "name": "bob"}],
            on_conflict=OnConflict.REPLACE,
        )
        result = adapter.fetch_one("SELECT * FROM test WHERE id = 1")
        assert result["name"] == "bob"

    def test_insert_batch_upsert(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
        adapter.insert_batch("test", [{"id": 1, "name": "alice", "age": 30}])
        adapter.insert_batch(
            "test",
            [{"id": 1, "name": "alice_updated", "age": 31}],
            on_conflict=OnConflict.UPDATE,
            conflict_columns=["id"],
        )
        result = adapter.fetch_one("SELECT * FROM test WHERE id = 1")
        assert result["name"] == "alice_updated"
        assert result["age"] == 31

    def test_insert_batch_sparse_rows(self, adapter):
        """Rows with different keys should be handled."""
        adapter.execute("CREATE TABLE test (a TEXT, b TEXT, c TEXT)")
        rows = [
            {"a": "1", "b": "2"},
            {"a": "3", "c": "4"},
        ]
        adapter.insert_batch("test", rows)
        result = adapter.fetch_all("SELECT * FROM test ORDER BY a")
        assert result[0]["a"] == "1"
        assert result[0]["b"] == "2"
        assert result[0]["c"] is None
        assert result[1]["a"] == "3"
        assert result[1]["c"] == "4"

    def test_table_exists(self, adapter):
        assert adapter.table_exists("nonexistent") is False
        adapter.execute("CREATE TABLE test (id INTEGER)")
        assert adapter.table_exists("test") is True

    def test_create_table(self, adapter):
        adapter.create_table("users", {"id": "INTEGER", "name": "TEXT"}, primary_key="id")
        assert adapter.table_exists("users")
        schema = adapter.get_table_schema("users")
        assert len(schema) == 2
        id_col = next(c for c in schema if c["name"] == "id")
        assert id_col["primary_key"] == "YES"

    def test_get_table_schema(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT NOT NULL, age REAL)")
        schema = adapter.get_table_schema("test")
        assert len(schema) == 3

        id_col = next(c for c in schema if c["name"] == "id")
        assert id_col["type"] == "INTEGER"
        assert id_col["primary_key"] == "YES"

        name_col = next(c for c in schema if c["name"] == "name")
        assert name_col["nullable"] == "NO"

    def test_get_server_info(self, adapter):
        info = adapter.get_server_info()
        assert info["type"] == "sqlite"
        assert "version" in info

    def test_transaction_commit(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER)")
        with adapter.transaction():
            adapter.conn.execute("INSERT INTO test VALUES (1)")
            adapter.conn.execute("INSERT INTO test VALUES (2)")
        rows = adapter.fetch_all("SELECT * FROM test")
        assert len(rows) == 2

    def test_transaction_rollback(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER)")
        try:
            with adapter.transaction():
                adapter.conn.execute("INSERT INTO test VALUES (1)")
                raise RuntimeError("test error")
        except RuntimeError:
            pass
        rows = adapter.fetch_all("SELECT * FROM test")
        assert len(rows) == 0

    def test_not_connected_error(self, config):
        adapter = SQLiteAdapter(config)
        with pytest.raises(RuntimeError, match="Not connected"):
            adapter.execute("SELECT 1")

    def test_file_based_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="test", type=DatabaseType.SQLITE, path=db_path)
        with SQLiteAdapter(config) as adapter:
            adapter.execute("CREATE TABLE test (id INTEGER)")
            adapter.execute("INSERT INTO test VALUES (1)")

        # Reopen and verify
        with SQLiteAdapter(config) as adapter:
            row = adapter.fetch_one("SELECT * FROM test")
            assert row["id"] == 1
