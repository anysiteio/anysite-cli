"""Tests for ClickHouse adapter with mocked driver."""

from __future__ import annotations

import importlib.util
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from anysite.db.config import ConnectionConfig, DatabaseType, OnConflict

HAS_CLICKHOUSE_CONNECT = importlib.util.find_spec("clickhouse_connect") is not None


@pytest.fixture
def config():
    return ConnectionConfig(
        name="test_ch",
        type=DatabaseType.CLICKHOUSE,
        host="localhost",
        port=8123,
        database="default",
        user="default",
    )


@pytest.fixture
def mock_client():
    """Create a mock clickhouse-connect client."""
    client = MagicMock()
    result = MagicMock()
    result.result_rows = []
    result.column_names = []
    client.query.return_value = result
    return client


@pytest.fixture
def adapter(config, mock_client):
    """Create a ClickHouseAdapter with a mocked client."""
    with patch("clickhouse_connect.get_client", return_value=mock_client):
        from anysite.db.adapters.clickhouse import ClickHouseAdapter

        a = ClickHouseAdapter(config)
        a.connect()
        yield a
        a.disconnect()


class TestClickHouseConnection:
    def test_connect_creates_client(self, config):
        mock_client = MagicMock()
        with patch("clickhouse_connect.get_client", return_value=mock_client) as mock_get:
            from anysite.db.adapters.clickhouse import ClickHouseAdapter

            a = ClickHouseAdapter(config)
            a.connect()
            mock_get.assert_called_once()
            assert a._client is not None
            a.disconnect()
            assert a._client is None

    def test_connect_idempotent(self, adapter):
        with patch("clickhouse_connect.get_client") as mock_get:
            adapter.connect()
            mock_get.assert_not_called()

    def test_context_manager(self, config):
        mock_client = MagicMock()
        with patch("clickhouse_connect.get_client", return_value=mock_client):
            from anysite.db.adapters.clickhouse import ClickHouseAdapter

            with ClickHouseAdapter(config) as a:
                assert a._client is not None
            assert a._client is None

    def test_not_connected_error(self, config):
        from anysite.db.adapters.clickhouse import ClickHouseAdapter

        a = ClickHouseAdapter(config)
        with pytest.raises(RuntimeError, match="Not connected"):
            a.execute("SELECT 1")

    def test_ssl_from_config(self):
        config = ConnectionConfig(
            name="ch",
            type=DatabaseType.CLICKHOUSE,
            host="ch.example.com",
            port=8443,
            ssl=True,
        )
        mock_client = MagicMock()
        with patch("clickhouse_connect.get_client", return_value=mock_client) as mock_get:
            from anysite.db.adapters.clickhouse import ClickHouseAdapter

            a = ClickHouseAdapter(config)
            a.connect()
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["secure"] is True
            assert call_kwargs["port"] == 8443
            a.disconnect()

    def test_ssl_inferred_from_port(self):
        config = ConnectionConfig(
            name="ch",
            type=DatabaseType.CLICKHOUSE,
            host="ch.example.com",
            port=8443,
        )
        mock_client = MagicMock()
        with patch("clickhouse_connect.get_client", return_value=mock_client) as mock_get:
            from anysite.db.adapters.clickhouse import ClickHouseAdapter

            a = ClickHouseAdapter(config)
            a.connect()
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["secure"] is True
            a.disconnect()


class TestClickHouseExecute:
    def test_execute_without_params(self, adapter, mock_client):
        adapter.execute("CREATE TABLE test (id Int64) ENGINE = MergeTree() ORDER BY id")
        mock_client.command.assert_called_once_with(
            "CREATE TABLE test (id Int64) ENGINE = MergeTree() ORDER BY id"
        )

    def test_execute_with_params(self, adapter, mock_client):
        adapter.execute("SELECT 1 WHERE id = {id:Int64}", (42,))
        mock_client.command.assert_called_once_with(
            "SELECT 1 WHERE id = {id:Int64}", parameters=(42,)
        )

    def test_fetch_one_returns_dict(self, adapter, mock_client):
        result = MagicMock()
        result.column_names = ["id", "name"]
        result.result_rows = [(1, "alice")]
        mock_client.query.return_value = result

        row = adapter.fetch_one("SELECT * FROM test LIMIT 1")
        assert row == {"id": 1, "name": "alice"}

    def test_fetch_one_returns_none(self, adapter, mock_client):
        result = MagicMock()
        result.column_names = ["id"]
        result.result_rows = []
        mock_client.query.return_value = result

        assert adapter.fetch_one("SELECT * FROM empty") is None

    def test_fetch_all(self, adapter, mock_client):
        result = MagicMock()
        result.column_names = ["id", "val"]
        result.result_rows = [(1, "a"), (2, "b"), (3, "c")]
        mock_client.query.return_value = result

        rows = adapter.fetch_all("SELECT * FROM test ORDER BY id")
        assert len(rows) == 3
        assert rows[0] == {"id": 1, "val": "a"}
        assert rows[2] == {"id": 3, "val": "c"}

    def test_fetch_all_empty(self, adapter, mock_client):
        result = MagicMock()
        result.column_names = ["id"]
        result.result_rows = []
        mock_client.query.return_value = result

        assert adapter.fetch_all("SELECT * FROM empty") == []


