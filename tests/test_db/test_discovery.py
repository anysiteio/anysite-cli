"""Tests for database discovery engine."""

import pytest

from anysite.db.adapters.sqlite import SQLiteAdapter
from anysite.db.config import ConnectionConfig, DatabaseType
from anysite.db.discovery import (
    ColumnInfo,
    DatabaseCatalog,
    DatabaseDiscoverer,
    ForeignKeyInfo,
    ImplicitRelationship,
    IndexInfo,
    TableInfo,
)


@pytest.fixture
def config():
    return ConnectionConfig(name="test", type=DatabaseType.SQLITE, path=":memory:")


@pytest.fixture
def adapter(config):
    a = SQLiteAdapter(config)
    a.connect()
    yield a
    a.disconnect()


@pytest.fixture
def seeded_adapter(adapter):
    """Adapter with users and posts tables."""
    adapter.execute(
        "CREATE TABLE users ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  email TEXT,"
        "  created_at TEXT DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    adapter.execute(
        "CREATE TABLE posts ("
        "  id INTEGER PRIMARY KEY,"
        "  user_id INTEGER NOT NULL,"
        "  title TEXT,"
        "  body TEXT,"
        "  FOREIGN KEY (user_id) REFERENCES users(id)"
        ")"
    )
    adapter.execute("CREATE INDEX idx_posts_user_id ON posts(user_id)")
    adapter.execute("CREATE UNIQUE INDEX idx_users_email ON users(email)")

    # Insert sample data
    adapter.execute("INSERT INTO users (id, name, email) VALUES (1, 'Alice', 'alice@example.com')")
    adapter.execute("INSERT INTO users (id, name, email) VALUES (2, 'Bob', 'bob@example.com')")
    adapter.execute("INSERT INTO posts (id, user_id, title, body) VALUES (1, 1, 'Hello', 'World')")
    adapter.execute("INSERT INTO posts (id, user_id, title, body) VALUES (2, 1, 'Foo', 'Bar')")
    adapter.execute("INSERT INTO posts (id, user_id, title, body) VALUES (3, 2, 'Test', 'Post')")

    return adapter


class TestColumnInfo:
    def test_to_dict_minimal(self):
        col = ColumnInfo(name="id", type="INTEGER")
        d = col.to_dict()
        assert d == {"name": "id", "type": "INTEGER"}

    def test_to_dict_full(self):
        col = ColumnInfo(
            name="id", type="INTEGER", nullable=False,
            primary_key=True, default="0", description="Primary key"
        )
        d = col.to_dict()
        assert d["primary_key"] is True
        assert d["nullable"] is False
        assert d["default"] == "0"
        assert d["description"] == "Primary key"

    def test_roundtrip(self):
        col = ColumnInfo(name="email", type="TEXT", nullable=True, description="User email")
        restored = ColumnInfo.from_dict(col.to_dict())
        assert restored.name == col.name
        assert restored.type == col.type
        assert restored.description == col.description


class TestIndexInfo:
    def test_to_dict(self):
        idx = IndexInfo(name="idx_users_email", columns=["email"], unique=True)
        d = idx.to_dict()
        assert d["name"] == "idx_users_email"
        assert d["unique"] is True

    def test_roundtrip(self):
        idx = IndexInfo(name="idx", columns=["a", "b"], unique=False)
        restored = IndexInfo.from_dict(idx.to_dict())
        assert restored.columns == ["a", "b"]
        assert restored.unique is False


class TestForeignKeyInfo:
    def test_to_dict(self):
        fk = ForeignKeyInfo(
            constrained_columns=["user_id"],
            referred_table="users",
            referred_columns=["id"],
            name="fk_posts_user",
        )
        d = fk.to_dict()
        assert d["referred_table"] == "users"
        assert d["name"] == "fk_posts_user"

    def test_roundtrip(self):
        fk = ForeignKeyInfo(
            constrained_columns=["a_id"],
            referred_table="a",
            referred_columns=["id"],
        )
        restored = ForeignKeyInfo.from_dict(fk.to_dict())
        assert restored.constrained_columns == ["a_id"]
        assert restored.name is None


