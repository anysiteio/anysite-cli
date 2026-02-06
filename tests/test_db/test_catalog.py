"""Tests for catalog store (YAML persistence)."""

import pytest

from anysite.db.catalog import CatalogStore
from anysite.db.discovery import (
    ColumnInfo,
    DatabaseCatalog,
    ForeignKeyInfo,
    ImplicitRelationship,
    IndexInfo,
    TableInfo,
)


@pytest.fixture
def store(tmp_path):
    return CatalogStore(catalogs_dir=tmp_path)


@pytest.fixture
def sample_catalog():
    return DatabaseCatalog(
        connection_name="testdb",
        database_type="sqlite",
        server_info={"type": "sqlite", "version": "3.40.0"},
        tables=[
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(name="id", type="INTEGER", primary_key=True, nullable=False),
                    ColumnInfo(name="name", type="TEXT", nullable=False),
                    ColumnInfo(name="email", type="TEXT", description="User email"),
                ],
                row_count=100,
                sample_rows=[{"id": 1, "name": "Alice", "email": "alice@example.com"}],
                indexes=[IndexInfo(name="idx_email", columns=["email"], unique=True)],
                foreign_keys=[],
                description="User accounts",
            ),
            TableInfo(
                name="posts",
                columns=[
                    ColumnInfo(name="id", type="INTEGER", primary_key=True),
                    ColumnInfo(name="user_id", type="INTEGER"),
                    ColumnInfo(name="title", type="TEXT"),
                ],
                row_count=500,
                foreign_keys=[
                    ForeignKeyInfo(
                        constrained_columns=["user_id"],
                        referred_table="users",
                        referred_columns=["id"],
                    )
                ],
                description="Blog posts",
            ),
        ],
        discovered_at="2026-02-06T14:00:00+00:00",
        description="Test database",
        llm_enriched=True,
        implicit_relationships=[
            ImplicitRelationship(
                from_table="posts",
                from_column="author_id",
                to_table="users",
                to_column="id",
                confidence=0.85,
                reason="Naming convention",
            )
        ],
    )


class TestCatalogStore:
    def test_save_and_load(self, store, sample_catalog):
        path = store.save(sample_catalog)
        assert path.exists()
        assert path.suffix == ".yaml"

        loaded = store.load("testdb")
        assert loaded is not None
        assert loaded.connection_name == "testdb"
        assert loaded.database_type == "sqlite"
        assert loaded.llm_enriched is True
        assert loaded.description == "Test database"
        assert len(loaded.tables) == 2

    def test_load_nonexistent(self, store):
        assert store.load("nonexistent") is None

    def test_save_overwrites(self, store, sample_catalog):
        store.save(sample_catalog)
        sample_catalog.description = "Updated description"
        store.save(sample_catalog)
        loaded = store.load("testdb")
        assert loaded.description == "Updated description"

    def test_list_empty(self, store):
        assert store.list() == []

    def test_list_catalogs(self, store, sample_catalog):
        store.save(sample_catalog)

        # Save a second catalog
        catalog2 = DatabaseCatalog(
            connection_name="proddb",
            database_type="postgres",
            server_info={},
            tables=[TableInfo(name="orders", columns=[])],
            discovered_at="2026-02-06T15:00:00+00:00",
        )
        store.save(catalog2)

        catalogs = store.list()
        assert len(catalogs) == 2
        names = {c["name"] for c in catalogs}
        assert "testdb" in names
        assert "proddb" in names

        proddb = next(c for c in catalogs if c["name"] == "proddb")
        assert proddb["database_type"] == "postgres"
        assert proddb["table_count"] == "1"

    def test_remove(self, store, sample_catalog):
        store.save(sample_catalog)
        assert store.remove("testdb") is True
        assert store.load("testdb") is None

    def test_remove_nonexistent(self, store):
        assert store.remove("nonexistent") is False

    def test_preserves_columns(self, store, sample_catalog):
        store.save(sample_catalog)
        loaded = store.load("testdb")
        users = loaded.get_table("users")
        assert users is not None
        assert len(users.columns) == 3
        email_col = next(c for c in users.columns if c.name == "email")
        assert email_col.description == "User email"

    def test_preserves_indexes(self, store, sample_catalog):
        store.save(sample_catalog)
        loaded = store.load("testdb")
        users = loaded.get_table("users")
        assert len(users.indexes) == 1
        assert users.indexes[0].name == "idx_email"
        assert users.indexes[0].unique is True

    def test_preserves_foreign_keys(self, store, sample_catalog):
        store.save(sample_catalog)
        loaded = store.load("testdb")
        posts = loaded.get_table("posts")
        assert len(posts.foreign_keys) == 1
        fk = posts.foreign_keys[0]
        assert fk.referred_table == "users"

    def test_preserves_implicit_relationships(self, store, sample_catalog):
        store.save(sample_catalog)
        loaded = store.load("testdb")
        assert len(loaded.implicit_relationships) == 1
        rel = loaded.implicit_relationships[0]
        assert rel.from_table == "posts"
        assert rel.confidence == 0.85

    def test_preserves_sample_rows(self, store, sample_catalog):
        store.save(sample_catalog)
        loaded = store.load("testdb")
        users = loaded.get_table("users")
        assert len(users.sample_rows) == 1
        assert users.sample_rows[0]["name"] == "Alice"

    def test_preserves_server_info(self, store, sample_catalog):
        store.save(sample_catalog)
        loaded = store.load("testdb")
        assert loaded.server_info["type"] == "sqlite"
        assert loaded.server_info["version"] == "3.40.0"

    def test_list_with_no_directory(self, tmp_path):
        store = CatalogStore(catalogs_dir=tmp_path / "nonexistent")
        assert store.list() == []
