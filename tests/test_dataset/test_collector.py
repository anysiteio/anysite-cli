"""Tests for dataset collector with mocked API."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from anysite.dataset.collector import (
    _extract_values,
    _filter_sources,
    collect_dataset,
)
from anysite.dataset.models import (
    DatasetConfig,
    DatasetSource,
    SourceDependency,
)
from anysite.dataset.storage import read_parquet, write_parquet


class TestExtractValues:
    def test_simple_field(self):
        records = [
            {"urn": "urn:1", "name": "Alice"},
            {"urn": "urn:2", "name": "Bob"},
        ]
        values = _extract_values(records, field="urn", match_by=None, dedupe=False)
        assert values == ["urn:1", "urn:2"]

    def test_nested_field(self):
        records = [
            {"experience": [{"company_urn": "c1"}]},
            {"experience": [{"company_urn": "c2"}]},
        ]
        values = _extract_values(records, field="experience[0].company_urn", match_by=None, dedupe=False)
        assert values == ["c1", "c2"]

    def test_dedupe(self):
        records = [
            {"urn": "urn:1"},
            {"urn": "urn:1"},
            {"urn": "urn:2"},
        ]
        values = _extract_values(records, field="urn", match_by=None, dedupe=True)
        assert values == ["urn:1", "urn:2"]

    def test_match_by_uses_field(self):
        records = [{"name": "Alice"}, {"name": "Bob"}]
        values = _extract_values(records, field=None, match_by="name", dedupe=False)
        assert values == ["Alice", "Bob"]

    def test_none_values_skipped(self):
        records = [
            {"urn": "urn:1"},
            {"urn": None},
            {"other": "val"},
        ]
        values = _extract_values(records, field="urn", match_by=None, dedupe=False)
        assert values == ["urn:1"]


class TestFilterSources:
    def test_filter_single(self):
        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="a", endpoint="/api/a"),
                DatasetSource(id="b", endpoint="/api/b"),
            ],
        )
        ordered = config.topological_sort()
        filtered = _filter_sources(ordered, "a", config)
        assert len(filtered) == 1
        assert filtered[0].id == "a"

    def test_filter_with_dependency(self):
        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="parent", endpoint="/api/parent"),
                DatasetSource(
                    id="child",
                    endpoint="/api/child",
                    dependency=SourceDependency(from_source="parent", field="id"),
                    input_key="parent_id",
                ),
                DatasetSource(id="unrelated", endpoint="/api/unrelated"),
            ],
        )
        ordered = config.topological_sort()
        filtered = _filter_sources(ordered, "child", config)
        ids = {s.id for s in filtered}
        assert ids == {"parent", "child"}


class TestCollectDataset:
    @pytest.mark.asyncio
    async def test_independent_source(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(
                    id="profiles",
                    endpoint="/api/test/search",
                    params={"count": 2},
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        mock_response = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(config, quiet=True)

        assert results["profiles"] == 2

        # Verify Parquet was written
        source_dir = tmp_path / "data" / "raw" / "profiles"
        files = list(source_dir.glob("*.parquet"))
        assert len(files) == 1

        records = read_parquet(files[0])
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_dry_run(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="a", endpoint="/api/a"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        results = await collect_dataset(config, dry_run=True, quiet=True)
        assert results == {}

    @pytest.mark.asyncio
    async def test_incremental_skip(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="profiles", endpoint="/api/test"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        # Pre-write data for today
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        today = date.today()
        parquet_path = get_parquet_path(tmp_path / "data", "profiles", today)
        write_parquet([{"id": 1}], parquet_path)
        metadata = MetadataStore(tmp_path / "data")
        metadata.update_source("profiles", 1, today)

        results = await collect_dataset(config, incremental=True, quiet=True)
        assert results["profiles"] == 1  # From metadata, not re-collected