class TestImplicitRelationship:
    def test_roundtrip(self):
        r = ImplicitRelationship(
            from_table="posts",
            from_column="author_id",
            to_table="users",
            to_column="id",
            confidence=0.9,
            reason="Naming convention",
        )
        restored = ImplicitRelationship.from_dict(r.to_dict())
        assert restored.from_table == "posts"
        assert restored.confidence == 0.9


class TestTableInfo:
    def test_to_dict(self):
        t = TableInfo(
            name="users",
            columns=[ColumnInfo(name="id", type="INTEGER", primary_key=True)],
            row_count=100,
            sample_rows=[{"id": 1}],
            indexes=[IndexInfo(name="pk", columns=["id"], unique=True)],
            foreign_keys=[],
            description="User accounts",
        )
        d = t.to_dict()
        assert d["name"] == "users"
        assert d["row_count"] == 100
        assert len(d["columns"]) == 1
        assert d["description"] == "User accounts"

    def test_roundtrip(self):
        t = TableInfo(
            name="posts",
            columns=[
                ColumnInfo(name="id", type="INTEGER", primary_key=True),
                ColumnInfo(name="user_id", type="INTEGER"),
            ],
            row_count=50,
            foreign_keys=[
                ForeignKeyInfo(
                    constrained_columns=["user_id"],
                    referred_table="users",
                    referred_columns=["id"],
                )
            ],
        )
        restored = TableInfo.from_dict(t.to_dict())
        assert restored.name == "posts"
        assert len(restored.columns) == 2
        assert len(restored.foreign_keys) == 1


class TestDatabaseCatalog:
    def test_to_dict_and_from_dict(self):
        catalog = DatabaseCatalog(
            connection_name="mydb",
            database_type="sqlite",
            server_info={"version": "3.40.0"},
            tables=[
                TableInfo(
                    name="users",
                    columns=[ColumnInfo(name="id", type="INTEGER")],
                    row_count=10,
                )
            ],
            discovered_at="2026-02-06T14:00:00+00:00",
            description="Test DB",
            llm_enriched=True,
        )
        d = catalog.to_dict()
        restored = DatabaseCatalog.from_dict(d)
        assert restored.connection_name == "mydb"
        assert restored.llm_enriched is True
        assert len(restored.tables) == 1
        assert restored.description == "Test DB"

    def test_get_table(self):
        catalog = DatabaseCatalog(
            connection_name="test",
            database_type="sqlite",
            server_info={},
            tables=[
                TableInfo(name="users", columns=[]),
                TableInfo(name="posts", columns=[]),
            ],
            discovered_at="",
        )
        assert catalog.get_table("users") is not None
        assert catalog.get_table("users").name == "users"
        assert catalog.get_table("nonexistent") is None

    def test_to_context_string(self):
        catalog = DatabaseCatalog(
            connection_name="mydb",
            database_type="sqlite",
            server_info={},
            tables=[
                TableInfo(
                    name="users",
                    columns=[
                        ColumnInfo(name="id", type="INTEGER", primary_key=True, nullable=False),
                        ColumnInfo(name="name", type="TEXT"),
                    ],
                    row_count=100,
                    description="User accounts",
                    foreign_keys=[],
                )
            ],
            discovered_at="",
            description="Main database",
        )
        ctx = catalog.to_context_string()
        assert "Database: mydb (sqlite)" in ctx
        assert "Description: Main database" in ctx
        assert "Table: users (100 rows)" in ctx
        assert "id: INTEGER PK NOT NULL" in ctx

    def test_to_context_string_with_fks(self):
        catalog = DatabaseCatalog(
            connection_name="test",
            database_type="sqlite",
            server_info={},
            tables=[
                TableInfo(
                    name="posts",
                    columns=[ColumnInfo(name="user_id", type="INTEGER")],
                    foreign_keys=[
                        ForeignKeyInfo(
                            constrained_columns=["user_id"],
                            referred_table="users",
                            referred_columns=["id"],
                        )
                    ],
                )
            ],
            discovered_at="",
        )
        ctx = catalog.to_context_string()
        assert "FK: user_id" in ctx
        assert "users(id)" in ctx

    def test_to_context_string_with_implicit_rels(self):
        catalog = DatabaseCatalog(
            connection_name="test",
            database_type="sqlite",
            server_info={},
            tables=[],
            discovered_at="",
            implicit_relationships=[
                ImplicitRelationship(
                    from_table="posts",
                    from_column="author_id",
                    to_table="users",
                    to_column="id",
                    reason="naming",
                )
            ],
        )
        ctx = catalog.to_context_string()
        assert "Implicit relationships:" in ctx
        assert "posts.author_id" in ctx


