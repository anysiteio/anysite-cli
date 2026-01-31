"""Tests for insert operations."""

import io

import pytest

from anysite.db.adapters.sqlite import SQLiteAdapter
from anysite.db.config import ConnectionConfig, DatabaseType, OnConflict
from anysite.db.operations.insert import _read_json_stream, insert_from_stream


@pytest.fixture
def adapter():
    config = ConnectionConfig(name="test", type=DatabaseType.SQLITE, path=":memory:")
    a = SQLiteAdapter(config)
    a.connect()
    yield a
    a.disconnect()


class TestReadJsonStream:
    def test_json_array(self):
        stream = io.StringIO('[{"a": 1}, {"b": 2}]')
        rows = _read_json_stream(stream)
        assert len(rows) == 2
        assert rows[0] == {"a": 1}

    def test_single_json_object(self):
        stream = io.StringIO('{"name": "test", "value": 42}')
        rows = _read_json_stream(stream)
        assert len(rows) == 1
        assert rows[0]["name"] == "test"

    def test_jsonl(self):
        stream = io.StringIO('{"a": 1}\n{"b": 2}\n{"c": 3}\n')
        rows = _read_json_stream(stream)
        assert len(rows) == 3

    def test_empty_stream(self):
        stream = io.StringIO("")
        rows = _read_json_stream(stream)
        assert rows == []

    def test_blank_lines_skipped(self):
        stream = io.StringIO('{"a": 1}\n\n{"b": 2}\n\n')
        rows = _read_json_stream(stream)
        assert len(rows) == 2

    def test_non_dict_filtered(self):
        stream = io.StringIO('[1, 2, {"a": 3}]')
        rows = _read_json_stream(stream)
        assert len(rows) == 1
        assert rows[0] == {"a": 3}

    def test_invalid_json_lines_skipped(self):
        stream = io.StringIO('{"a": 1}\nnot json\n{"b": 2}\n')
        rows = _read_json_stream(stream)
        assert len(rows) == 2


class TestInsertFromStream:
    def test_insert_jsonl(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        stream = io.StringIO('{"id": 1, "name": "alice"}\n{"id": 2, "name": "bob"}\n')
        count = insert_from_stream(adapter, "test", stream)
        assert count == 2

        rows = adapter.fetch_all("SELECT * FROM test ORDER BY id")
        assert rows[0]["name"] == "alice"
        assert rows[1]["name"] == "bob"

    def test_insert_json_array(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        stream = io.StringIO('[{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]')
        count = insert_from_stream(adapter, "test", stream)
        assert count == 2

    def test_insert_empty_stream(self, adapter):
        count = insert_from_stream(adapter, "test", io.StringIO(""))
        assert count == 0

    def test_auto_create_table(self, adapter):
        stream = io.StringIO('{"id": 1, "name": "alice", "score": 9.5}')
        count = insert_from_stream(
            adapter, "demo", stream, auto_create=True, quiet=True
        )
        assert count == 1
        assert adapter.table_exists("demo")

        schema = adapter.get_table_schema("demo")
        assert len(schema) == 3

    def test_auto_create_with_pk(self, adapter):
        stream = io.StringIO('{"id": 1, "name": "alice"}')
        insert_from_stream(
            adapter, "demo", stream, auto_create=True, primary_key="id", quiet=True
        )
        schema = adapter.get_table_schema("demo")
        id_col = next(c for c in schema if c["name"] == "id")
        assert id_col["primary_key"] == "YES"

    def test_insert_with_upsert(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        stream1 = io.StringIO('{"id": 1, "name": "alice"}')
        insert_from_stream(adapter, "test", stream1)

        stream2 = io.StringIO('{"id": 1, "name": "alice_updated"}')
        insert_from_stream(
            adapter,
            "test",
            stream2,
            on_conflict=OnConflict.UPDATE,
            conflict_columns=["id"],
        )

        row = adapter.fetch_one("SELECT * FROM test WHERE id = 1")
        assert row["name"] == "alice_updated"

    def test_batch_size(self, adapter):
        adapter.execute("CREATE TABLE test (id INTEGER)")
        data = "\n".join(f'{{"id": {i}}}' for i in range(250))
        stream = io.StringIO(data)
        count = insert_from_stream(adapter, "test", stream, batch_size=50)
        assert count == 250
        rows = adapter.fetch_all("SELECT COUNT(*) as cnt FROM test")
        assert rows[0]["cnt"] == 250
