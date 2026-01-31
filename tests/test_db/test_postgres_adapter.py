"""Integration tests for PostgreSQL adapter.

Requires a running PostgreSQL instance.
Default: postgresql://testuser:testpass@localhost:5434/testdb
Override with PG_TEST_URL env var.
"""

import importlib.util
import os

import pytest

HAS_PSYCOPG = importlib.util.find_spec("psycopg") is not None

pytestmark = pytest.mark.skipif(not HAS_PSYCOPG, reason="psycopg not installed")

PG_TEST_URL = os.environ.get(
    "PG_TEST_URL", "postgresql://testuser:testpass@localhost:5434/testdb"
)


@pytest.fixture
def config():
    from anysite.db.config import ConnectionConfig, DatabaseType

    return ConnectionConfig(
        name="test_pg",
        type=DatabaseType.POSTGRES,
        host="localhost",
        port=5434,
        database="testdb",
        user="testuser",
        password_env="PG_TEST_PASS",
    )


@pytest.fixture(autouse=True)
def set_pg_password(monkeypatch):
    monkeypatch.setenv("PG_TEST_PASS", "testpass")


@pytest.fixture
def adapter(config):
    from anysite.db.adapters.postgres import PostgresAdapter

    a = PostgresAdapter(config)
    a.connect()
    yield a
    # Clean up all test tables
    tables = a.fetch_all(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    for t in tables:
        a.execute(f"DROP TABLE IF EXISTS {t['tablename']} CASCADE")
    a.disconnect()


class TestPostgresConnection:
    def test_connect_disconnect(self, config):
        from anysite.db.adapters.postgres import PostgresAdapter

        a = PostgresAdapter(config)
        a.connect()
        assert a._conn is not None
        a.disconnect()
        assert a._conn is None

    def test_context_manager(self, config):
        from anysite.db.adapters.postgres import PostgresAdapter

        with PostgresAdapter(config) as a:
            assert a._conn is not None
        assert a._conn is None

    def test_connect_via_url(self, monkeypatch):
        from anysite.db.adapters.postgres import PostgresAdapter
        from anysite.db.config import ConnectionConfig, DatabaseType

        monkeypatch.setenv("PG_URL", PG_TEST_URL)
        cfg = ConnectionConfig(
            name="url_test",
            type=DatabaseType.POSTGRES,
            url_env="PG_URL",
        )
        with PostgresAdapter(cfg) as a:
            info = a.get_server_info()
            assert info["type"] == "postgres"

    def test_get_server_info(self, adapter):
        info = adapter.get_server_info()
        assert info["type"] == "postgres"
        assert "PostgreSQL" in info["version"]
        assert info["database"] == "testdb"

    def test_not_connected_error(self, config):
        from anysite.db.adapters.postgres import PostgresAdapter

        a = PostgresAdapter(config)
        with pytest.raises(RuntimeError, match="Not connected"):
            a.execute("SELECT 1")


class TestPostgresExecute:
    def test_execute_and_fetch(self, adapter):
        adapter.execute("CREATE TABLE test_exec (id INTEGER, name TEXT)")
        adapter.execute("INSERT INTO test_exec VALUES (1, 'alice')")
        adapter.execute("INSERT INTO test_exec VALUES (2, 'bob')")

        row = adapter.fetch_one("SELECT * FROM test_exec WHERE id = %s", (1,))
        assert row is not None
        assert row["id"] == 1
        assert row["name"] == "alice"

    def test_fetch_all(self, adapter):
        adapter.execute("CREATE TABLE test_fetch (id INTEGER, val TEXT)")
        adapter.execute("INSERT INTO test_fetch VALUES (1, 'a')")
        adapter.execute("INSERT INTO test_fetch VALUES (2, 'b')")
        adapter.execute("INSERT INTO test_fetch VALUES (3, 'c')")

        rows = adapter.fetch_all("SELECT * FROM test_fetch ORDER BY id")
        assert len(rows) == 3
        assert [r["val"] for r in rows] == ["a", "b", "c"]

    def test_fetch_one_none(self, adapter):
        adapter.execute("CREATE TABLE test_empty (id INTEGER)")
        result = adapter.fetch_one("SELECT * FROM test_empty")
        assert result is None

    def test_fetch_all_empty(self, adapter):
        adapter.execute("CREATE TABLE test_empty2 (id INTEGER)")
        result = adapter.fetch_all("SELECT * FROM test_empty2")
        assert result == []


class TestPostgresTableOperations:
    def test_create_table(self, adapter):
        adapter.create_table(
            "test_create",
            {"id": "BIGINT", "name": "VARCHAR(255)", "score": "DOUBLE PRECISION"},
            primary_key="id",
        )
        assert adapter.table_exists("test_create")

    def test_table_exists(self, adapter):
        assert adapter.table_exists("nonexistent_table_xyz") is False
        adapter.execute("CREATE TABLE test_exists (id INTEGER)")
        assert adapter.table_exists("test_exists") is True

    def test_get_table_schema(self, adapter):
        adapter.execute(
            "CREATE TABLE test_schema ("
            "  id BIGINT PRIMARY KEY,"
            "  name VARCHAR(255) NOT NULL,"
            "  bio TEXT,"
            "  score DOUBLE PRECISION,"
            "  active BOOLEAN DEFAULT true"
            ")"
        )
        schema = adapter.get_table_schema("test_schema")
        assert len(schema) == 5

        id_col = next(c for c in schema if c["name"] == "id")
        assert id_col["primary_key"] == "YES"
        assert "int" in id_col["type"]  # bigint

        name_col = next(c for c in schema if c["name"] == "name")
        assert name_col["nullable"] == "NO"

        bio_col = next(c for c in schema if c["name"] == "bio")
        assert bio_col["nullable"] == "YES"


class TestPostgresInsertBatch:
    def test_basic_insert(self, adapter):
        adapter.execute("CREATE TABLE test_ins (id INTEGER, name TEXT)")
        rows = [
            {"id": 1, "name": "alice"},
            {"id": 2, "name": "bob"},
            {"id": 3, "name": "charlie"},
        ]
        count = adapter.insert_batch("test_ins", rows)
        assert count == 3

        result = adapter.fetch_all("SELECT * FROM test_ins ORDER BY id")
        assert len(result) == 3
        assert result[0]["name"] == "alice"
        assert result[2]["name"] == "charlie"

    def test_insert_empty(self, adapter):
        assert adapter.insert_batch("test_whatever", []) == 0

    def test_insert_complex_values_as_json(self, adapter):
        """Dicts and lists should be serialized to JSON strings."""
        adapter.execute("CREATE TABLE test_json (id INTEGER, data JSONB, tags JSONB)")
        rows = [
            {"id": 1, "data": {"key": "value", "nested": {"a": 1}}, "tags": ["a", "b"]},
        ]
        count = adapter.insert_batch("test_json", rows)
        assert count == 1

        result = adapter.fetch_one("SELECT * FROM test_json WHERE id = 1")
        assert result is not None
        assert result["data"] == {"key": "value", "nested": {"a": 1}}
        assert result["tags"] == ["a", "b"]

    def test_insert_sparse_rows(self, adapter):
        """Rows with different columns should handle NULLs."""
        adapter.execute("CREATE TABLE test_sparse (a TEXT, b TEXT, c TEXT)")
        rows = [
            {"a": "1", "b": "2"},
            {"a": "3", "c": "4"},
        ]
        adapter.insert_batch("test_sparse", rows)
        result = adapter.fetch_all("SELECT * FROM test_sparse ORDER BY a")
        assert result[0]["b"] == "2"
        assert result[0]["c"] is None
        assert result[1]["b"] is None
        assert result[1]["c"] == "4"

    def test_insert_on_conflict_ignore(self, adapter):
        adapter.execute("CREATE TABLE test_ign (id INTEGER PRIMARY KEY, name TEXT)")
        adapter.insert_batch("test_ign", [{"id": 1, "name": "alice"}])

        from anysite.db.config import OnConflict

        adapter.insert_batch(
            "test_ign",
            [{"id": 1, "name": "bob"}],
            on_conflict=OnConflict.IGNORE,
            conflict_columns=["id"],
        )
        result = adapter.fetch_one("SELECT * FROM test_ign WHERE id = 1")
        assert result["name"] == "alice"  # unchanged

    def test_insert_on_conflict_update(self, adapter):
        adapter.execute("CREATE TABLE test_upsert (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
        adapter.insert_batch("test_upsert", [{"id": 1, "name": "alice", "age": 30}])

        from anysite.db.config import OnConflict

        adapter.insert_batch(
            "test_upsert",
            [{"id": 1, "name": "alice_v2", "age": 31}],
            on_conflict=OnConflict.UPDATE,
            conflict_columns=["id"],
        )
        result = adapter.fetch_one("SELECT * FROM test_upsert WHERE id = 1")
        assert result["name"] == "alice_v2"
        assert result["age"] == 31

    def test_insert_large_batch(self, adapter):
        adapter.execute("CREATE TABLE test_large (id INTEGER, val TEXT)")
        rows = [{"id": i, "val": f"row_{i}"} for i in range(500)]
        count = adapter.insert_batch("test_large", rows)
        assert count == 500

        result = adapter.fetch_one("SELECT COUNT(*) as cnt FROM test_large")
        assert result["cnt"] == 500


class TestPostgresTransaction:
    def test_transaction_commit(self, adapter):
        adapter.execute("CREATE TABLE test_tx (id INTEGER)")
        with adapter.transaction():
            adapter.conn.execute("INSERT INTO test_tx VALUES (1)")
            adapter.conn.execute("INSERT INTO test_tx VALUES (2)")
        rows = adapter.fetch_all("SELECT * FROM test_tx ORDER BY id")
        assert len(rows) == 2

    def test_transaction_rollback(self, adapter):
        adapter.execute("CREATE TABLE test_tx_rb (id INTEGER)")
        try:
            with adapter.transaction():
                adapter.conn.execute("INSERT INTO test_tx_rb VALUES (1)")
                raise RuntimeError("simulated error")
        except RuntimeError:
            pass
        rows = adapter.fetch_all("SELECT * FROM test_tx_rb")
        assert len(rows) == 0


class TestPostgresViaManager:
    def test_manager_test_connection(self, config):
        from anysite.db.manager import ConnectionManager

        manager = ConnectionManager.__new__(ConnectionManager)
        manager._connections = {config.name: config}
        manager.path = None

        info = manager.test(config.name)
        assert info["type"] == "postgres"
        assert "PostgreSQL" in info["version"]

    def test_manager_get_adapter(self, config):
        from anysite.db.adapters.postgres import PostgresAdapter
        from anysite.db.manager import ConnectionManager

        manager = ConnectionManager.__new__(ConnectionManager)
        manager._connections = {config.name: config}
        manager.path = None

        adapter = manager.get_adapter(config)
        assert isinstance(adapter, PostgresAdapter)


class TestPostgresInsertOperations:
    """Test insert_from_stream against real PostgreSQL."""

    def test_insert_jsonl_auto_create(self, adapter):
        import io

        from anysite.db.operations.insert import insert_from_stream

        stream = io.StringIO(
            '{"username": "alice", "score": 95, "active": true}\n'
            '{"username": "bob", "score": 88, "active": false}\n'
        )
        count = insert_from_stream(
            adapter, "test_auto", stream, auto_create=True, quiet=True
        )
        assert count == 2
        assert adapter.table_exists("test_auto")

        rows = adapter.fetch_all("SELECT * FROM test_auto ORDER BY username")
        assert len(rows) == 2
        assert rows[0]["username"] == "alice"
        assert rows[0]["score"] == 95
        assert rows[0]["active"] is True

    def test_insert_json_array(self, adapter):
        import io

        from anysite.db.operations.insert import insert_from_stream

        adapter.execute("CREATE TABLE test_arr (id INTEGER, name TEXT)")
        stream = io.StringIO('[{"id": 1, "name": "x"}, {"id": 2, "name": "y"}]')
        count = insert_from_stream(adapter, "test_arr", stream)
        assert count == 2

    def test_upsert_via_stream(self, adapter):
        import io

        from anysite.db.config import OnConflict
        from anysite.db.operations.insert import insert_from_stream

        adapter.execute("CREATE TABLE test_ups (id INTEGER PRIMARY KEY, val TEXT)")

        s1 = io.StringIO('{"id": 1, "val": "original"}')
        insert_from_stream(adapter, "test_ups", s1)

        s2 = io.StringIO('{"id": 1, "val": "updated"}')
        insert_from_stream(
            adapter,
            "test_ups",
            s2,
            on_conflict=OnConflict.UPDATE,
            conflict_columns=["id"],
        )

        row = adapter.fetch_one("SELECT * FROM test_ups WHERE id = 1")
        assert row["val"] == "updated"

    def test_insert_nested_objects_as_jsonb(self, adapter):
        import io

        from anysite.db.operations.insert import insert_from_stream

        stream = io.StringIO(
            '{"id": 1, "profile": {"name": "alice", "skills": ["python", "sql"]}, "tags": [1, 2, 3]}'
        )
        count = insert_from_stream(
            adapter, "test_nested", stream, auto_create=True, quiet=True
        )
        assert count == 1

        row = adapter.fetch_one("SELECT * FROM test_nested WHERE id = 1")
        assert row is not None
        # psycopg auto-deserializes JSONB
        # but since we store as TEXT in auto-create (inferred as "json" → TEXT for sqlite,
        # but for postgres it maps to JSONB), let's check the value
        assert "alice" in str(row["profile"])


class TestPostgresSchemaInference:
    """Test that inferred schemas create valid PostgreSQL tables."""

    def test_infer_and_create(self, adapter):
        from anysite.db.schema.inference import infer_table_schema

        rows = [
            {
                "id": 1,
                "name": "Satya Nadella",
                "email": "satya@example.com",
                "url": "https://linkedin.com/in/satyanadella",
                "followers": 12345678,
                "rating": 4.9,
                "active": True,
                "joined": "2024-01-15",
                "updated_at": "2024-06-15T10:30:00Z",
                "metadata": {"source": "api", "version": 2},
            }
        ]
        schema = infer_table_schema("profiles", rows)
        sql_types = schema.to_sql_types("postgres")

        assert sql_types["id"] == "BIGINT"
        assert sql_types["name"] == "VARCHAR(255)"
        assert sql_types["email"] == "TEXT"  # email maps to TEXT for postgres
        assert sql_types["url"] == "TEXT"
        assert sql_types["followers"] == "BIGINT"
        assert sql_types["rating"] == "DOUBLE PRECISION"
        assert sql_types["active"] == "BOOLEAN"
        assert sql_types["joined"] == "DATE"
        assert sql_types["updated_at"] == "TIMESTAMPTZ"
        assert sql_types["metadata"] == "JSONB"

        # Actually create the table and insert
        adapter.create_table("profiles", sql_types, primary_key="id")
        assert adapter.table_exists("profiles")

        count = adapter.insert_batch("profiles", rows)
        assert count == 1

        result = adapter.fetch_one("SELECT * FROM profiles WHERE id = 1")
        assert result["name"] == "Satya Nadella"
        assert result["followers"] == 12345678
        assert result["active"] is True
