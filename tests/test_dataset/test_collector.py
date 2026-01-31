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


class TestProvenance:
    @pytest.mark.asyncio
    async def test_dependent_source_has_provenance(self, tmp_path):
        """Dependent source records should have _input_value and _parent_source."""
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="parent", endpoint="/api/parent"),
                DatasetSource(
                    id="child",
                    endpoint="/api/child",
                    dependency=SourceDependency(from_source="parent", field="urn"),
                    input_key="parent_urn",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        # Pre-write parent data for today so incremental=True skips it
        today = date.today()
        parquet_path = get_parquet_path(tmp_path / "data", "parent", today)
        write_parquet(
            [{"urn": "u1", "name": "A"}, {"urn": "u2", "name": "B"}],
            parquet_path,
        )
        metadata = MetadataStore(tmp_path / "data")
        metadata.update_source("parent", 2)

        call_count = 0

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):
                nonlocal call_count
                call_count += 1
                return {"id": call_count, "detail": f"record-{call_count}"}

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            # Use incremental so parent (already collected) is skipped
            results = await collect_dataset(
                config, incremental=True, quiet=True
            )

        assert results["child"] == 2

        child_dir = tmp_path / "data" / "raw" / "child"
        records = read_parquet(child_dir)
        assert len(records) == 2

        for r in records:
            assert "_input_value" in r
            assert "_parent_source" in r
            assert r["_parent_source"] == "parent"

        input_values = {r["_input_value"] for r in records}
        assert input_values == {"u1", "u2"}

    @pytest.mark.asyncio
    async def test_from_file_has_input_value_no_parent_source(self, tmp_path):
        """from_file source records should have _input_value but no _parent_source."""
        input_file = tmp_path / "inputs.txt"
        input_file.write_text("alpha\nbeta\n")

        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(
                    id="items",
                    endpoint="/api/items",
                    from_file="inputs.txt",
                    input_key="name",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        call_count = 0

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):
                nonlocal call_count
                call_count += 1
                return {"id": call_count}

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(
                config, config_dir=tmp_path, quiet=True
            )

        assert results["items"] == 2

        records = read_parquet(tmp_path / "data" / "raw" / "items")
        for r in records:
            assert "_input_value" in r
            assert "_parent_source" not in r

        input_values = {r["_input_value"] for r in records}
        assert input_values == {"alpha", "beta"}

    @pytest.mark.asyncio
    async def test_provenance_input_value_is_raw(self, tmp_path):
        """_input_value should be the raw value, not the templated payload."""
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="parent", endpoint="/api/parent"),
                DatasetSource(
                    id="child",
                    endpoint="/api/child",
                    dependency=SourceDependency(from_source="parent", field="urn"),
                    input_key="urn",
                    input_template={"urn": "urn:li:company:{value}", "count": 5},
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        today = date.today()
        parquet_path = get_parquet_path(tmp_path / "data", "parent", today)
        write_parquet([{"urn": "12345"}], parquet_path)
        metadata = MetadataStore(tmp_path / "data")
        metadata.update_source("parent", 1)

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):
                return {"id": 1}

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            await collect_dataset(config, incremental=True, quiet=True)

        records = read_parquet(tmp_path / "data" / "raw" / "child")
        assert len(records) == 1
        # Raw value "12345", not "urn:li:company:12345"
        assert records[0]["_input_value"] == "12345"