class TestClickHouseInsertBatch:
    def test_insert_calls_client_insert(self, adapter, mock_client):
        rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        count = adapter.insert_batch("test", rows)
        assert count == 2
        mock_client.insert.assert_called_once()

    def test_insert_empty_returns_zero(self, adapter):
        assert adapter.insert_batch("test", []) == 0

    def test_insert_serializes_complex_types(self, adapter, mock_client):
        rows = [{"id": 1, "data": {"nested": "value"}, "tags": [1, 2]}]
        adapter.insert_batch("test", rows)
        call_args = mock_client.insert.call_args
        row_data = call_args[0][1]  # positional arg 1 = data
        # data column (index 1) and tags column (index 2) should be JSON strings
        assert row_data[0][1] == json.dumps({"nested": "value"})
        assert row_data[0][2] == json.dumps([1, 2])

    def test_insert_sparse_rows(self, adapter, mock_client):
        rows = [{"a": "1", "b": "2"}, {"a": "3", "c": "4"}]
        adapter.insert_batch("test", rows)
        call_args = mock_client.insert.call_args
        column_names = call_args[1]["column_names"]
        assert set(column_names) == {"a", "b", "c"}
        row_data = call_args[0][1]
        # First row: a=1, b=2, c=None
        assert row_data[0][0] == "1"
        assert row_data[0][1] == "2"
        assert row_data[0][2] is None
        # Second row: a=3, b=None, c=4
        assert row_data[1][0] == "3"
        assert row_data[1][1] is None
        assert row_data[1][2] == "4"

    def test_insert_on_conflict_still_inserts(self, adapter, mock_client):
        """ClickHouse doesn't support ON CONFLICT — inserts go through regardless."""
        rows = [{"id": 1, "name": "alice"}]
        count = adapter.insert_batch(
            "test", rows, on_conflict=OnConflict.UPDATE, conflict_columns=["id"]
        )
        assert count == 1
        mock_client.insert.assert_called_once()


class TestClickHouseTableOperations:
    def test_table_exists_true(self, adapter, mock_client):
        result = MagicMock()
        result.column_names = ["cnt"]
        result.result_rows = [(1,)]
        mock_client.query.return_value = result

        assert adapter.table_exists("test") is True

    def test_table_exists_false(self, adapter, mock_client):
        result = MagicMock()
        result.column_names = ["cnt"]
        result.result_rows = [(0,)]
        mock_client.query.return_value = result

        assert adapter.table_exists("nonexistent") is False

    def test_create_table_with_pk(self, adapter, mock_client):
        adapter.create_table(
            "users",
            {"id": "Int64", "name": "String"},
            primary_key="id",
        )
        call_sql = mock_client.command.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS" in call_sql
        assert "MergeTree()" in call_sql
        assert "ORDER BY id" in call_sql

    def test_create_table_no_pk(self, adapter, mock_client):
        adapter.create_table("logs", {"ts": "DateTime", "msg": "String"})
        call_sql = mock_client.command.call_args[0][0]
        assert "ORDER BY tuple()" in call_sql

    def test_create_table_custom_engine(self, config, mock_client):  # noqa: ARG002
        config_with_engine = ConnectionConfig(
            name="ch",
            type=DatabaseType.CLICKHOUSE,
            host="localhost",
            options={"engine": "ReplacingMergeTree()"},
        )
        with patch("clickhouse_connect.get_client", return_value=mock_client):
            from anysite.db.adapters.clickhouse import ClickHouseAdapter

            a = ClickHouseAdapter(config_with_engine)
            a.connect()
            a.create_table("users", {"id": "Int64"}, primary_key="id")
            call_sql = mock_client.command.call_args[0][0]
            assert "ReplacingMergeTree()" in call_sql
            a.disconnect()

    def test_get_server_info(self, adapter, mock_client):
        result = MagicMock()
        result.column_names = ["ver"]
        result.result_rows = [("24.3.1.234",)]
        mock_client.query.return_value = result

        info = adapter.get_server_info()
        assert info["type"] == "clickhouse"
        assert info["version"] == "24.3.1.234"
        assert info["host"] == "localhost"
        assert info["database"] == "default"


