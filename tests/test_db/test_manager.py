"""Tests for ConnectionManager."""

import pytest

from anysite.db.config import ConnectionConfig, DatabaseType
from anysite.db.manager import ConnectionManager


@pytest.fixture
def manager(tmp_path):
    """Create a ConnectionManager with a temp connections file."""
    return ConnectionManager(path=tmp_path / "connections.yaml")


@pytest.fixture
def sqlite_config():
    return ConnectionConfig(
        name="testdb",
        type=DatabaseType.SQLITE,
        path=":memory:",
    )


class TestConnectionManager:
    def test_add_and_get(self, manager, sqlite_config):
        manager.add(sqlite_config)
        retrieved = manager.get("testdb")
        assert retrieved is not None
        assert retrieved.name == "testdb"
        assert retrieved.type == DatabaseType.SQLITE

    def test_get_nonexistent(self, manager):
        assert manager.get("nonexistent") is None

    def test_list_empty(self, manager):
        assert manager.list() == []

    def test_list_connections(self, manager, sqlite_config):
        manager.add(sqlite_config)
        connections = manager.list()
        assert len(connections) == 1
        assert connections[0].name == "testdb"

    def test_remove(self, manager, sqlite_config):
        manager.add(sqlite_config)
        assert manager.remove("testdb") is True
        assert manager.get("testdb") is None

    def test_remove_nonexistent(self, manager):
        assert manager.remove("nonexistent") is False

    def test_persistence(self, tmp_path, sqlite_config):
        path = tmp_path / "connections.yaml"

        # Save with one manager
        m1 = ConnectionManager(path=path)
        m1.add(sqlite_config)

        # Load with a fresh manager
        m2 = ConnectionManager(path=path)
        retrieved = m2.get("testdb")
        assert retrieved is not None
        assert retrieved.type == DatabaseType.SQLITE

    def test_update_connection(self, manager):
        config1 = ConnectionConfig(
            name="mydb",
            type=DatabaseType.SQLITE,
            path="./old.db",
        )
        config2 = ConnectionConfig(
            name="mydb",
            type=DatabaseType.SQLITE,
            path="./new.db",
        )
        manager.add(config1)
        manager.add(config2)
        retrieved = manager.get("mydb")
        assert retrieved is not None
        assert retrieved.path == "./new.db"

    def test_multiple_connections(self, manager):
        manager.add(ConnectionConfig(name="db1", type=DatabaseType.SQLITE, path="./a.db"))
        manager.add(ConnectionConfig(name="db2", type=DatabaseType.SQLITE, path="./b.db"))
        assert len(manager.list()) == 2

    def test_test_connection(self, manager, sqlite_config):
        manager.add(sqlite_config)
        info = manager.test("testdb")
        assert info["type"] == "sqlite"
        assert "version" in info

    def test_test_nonexistent(self, manager):
        with pytest.raises(ValueError, match="not found"):
            manager.test("nonexistent")

    def test_get_adapter(self, manager, sqlite_config):
        from anysite.db.adapters.sqlite import SQLiteAdapter

        adapter = manager.get_adapter(sqlite_config)
        assert isinstance(adapter, SQLiteAdapter)

    def test_get_adapter_by_name(self, manager, sqlite_config):
        from anysite.db.adapters.sqlite import SQLiteAdapter

        manager.add(sqlite_config)
        adapter = manager.get_adapter_by_name("testdb")
        assert isinstance(adapter, SQLiteAdapter)

    def test_get_adapter_by_name_nonexistent(self, manager):
        with pytest.raises(ValueError, match="not found"):
            manager.get_adapter_by_name("nonexistent")