class TestDatabaseDiscoverer:
    def test_discover_empty_db(self, adapter):
        discoverer = DatabaseDiscoverer(adapter, "sqlite", "test")
        catalog = discoverer.discover()
        assert catalog.connection_name == "test"
        assert catalog.database_type == "sqlite"
        assert len(catalog.tables) == 0
        assert catalog.discovered_at  # non-empty

    def test_discover_tables(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover()
        assert len(catalog.tables) == 2
        table_names = [t.name for t in catalog.tables]
        assert "users" in table_names
        assert "posts" in table_names

    def test_discover_columns(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover()
        users = catalog.get_table("users")
        assert users is not None
        col_names = [c.name for c in users.columns]
        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names
        assert "created_at" in col_names

        id_col = next(c for c in users.columns if c.name == "id")
        assert id_col.primary_key is True
        assert id_col.type == "INTEGER"

        name_col = next(c for c in users.columns if c.name == "name")
        assert name_col.nullable is False

    def test_discover_row_counts(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover()
        users = catalog.get_table("users")
        assert users.row_count == 2
        posts = catalog.get_table("posts")
        assert posts.row_count == 3

    def test_discover_sample_rows(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover(sample_rows=2)
        users = catalog.get_table("users")
        assert len(users.sample_rows) == 2
        assert "name" in users.sample_rows[0]

    def test_discover_sample_rows_zero(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover(sample_rows=0)
        users = catalog.get_table("users")
        assert len(users.sample_rows) == 0

    def test_discover_indexes(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover()
        users = catalog.get_table("users")
        idx_names = [i.name for i in users.indexes]
        assert "idx_users_email" in idx_names

        email_idx = next(i for i in users.indexes if i.name == "idx_users_email")
        assert email_idx.unique is True
        assert "email" in email_idx.columns

    def test_discover_foreign_keys(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover()
        posts = catalog.get_table("posts")
        assert len(posts.foreign_keys) == 1
        fk = posts.foreign_keys[0]
        assert fk.constrained_columns == ["user_id"]
        assert fk.referred_table == "users"
        assert fk.referred_columns == ["id"]

    def test_discover_include_tables(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover(include_tables=["users"])
        assert len(catalog.tables) == 1
        assert catalog.tables[0].name == "users"

    def test_discover_exclude_tables(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover(exclude_tables=["posts"])
        assert len(catalog.tables) == 1
        assert catalog.tables[0].name == "users"

    def test_discover_server_info(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover()
        assert "type" in catalog.server_info
        assert catalog.server_info["type"] == "sqlite"

    def test_discover_force_read_only(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover(force_read_only=True)
        assert catalog.read_only is True

    def test_discover_auto_read_only(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover()
        # In-memory SQLite is always writable
        assert catalog.read_only is False

    def test_catalog_serialization_roundtrip(self, seeded_adapter):
        discoverer = DatabaseDiscoverer(seeded_adapter, "sqlite", "test")
        catalog = discoverer.discover()
        d = catalog.to_dict()
        restored = DatabaseCatalog.from_dict(d)
        assert restored.connection_name == catalog.connection_name
        assert len(restored.tables) == len(catalog.tables)
        for orig, rest in zip(catalog.tables, restored.tables, strict=True):
            assert orig.name == rest.name
            assert orig.row_count == rest.row_count
            assert len(orig.columns) == len(rest.columns)
