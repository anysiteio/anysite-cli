"""Tests for db CLI commands."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from anysite.db.catalog import CatalogStore
from anysite.db.cli import app
from anysite.db.config import ConnectionConfig, DatabaseType
from anysite.db.discovery import ColumnInfo, DatabaseCatalog, TableInfo
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

    def test_add_read_only(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        result = runner.invoke(
            app, ["add", "mydb", "--type", "sqlite", "--path", db_path, "--read-only"]
        )
        assert result.exit_code == 0
        config = patch_manager.get("mydb")
        assert config is not None
        assert config.read_only is True

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

    def test_info_read_only(self, patch_manager):
        patch_manager.add(
            ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path="./data.db", read_only=True)
        )
        result = runner.invoke(app, ["info", "mydb"])
        assert result.exit_code == 0
        assert "Read-only" in result.output


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


class TestDiscoverCommand:
    def test_discover(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path)
        patch_manager.add(config)

        from anysite.db.adapters.sqlite import SQLiteAdapter

        with SQLiteAdapter(config) as adapter:
            adapter.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            adapter.execute("INSERT INTO users VALUES (1, 'Alice')")
            adapter.execute("INSERT INTO users VALUES (2, 'Bob')")
            adapter.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT)")
            adapter.execute("INSERT INTO posts VALUES (1, 1, 'Hello')")

        catalogs_dir = tmp_path / "catalogs"
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["discover", "mydb"])

        assert result.exit_code == 0
        assert "Discovered" in result.output
        assert "2 table" in result.output
        assert "users" in result.output
        assert "posts" in result.output

    def test_discover_json(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path)
        patch_manager.add(config)

        from anysite.db.adapters.sqlite import SQLiteAdapter

        with SQLiteAdapter(config) as adapter:
            adapter.execute("CREATE TABLE demo (id INTEGER, val TEXT)")

        catalogs_dir = tmp_path / "catalogs"
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["discover", "mydb", "--json", "--quiet"])

        assert result.exit_code == 0, result.output
        import json

        data = json.loads(result.output)
        assert data["connection_name"] == "mydb"
        assert len(data["tables"]) == 1

    def test_discover_tables_filter(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(name="mydb", type=DatabaseType.SQLITE, path=db_path)
        patch_manager.add(config)

        from anysite.db.adapters.sqlite import SQLiteAdapter

        with SQLiteAdapter(config) as adapter:
            adapter.execute("CREATE TABLE users (id INTEGER)")
            adapter.execute("CREATE TABLE posts (id INTEGER)")
            adapter.execute("CREATE TABLE logs (id INTEGER)")

        catalogs_dir = tmp_path / "catalogs"
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["discover", "mydb", "--tables", "users,posts"])

        assert result.exit_code == 0
        assert "2 table" in result.output

    def test_discover_force_read_only(self, patch_manager, tmp_path):
        db_path = str(tmp_path / "test.db")
        config = ConnectionConfig(
            name="mydb", type=DatabaseType.SQLITE, path=db_path, read_only=True,
        )
        patch_manager.add(config)

        from anysite.db.adapters.sqlite import SQLiteAdapter

        with SQLiteAdapter(config) as adapter:
            adapter.execute("CREATE TABLE demo (id INTEGER)")

        catalogs_dir = tmp_path / "catalogs"
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["discover", "mydb"])

        assert result.exit_code == 0
        assert "read-only" in result.output

    def test_discover_nonexistent(self, patch_manager):  # noqa: ARG002
        result = runner.invoke(app, ["discover", "nope"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCatalogCommand:
    def test_catalog_list_empty(self, tmp_path):
        catalogs_dir = tmp_path / "catalogs"
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["catalog"])
        assert result.exit_code == 0
        assert "No catalogs" in result.output

    def test_catalog_list(self, tmp_path):
        catalogs_dir = tmp_path / "catalogs"
        store = CatalogStore(catalogs_dir)
        store.save(
            DatabaseCatalog(
                connection_name="mydb",
                database_type="sqlite",
                server_info={},
                tables=[TableInfo(name="users", columns=[ColumnInfo(name="id", type="INTEGER")])],
                discovered_at="2026-02-06T14:00:00+00:00",
            )
        )
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["catalog"])
        assert result.exit_code == 0
        assert "mydb" in result.output
        assert "sqlite" in result.output

    def test_catalog_show(self, tmp_path):
        catalogs_dir = tmp_path / "catalogs"
        store = CatalogStore(catalogs_dir)
        store.save(
            DatabaseCatalog(
                connection_name="mydb",
                database_type="sqlite",
                server_info={},
                tables=[
                    TableInfo(
                        name="users",
                        columns=[ColumnInfo(name="id", type="INTEGER", primary_key=True)],
                        row_count=100,
                    )
                ],
                discovered_at="2026-02-06T14:00:00+00:00",
            )
        )
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["catalog", "mydb"])
        assert result.exit_code == 0
        assert "mydb" in result.output
        assert "users" in result.output

    def test_catalog_show_table(self, tmp_path):
        catalogs_dir = tmp_path / "catalogs"
        store = CatalogStore(catalogs_dir)
        store.save(
            DatabaseCatalog(
                connection_name="mydb",
                database_type="sqlite",
                server_info={},
                tables=[
                    TableInfo(
                        name="users",
                        columns=[
                            ColumnInfo(name="id", type="INTEGER", primary_key=True),
                            ColumnInfo(name="name", type="TEXT"),
                        ],
                        row_count=50,
                        sample_rows=[{"id": 1, "name": "Alice"}],
                    )
                ],
                discovered_at="2026-02-06T14:00:00+00:00",
            )
        )
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["catalog", "mydb", "--table", "users"])
        assert result.exit_code == 0
        assert "users" in result.output
        assert "50" in result.output

    def test_catalog_show_json(self, tmp_path):
        catalogs_dir = tmp_path / "catalogs"
        store = CatalogStore(catalogs_dir)
        store.save(
            DatabaseCatalog(
                connection_name="mydb",
                database_type="sqlite",
                server_info={},
                tables=[TableInfo(name="users", columns=[])],
                discovered_at="2026-02-06T14:00:00+00:00",
            )
        )
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["catalog", "mydb", "--json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert data["connection_name"] == "mydb"

    def test_catalog_nonexistent(self, tmp_path):
        catalogs_dir = tmp_path / "catalogs"
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["catalog", "nope"])
        assert result.exit_code == 1
        assert "no catalog" in result.output

    def test_catalog_table_nonexistent(self, tmp_path):
        catalogs_dir = tmp_path / "catalogs"
        store = CatalogStore(catalogs_dir)
        store.save(
            DatabaseCatalog(
                connection_name="mydb",
                database_type="sqlite",
                server_info={},
                tables=[TableInfo(name="users", columns=[])],
                discovered_at="",
            )
        )
        with patch("anysite.db.cli._get_catalog_store", lambda: CatalogStore(catalogs_dir)):
            result = runner.invoke(app, ["catalog", "mydb", "--table", "nope"])
        assert result.exit_code == 1
        assert "not in catalog" in result.output