class TestDryRunEstimates:
    @pytest.mark.asyncio
    async def test_independent_shows_1(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[DatasetSource(id="s1", endpoint="/api/s1")],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )
        from anysite.dataset.collector import _build_plan
        from anysite.dataset.storage import MetadataStore

        metadata = MetadataStore(tmp_path / "data")
        plan = _build_plan(
            config.topological_sort(), config, tmp_path / "data",
            metadata, False, date.today(),
        )
        assert plan.steps[0]["estimated_requests"] == 1

    @pytest.mark.asyncio
    async def test_dependent_counts_extracted_values(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="parent", endpoint="/api/parent"),
                DatasetSource(
                    id="child", endpoint="/api/child",
                    dependency=SourceDependency(from_source="parent", field="urn", dedupe=True),
                    input_key="urn",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        # Write 4 parent records, 2 with duplicate urns
        parent_dir = tmp_path / "data" / "raw" / "parent"
        parent_dir.mkdir(parents=True)
        write_parquet(
            [{"urn": "a"}, {"urn": "b"}, {"urn": "a"}, {"urn": "c"}],
            parent_dir / "2026-01-01.parquet",
        )

        from anysite.dataset.collector import _build_plan
        from anysite.dataset.storage import MetadataStore

        metadata = MetadataStore(tmp_path / "data")
        plan = _build_plan(
            config.topological_sort(), config, tmp_path / "data",
            metadata, False, date.today(),
        )
        # child step: 3 unique values (a, b, c) after dedupe
        child_step = [s for s in plan.steps if s["source"] == "child"][0]
        assert child_step["estimated_requests"] == 3

    @pytest.mark.asyncio
    async def test_from_file_counts_lines(self, tmp_path):
        input_file = tmp_path / "inputs.txt"
        input_file.write_text("one\ntwo\nthree\n")

        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(
                    id="items", endpoint="/api/items",
                    from_file=str(input_file), input_key="name",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        from anysite.dataset.collector import _build_plan
        from anysite.dataset.storage import MetadataStore

        metadata = MetadataStore(tmp_path / "data")
        plan = _build_plan(
            config.topological_sort(), config, tmp_path / "data",
            metadata, False, date.today(),
        )
        assert plan.steps[0]["estimated_requests"] == 3


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


class TestIncrementalDedup:
    @pytest.mark.asyncio
    async def test_incremental_skips_collected_inputs(self, tmp_path):
        """Second collect run skips already-fetched input values."""
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="parent", endpoint="/api/parent"),
                DatasetSource(
                    id="child",
                    endpoint="/api/child",
                    dependency=SourceDependency(from_source="parent", field="urn"),
                    input_key="parent_urn",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        today = date.today()
        parquet_path = get_parquet_path(tmp_path / "data", "parent", today)
        write_parquet(
            [{"urn": "u1"}, {"urn": "u2"}, {"urn": "u3"}],
            parquet_path,
        )
        metadata = MetadataStore(tmp_path / "data")
        metadata.update_source("parent", 3)
        # Mark u1 and u2 as already collected
        metadata.update_collected_inputs("child", ["u1", "u2"])

        call_count = 0

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):
                nonlocal call_count
                call_count += 1
                return {"id": call_count, "detail": f"record-{call_count}"}

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(
                config, incremental=True, quiet=True
            )

        # Only u3 should be fetched (u1, u2 already collected)
        assert results["child"] == 1
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_incremental_collects_new_and_saves_inputs(self, tmp_path):
        """New values are collected and saved to metadata for future dedup."""
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(id="parent", endpoint="/api/parent"),
                DatasetSource(
                    id="child",
                    endpoint="/api/child",
                    dependency=SourceDependency(from_source="parent", field="urn"),
                    input_key="parent_urn",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        today = date.today()
        parquet_path = get_parquet_path(tmp_path / "data", "parent", today)
        write_parquet([{"urn": "x1"}, {"urn": "x2"}], parquet_path)
        metadata = MetadataStore(tmp_path / "data")
        metadata.update_source("parent", 2)

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):
                return {"id": 1}

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            await collect_dataset(config, incremental=True, quiet=True)

        # Verify collected inputs were saved
        saved = metadata.get_collected_inputs("child")
        assert "x1" in saved
        assert "x2" in saved

    @pytest.mark.asyncio
    async def test_from_file_incremental_skips_collected(self, tmp_path):
        """from_file source skips already-collected inputs in incremental mode."""
        from anysite.dataset.storage import MetadataStore

        input_file = tmp_path / "inputs.txt"
        input_file.write_text("alpha\nbeta\ngamma\n")

        config = DatasetConfig(
            name="test",
            sources=[
                DatasetSource(
                    id="items",
                    endpoint="/api/items",
                    from_file=str(input_file),
                    input_key="name",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        metadata = MetadataStore(tmp_path / "data")
        metadata.update_collected_inputs("items", ["alpha", "beta"])

        call_count = 0

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):
                nonlocal call_count
                call_count += 1
                return {"id": call_count}

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(
                config, config_dir=tmp_path, incremental=True, quiet=True
            )

        # Only gamma should be fetched
        assert results["items"] == 1
        assert call_count == 1
