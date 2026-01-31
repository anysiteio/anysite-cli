"""Tests for dataset DuckDB analyzer."""

import pytest

from anysite.dataset.analyzer import DatasetAnalyzer
from anysite.dataset.models import DatasetConfig, DatasetSource, StorageConfig
from anysite.dataset.storage import get_source_dir, write_parquet


def _make_config(tmp_path, sources_data=None):
    """Create a test config with Parquet data on disk."""
    data_path = tmp_path / "data"

    if sources_data is None:
        sources_data = {
            "profiles": [
                {"id": 1, "name": "Alice", "age": 30, "city": "SF"},
                {"id": 2, "name": "Bob", "age": 25, "city": "NYC"},
                {"id": 3, "name": "Carol", "age": None, "city": "SF"},
            ],
        }

    sources = []
    for source_id, records in sources_data.items():
        sources.append(DatasetSource(id=source_id, endpoint=f"/api/{source_id}"))
        source_dir = get_source_dir(data_path, source_id)
        write_parquet(records, source_dir / "2025-01-01.parquet")

    return DatasetConfig(
        name="test",
        sources=sources,
        storage=StorageConfig(path=str(data_path)),
    )


class TestQuery:
    def test_simple_select(self, tmp_path):
        config = _make_config(tmp_path)
        with DatasetAnalyzer(config) as analyzer:
            results = analyzer.query("SELECT * FROM profiles ORDER BY id")
        assert len(results) == 3
        assert results[0]["name"] == "Alice"

    def test_aggregate(self, tmp_path):
        config = _make_config(tmp_path)
        with DatasetAnalyzer(config) as analyzer:
            results = analyzer.query(
                "SELECT city, COUNT(*) as cnt FROM profiles GROUP BY city ORDER BY cnt DESC"
            )
        assert len(results) == 2
        assert results[0]["city"] == "SF"
        assert results[0]["cnt"] == 2

    def test_count(self, tmp_path):
        config = _make_config(tmp_path)
        with DatasetAnalyzer(config) as analyzer:
            results = analyzer.query("SELECT COUNT(*) as total FROM profiles")
        assert results[0]["total"] == 3


class TestStats:
    def test_column_stats(self, tmp_path):
        config = _make_config(tmp_path)
        with DatasetAnalyzer(config) as analyzer:
            results = analyzer.stats("profiles")

        # Should have stats for each column
        col_names = [r["column"] for r in results]
        assert "id" in col_names
        assert "name" in col_names
        assert "age" in col_names

        # Check age stats (has a null)
        age_stat = next(r for r in results if r["column"] == "age")
        assert age_stat["total"] == 3
        assert age_stat["null_count"] == 1
        assert age_stat["non_null"] == 2


class TestProfile:
    def test_profile_single_source(self, tmp_path):
        config = _make_config(tmp_path)
        with DatasetAnalyzer(config) as analyzer:
            results = analyzer.profile()

        assert len(results) == 1
        assert results[0]["source"] == "profiles"
        assert results[0]["status"] == "ok"
        assert results[0]["records"] == 3

    def test_profile_missing_source(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[DatasetSource(id="missing", endpoint="/api/missing")],
            storage=StorageConfig(path=str(tmp_path / "data")),
        )
        with DatasetAnalyzer(config) as analyzer:
            results = analyzer.profile()

        assert len(results) == 1
        assert results[0]["status"] == "no data"


class TestListViews:
    def test_list_views(self, tmp_path):
        config = _make_config(tmp_path)
        with DatasetAnalyzer(config) as analyzer:
            views = analyzer.list_views()
        assert "profiles" in views
