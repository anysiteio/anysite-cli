"""Tests for dataset Parquet storage."""

import json
from datetime import date

import pytest

from anysite.dataset.storage import (
    MetadataStore,
    get_parquet_path,
    get_source_dir,
    read_parquet,
    write_parquet,
)


class TestWriteParquet:
    def test_write_and_read(self, tmp_path):
        records = [
            {"name": "Alice", "age": 30, "city": "SF"},
            {"name": "Bob", "age": 25, "city": "NYC"},
        ]
        path = tmp_path / "test.parquet"
        count = write_parquet(records, path)
        assert count == 2
        assert path.exists()

        result = read_parquet(path)
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["age"] == 25

    def test_write_empty(self, tmp_path):
        path = tmp_path / "empty.parquet"
        count = write_parquet([], path)
        assert count == 0
        assert not path.exists()

    def test_write_nested(self, tmp_path):
        records = [
            {"name": "Alice", "experience": [{"company": "Google"}]},
        ]
        path = tmp_path / "nested.parquet"
        count = write_parquet(records, path)
        assert count == 1

        result = read_parquet(path)
        assert len(result) == 1
        # Nested should be serialized as JSON string
        exp = result[0]["experience"]
        assert isinstance(exp, str)
        parsed = json.loads(exp)
        assert parsed[0]["company"] == "Google"

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "c" / "test.parquet"
        write_parquet([{"x": 1}], path)
        assert path.exists()


class TestReadParquet:
    def test_read_directory(self, tmp_path):
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        write_parquet([{"id": 1, "name": "a"}], source_dir / "2025-01-01.parquet")
        write_parquet([{"id": 2, "name": "b"}], source_dir / "2025-01-02.parquet")

        result = read_parquet(source_dir)
        assert len(result) == 2

    def test_read_nonexistent(self, tmp_path):
        result = read_parquet(tmp_path / "nope.parquet")
        assert result == []

    def test_read_empty_dir(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = read_parquet(empty_dir)
        assert result == []


class TestPaths:
    def test_get_source_dir(self):
        from pathlib import Path

        result = get_source_dir(Path("./data/test"), "linkedin_profiles")
        assert result == Path("./data/test/raw/linkedin_profiles")

    def test_get_parquet_path(self):
        from pathlib import Path

        result = get_parquet_path(Path("./data/test"), "profiles", date(2025, 6, 15))
        assert result == Path("./data/test/raw/profiles/2025-06-15.parquet")


class TestMetadataStore:
    def test_load_empty(self, tmp_path):
        store = MetadataStore(tmp_path)
        data = store.load()
        assert data == {"sources": {}}

    def test_update_and_load(self, tmp_path):
        store = MetadataStore(tmp_path)
        store.update_source("profiles", 100, date(2025, 6, 15))

        data = store.load()
        assert data["sources"]["profiles"]["record_count"] == 100
        assert data["sources"]["profiles"]["last_collected"] == "2025-06-15"
        assert data["last_run"] == "2025-06-15"

    def test_get_source_info(self, tmp_path):
        store = MetadataStore(tmp_path)
        store.update_source("src1", 50)

        info = store.get_source_info("src1")
        assert info is not None
        assert info["record_count"] == 50

        assert store.get_source_info("nonexistent") is None

    def test_get_all_sources(self, tmp_path):
        store = MetadataStore(tmp_path)
        store.update_source("a", 10)
        store.update_source("b", 20)

        all_sources = store.get_all_sources()
        assert len(all_sources) == 2
        assert "a" in all_sources
        assert "b" in all_sources

    def test_update_and_get_collected_inputs(self, tmp_path):
        """Roundtrip: store collected inputs and retrieve them."""
        store = MetadataStore(tmp_path)
        store.update_collected_inputs("src1", ["val_a", "val_b"])

        result = store.get_collected_inputs("src1")
        assert result == {"val_a", "val_b"}

        # Append more, including a duplicate
        store.update_collected_inputs("src1", ["val_b", "val_c"])
        result = store.get_collected_inputs("src1")
        assert result == {"val_a", "val_b", "val_c"}

    def test_get_collected_inputs_empty_source(self, tmp_path):
        """Unknown source returns empty set."""
        store = MetadataStore(tmp_path)
        assert store.get_collected_inputs("nonexistent") == set()
