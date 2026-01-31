"""Tests for database connection configuration."""

import os

import pytest

from anysite.db.config import ConnectionConfig, DatabaseType, OnConflict


class TestConnectionConfig:
    def test_sqlite_config(self):
        config = ConnectionConfig(name="test", type=DatabaseType.SQLITE, path="./test.db")
        assert config.name == "test"
        assert config.type == DatabaseType.SQLITE
        assert config.path == "./test.db"

    def test_sqlite_requires_path(self):
        with pytest.raises(ValueError, match="requires 'path'"):
            ConnectionConfig(name="test", type=DatabaseType.SQLITE)

    def test_postgres_config_with_host(self):
        config = ConnectionConfig(
            name="pg",
            type=DatabaseType.POSTGRES,
            host="localhost",
            port=5432,
            database="testdb",
            user="admin",
            password_env="PG_PASS",
        )
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "testdb"

    def test_postgres_config_with_url_env(self):
        config = ConnectionConfig(
            name="pg",
            type=DatabaseType.POSTGRES,
            url_env="DATABASE_URL",
        )
        assert config.url_env == "DATABASE_URL"

    def test_postgres_requires_host_or_url(self):
        with pytest.raises(ValueError, match="requires 'host' or 'url_env'"):
            ConnectionConfig(name="pg", type=DatabaseType.POSTGRES)

    def test_get_password_from_env(self, monkeypatch):
        monkeypatch.setenv("TEST_DB_PASS", "secret123")
        config = ConnectionConfig(
            name="pg",
            type=DatabaseType.POSTGRES,
            host="localhost",
            password_env="TEST_DB_PASS",
        )
        assert config.get_password() == "secret123"

    def test_get_password_missing_env(self):
        config = ConnectionConfig(
            name="pg",
            type=DatabaseType.POSTGRES,
            host="localhost",
            password_env="NONEXISTENT_VAR_XYZ",
        )
        # Remove the var if it happens to exist
        os.environ.pop("NONEXISTENT_VAR_XYZ", None)
        with pytest.raises(ValueError, match="is not set"):
            config.get_password()

    def test_get_password_none(self):
        config = ConnectionConfig(
            name="pg",
            type=DatabaseType.POSTGRES,
            host="localhost",
        )
        assert config.get_password() is None

    def test_get_url_from_env(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
        config = ConnectionConfig(
            name="pg",
            type=DatabaseType.POSTGRES,
            url_env="DATABASE_URL",
        )
        assert config.get_url() == "postgresql://user:pass@host/db"

    def test_to_dict(self):
        config = ConnectionConfig(
            name="test",
            type=DatabaseType.SQLITE,
            path="./data.db",
        )
        d = config.to_dict()
        assert d == {"type": "sqlite", "path": "./data.db"}
        assert "name" not in d
        assert "host" not in d

    def test_to_dict_postgres(self):
        config = ConnectionConfig(
            name="pg",
            type=DatabaseType.POSTGRES,
            host="localhost",
            port=5432,
            database="testdb",
            user="admin",
            password_env="PG_PASS",
            ssl=True,
        )
        d = config.to_dict()
        assert d["type"] == "postgres"
        assert d["host"] == "localhost"
        assert d["port"] == 5432
        assert d["ssl"] is True

    def test_from_dict(self):
        data = {"type": "sqlite", "path": "./test.db"}
        config = ConnectionConfig.from_dict("mydb", data)
        assert config.name == "mydb"
        assert config.type == DatabaseType.SQLITE
        assert config.path == "./test.db"

    def test_roundtrip(self):
        original = ConnectionConfig(
            name="pg",
            type=DatabaseType.POSTGRES,
            host="db.example.com",
            port=5432,
            database="analytics",
            user="app",
            password_env="DB_PASS",
            ssl=True,
        )
        d = original.to_dict()
        restored = ConnectionConfig.from_dict("pg", d)
        assert restored.name == original.name
        assert restored.type == original.type
        assert restored.host == original.host
        assert restored.port == original.port
        assert restored.ssl == original.ssl


class TestOnConflict:
    def test_values(self):
        assert OnConflict.ERROR == "error"
        assert OnConflict.IGNORE == "ignore"
        assert OnConflict.REPLACE == "replace"
        assert OnConflict.UPDATE == "update"


class TestDatabaseType:
    def test_values(self):
        assert DatabaseType.SQLITE == "sqlite"
        assert DatabaseType.POSTGRES == "postgres"
        assert DatabaseType.MYSQL == "mysql"
        assert DatabaseType.DUCKDB == "duckdb"
