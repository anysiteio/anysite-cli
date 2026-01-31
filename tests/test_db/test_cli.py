"""Tests for db CLI commands."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from anysite.db.cli import app
from anysite.db.config import ConnectionConfig, DatabaseType
from anysite.db.manager import ConnectionManager

runner = CliRunner()


@pytest.fixture
def manager(tmp_path):
    """Create a temp ConnectionManager."""
    return ConnectionManager(path=tmp_path / "connections.yaml")


@pytest.fixture
def patch_manager(manager):
    """Patch _get_manager to return our temp manager."""
    with patch("anysite.db.cli._get_manager", return_value=manager):
        yield manager


class TestAddCommand:
    def test_add_sqlite(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        result = runner.invoke(app, ["add", "mydb", "--type", "sqlite", "--path", db_path])
        assert result.exit_code == 0
        assert "Added" in result.output
        assert patch_manager.get("mydb") is not None

    def test_add_missing_path(self, patch_manager):  # noqa: ARG002
        result = runner.invoke(app, ["add", "mydb", "--type", "sqlite"])
        assert result.exit_code == 1
        assert "Error" in result.output


class TestListCommand:
    def test_list_empty(self, patch_manager):  # noqa: ARG002
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No connections" in result.output

    def test_list_with_connections(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        patch_manager.add(ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path))
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "mydb" in result.output


class TestTestCommand:
    def test_test_sqlite(self, patch_manager):
        patch_manager.add(
            ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=":memory:")
        )
        result = runner.invoke(app, ["test", "mydb"])
        assert result.exit_code == 0
        assert "Connected" in result.output

    def test_test_nonexistent(self, patch_manager):  # noqa: ARG002
        result = runner.invoke(app, ["test", "nope"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestRemoveCommand:
    def test_remove(self, patch_manager):
        patch_manager.add(
            ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=":memory:")
        )
        result = runner.invoke(app, ["remove", "mydb", "--force"])
        assert result.exit_code == 0
        assert "Removed" in result.output
        assert patch_manager.get("mydb") is None

    def test_remove_nonexistent(self, patch_manager):  # noqa: ARG002
        result = runner.invoke(app, ["remove", "nope", "--force"])
        assert result.exit_code == 1


class TestInfoCommand:
    def test_info(self, patch_manager):
        patch_manager.add(
            ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path="./data.db")
        )
        result = runner.invoke(app, ["info", "mydb"])
        assert result.exit_code == 0
        assert "sqlite" in result.output
        assert "./data.db" in result.output


class TestInsertCommand:
    def test_insert_stdin(self, patch_manager):
        patch_manager.add(
            ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=":memory:")
        )
        input_data = '{"id": 1, "name": "test"}\n'
        result = runner.invoke(
            app,
            ["insert", "mydb", "--table", "demo", "--stdin", "--auto-create"],
            input=input_data,
        )
        assert result.exit_code == 0
        assert "Inserted" in result.output
        assert "1 row" in result.output

    def test_insert_no_source(self, patch_manager):
        patch_manager.add(
            ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=":memory:")
        )
        result = runner.invoke(app, ["insert", "mydb", "--table", "demo"])
        assert result.exit_code == 1
        assert "provide --stdin or --file" in result.output


class TestQueryCommand:
    def test_query(self, patch_manager):
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=":memory:")
        patch_manager.add(config)

        # Pre-populate via adapter
        from anysite.db.adapters.sqlite import SQLiteAdapter

        adapter = SQLiteAdapter(config)
        with adapter:
            adapter.execute("CREATE TABLE demo (id INTEGER, name TEXT)")
            adapter.execute("INSERT INTO demo VALUES (1, 'alice')")

        # The query command creates a new adapter, so for in-memory DBs
        # the data won't persist. Use a file-based db instead.

    def test_query_no_sql(self, patch_manager):
        patch_manager.add(
            ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=":memory:")
        )
        result = runner.invoke(app, ["query", "mydb"])
        assert result.exit_code == 1
        assert "provide --sql or --file" in result.output

    def test_query_file_db(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path)
        patch_manager.add(config)

        # Pre-populate
        from anysite.db.adapters.sqlite import SQLiteAdapter

        with SQLiteAdapter(config) as adapter:
            adapter.execute("CREATE TABLE demo (id INTEGER, name TEXT)")
            adapter.execute("INSERT INTO demo VALUES (1, 'alice')")
            adapter.execute("INSERT INTO demo VALUES (2, 'bob')")

        result = runner.invoke(
            app,
            ["query", "mydb", "--sql", "SELECT * FROM demo ORDER BY id", "--format", "json"],
        )
        assert result.exit_code == 0
        assert "alice" in result.output
        assert "bob" in result.output


class TestSchemaCommand:
    def test_schema_list_tables(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path)
        patch_manager.add(config)

        from anysite.db.adapters.sqlite import SQLiteAdapter

        with SQLiteAdapter(config) as adapter:
            adapter.execute("CREATE TABLE users (id INTEGER, name TEXT)")
            adapter.execute("CREATE TABLE orders (id INTEGER)")

        result = runner.invoke(app, ["schema", "mydb"])
        assert result.exit_code == 0
        assert "users" in result.output
        assert "orders" in result.output

    def test_schema_table_detail(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path)
        patch_manager.add(config)

        from anysite.db.adapters.sqlite import SQLiteAdapter

        with SQLiteAdapter(config) as adapter:
            adapter.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")

        result = runner.invoke(app, ["schema", "mydb", "--table", "users"])
        assert result.exit_code == 0
        assert "id" in result.output
        assert "name" in result.output


class TestCreateTableCommand:
    def test_create_table_dry_run(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path)
        patch_manager.add(config)

        input_data = '{"id": 1, "name": "test", "score": 9.5}\n'
        result = runner.invoke(
            app,
            ["create-table", "mydb", "--table", "demo", "--stdin", "--dry-run"],
            input=input_data,
        )
        assert result.exit_code == 0
        assert "CREATE TABLE" in result.output
        assert "id" in result.output

    def test_create_table(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path)
        patch_manager.add(config)

        input_data = '{"id": 1, "name": "test"}\n'
        result = runner.invoke(
            app,
            ["create-table", "mydb", "--table", "demo", "--stdin"],
            input=input_data,
        )
        assert result.exit_code == 0
        assert "Created" in result.output