class TestClickHouseGetTableSchema:
    def test_get_table_schema(self, adapter, mock_client):
        result = MagicMock()
        result.column_names = ["name", "type", "default_kind", "is_in_primary_key"]
        result.result_rows = [
            ("id", "Int64", "", 1),
            ("name", "Nullable(String)", "", 0),
            ("score", "Float64", "DEFAULT", 0),
        ]
        mock_client.query.return_value = result

        schema = adapter.get_table_schema("users")
        assert len(schema) == 3

        assert schema[0]["name"] == "id"
        assert schema[0]["type"] == "Int64"
        assert schema[0]["primary_key"] == "YES"
        assert schema[0]["nullable"] == "NO"

        assert schema[1]["name"] == "name"
        assert schema[1]["type"] == "Nullable(String)"
        assert schema[1]["nullable"] == "YES"
        assert schema[1]["primary_key"] == "NO"

        assert schema[2]["name"] == "score"
        assert schema[2]["type"] == "Float64"


class TestClickHouseTransactions:
    def test_transaction_is_noop(self, adapter):
        """Transaction context manager should not raise."""
        with adapter.transaction():
            pass


# ── Integration tests against real ClickHouse Cloud ──────────────────


_CH_ENV_VARS = ("CLICKHOUSE_HOST", "CLICKHOUSE_PORT", "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD", "CLICKHOUSE_DATABASE")
HAS_CH_ENV = all(os.environ.get(v) for v in _CH_ENV_VARS)


@pytest.mark.skipif(
    not HAS_CLICKHOUSE_CONNECT,
    reason="clickhouse-connect not installed",
)
@pytest.mark.skipif(
    not HAS_CH_ENV,
    reason="ClickHouse env vars not set (CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DATABASE)",
)
class TestClickHouseIntegration:
    """Read-only integration tests against a real ClickHouse instance.

    Set these environment variables to run:
        CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER,
        CLICKHOUSE_PASSWORD, CLICKHOUSE_DATABASE
    """

    @pytest.fixture
    def ch_config(self):
        return ConnectionConfig(
            name="ch_test",
            type=DatabaseType.CLICKHOUSE,
            host=os.environ["CLICKHOUSE_HOST"],
            port=int(os.environ["CLICKHOUSE_PORT"]),
            database=os.environ["CLICKHOUSE_DATABASE"],
            user=os.environ["CLICKHOUSE_USER"],
            password=os.environ["CLICKHOUSE_PASSWORD"],
            ssl=True,
        )

    @pytest.fixture
    def ch_adapter(self, ch_config):
        from anysite.db.adapters.clickhouse import ClickHouseAdapter

        a = ClickHouseAdapter(ch_config)
        a.connect()
        yield a
        a.disconnect()

    def test_connect_and_server_info(self, ch_adapter):
        info = ch_adapter.get_server_info()
        assert info["type"] == "clickhouse"
        assert info["version"]  # non-empty

    def test_table_exists(self, ch_adapter):
        tables = ch_adapter.fetch_all(
            "SELECT name FROM system.tables "
            "WHERE database = currentDatabase() LIMIT 1"
        )
        if tables:
            assert ch_adapter.table_exists(tables[0]["name"]) is True
        assert ch_adapter.table_exists("nonexistent_table_xyz_12345") is False

    def test_fetch_all(self, ch_adapter):
        rows = ch_adapter.fetch_all("SELECT 1 AS val, 'hello' AS msg")
        assert len(rows) == 1
        assert rows[0]["val"] == 1
        assert rows[0]["msg"] == "hello"

    def test_fetch_one(self, ch_adapter):
        row = ch_adapter.fetch_one("SELECT 42 AS answer")
        assert row is not None
        assert row["answer"] == 42

    def test_fetch_one_empty(self, ch_adapter):
        row = ch_adapter.fetch_one("SELECT 1 AS val WHERE 1 = 0")
        assert row is None

    def test_get_table_schema(self, ch_adapter):
        tables = ch_adapter.fetch_all(
            "SELECT name FROM system.tables "
            "WHERE database = currentDatabase() LIMIT 1"
        )
        if not tables:
            pytest.skip("No tables found in database")
        schema = ch_adapter.get_table_schema(tables[0]["name"])
        assert len(schema) > 0
        assert "name" in schema[0]
        assert "type" in schema[0]
        assert "nullable" in schema[0]
        assert "primary_key" in schema[0]

    def test_discovery(self, ch_adapter, ch_config):
        from anysite.db.discovery import DatabaseDiscoverer

        discoverer = DatabaseDiscoverer(
            ch_adapter, "clickhouse", ch_config.name
        )
        catalog = discoverer.discover(sample_rows=2)
        assert catalog.database_type == "clickhouse"
        assert catalog.connection_name == "ch_test"
        assert catalog.read_only is True
        assert len(catalog.tables) >= 0
        for t in catalog.tables:
            assert t.foreign_keys == []
