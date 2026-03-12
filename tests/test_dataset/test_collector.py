"""Tests for dataset collector with mocked API."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anysite.dataset.collector import (
    _collect_union,
    _dedupe_records,
    _extract_values,
    _filter_sources,
    collect_dataset,
)
from anysite.dataset.models import (
    ApiSource,
    DatasetConfig,
    LLMStepConfig,
    LlmSource,
    SourceDependency,
    SqlSource,
    UnionSource,
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
                ApiSource(id="a", endpoint="/api/a"),
                ApiSource(id="b", endpoint="/api/b"),
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
                ApiSource(id="parent", endpoint="/api/parent"),
                ApiSource(
                    id="child",
                    endpoint="/api/child",
                    dependency=SourceDependency(from_source="parent", field="id"),
                    input_key="parent_id",
                ),
                ApiSource(id="unrelated", endpoint="/api/unrelated"),
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
                ApiSource(id="parent", endpoint="/api/parent"),
                ApiSource(
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
                ApiSource(
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
                ApiSource(id="parent", endpoint="/api/parent"),
                ApiSource(
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
            sources=[ApiSource(id="s1", endpoint="/api/s1")],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )
        from anysite.dataset.collector import _build_plan
        from anysite.dataset.storage import MetadataStore

        metadata = MetadataStore(tmp_path / "data")
        plan = _build_plan(
            config.topological_sort(), tmp_path / "data",
            metadata, False, date.today(),
        )
        assert plan.steps[0]["estimated_requests"] == 1

    @pytest.mark.asyncio
    async def test_dependent_counts_extracted_values(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="parent", endpoint="/api/parent"),
                ApiSource(
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
            config.topological_sort(), tmp_path / "data",
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
                ApiSource(
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
            config.topological_sort(), tmp_path / "data",
            metadata, False, date.today(),
        )
        assert plan.steps[0]["estimated_requests"] == 3


class TestCollectDataset:
    @pytest.mark.asyncio
    async def test_independent_source(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
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
                ApiSource(id="a", endpoint="/api/a"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        results = await collect_dataset(config, dry_run=True, quiet=True)
        assert "_plan" in results
        assert len(results["_plan"]) == 1
        assert results["_plan"][0]["source"] == "a"
        assert results["_plan"][0]["kind"] == "independent"

    @pytest.mark.asyncio
    async def test_incremental_skip(self, tmp_path):
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="profiles", endpoint="/api/test"),
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


class TestRefreshAlways:
    @pytest.mark.asyncio
    async def test_refresh_always_not_skipped_incremental(self, tmp_path):
        """Source with refresh: always is NOT skipped when incremental=True and data exists."""
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="posts",
                    endpoint="/api/posts",
                    refresh="always",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        # Pre-write data for today
        today = date.today()
        parquet_path = get_parquet_path(tmp_path / "data", "posts", today)
        write_parquet([{"id": 1}], parquet_path)
        metadata = MetadataStore(tmp_path / "data")
        metadata.update_source("posts", 1, today)

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.post.return_value = [{"id": 2, "text": "new"}]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(config, incremental=True, quiet=True)

        # Should have re-collected (not returned old count of 1)
        assert results["posts"] == 1
        # Verify the API was called
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_auto_skipped_incremental(self, tmp_path):
        """Source with refresh: auto (default) IS skipped when incremental=True."""
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="profiles", endpoint="/api/profiles"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        today = date.today()
        parquet_path = get_parquet_path(tmp_path / "data", "profiles", today)
        write_parquet([{"id": 1}], parquet_path)
        metadata = MetadataStore(tmp_path / "data")
        metadata.update_source("profiles", 1, today)

        results = await collect_dataset(config, incremental=True, quiet=True)
        assert results["profiles"] == 1  # From metadata, not re-collected

    @pytest.mark.asyncio
    async def test_refresh_always_no_effect_without_incremental(self, tmp_path):
        """Without --incremental, refresh field has no effect."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="posts",
                    endpoint="/api/posts",
                    refresh="always",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.post.return_value = [{"id": 1}]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(config, incremental=False, quiet=True)

        assert results["posts"] == 1
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_always_dependent_ignores_collected_inputs(self, tmp_path):
        """Dependent source with refresh: always ignores collected_inputs tracking."""
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="parent", endpoint="/api/parent"),
                ApiSource(
                    id="child",
                    endpoint="/api/child",
                    dependency=SourceDependency(from_source="parent", field="urn"),
                    input_key="parent_urn",
                    refresh="always",
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
                return {"id": call_count}

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(
                config, incremental=True, quiet=True
            )

        # All 3 should be collected (refresh: always ignores collected_inputs)
        assert results["child"] == 3
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_refresh_always_from_file_ignores_collected_inputs(self, tmp_path):
        """from_file source with refresh: always ignores collected_inputs tracking."""
        from anysite.dataset.storage import MetadataStore

        input_file = tmp_path / "inputs.txt"
        input_file.write_text("alpha\nbeta\ngamma\n")

        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="items",
                    endpoint="/api/items",
                    from_file=str(input_file),
                    input_key="name",
                    refresh="always",
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

        # All 3 should be collected despite alpha/beta being in collected_inputs
        assert results["items"] == 3
        assert call_count == 3


class TestIncrementalDedup:
    @pytest.mark.asyncio
    async def test_incremental_skips_collected_inputs(self, tmp_path):
        """Second collect run skips already-fetched input values."""
        from anysite.dataset.storage import MetadataStore, get_parquet_path

        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="parent", endpoint="/api/parent"),
                ApiSource(
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
                ApiSource(id="parent", endpoint="/api/parent"),
                ApiSource(
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
                ApiSource(
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


class TestLLMSourceType:
    """Tests for type='llm' sources that process parent data without API calls."""

    @pytest.mark.asyncio
    async def test_collect_llm_reads_parent_data(self, tmp_path):
        """LLM source reads parent Parquet and returns records."""
        from anysite.dataset.collector import _collect_llm
        from anysite.dataset.storage import write_parquet

        # Create parent data
        parent_dir = tmp_path / "data" / "raw" / "profiles"
        parent_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice", "score": 10}, {"name": "Bob", "score": 20}],
            parent_dir / "2026-01-15.parquet",
        )

        # Create LLM source
        source = LlmSource(
            id="profiles_enriched",
            type="llm",
            dependency=SourceDependency(from_source="profiles", field="name"),
            llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
        )

        records = await _collect_llm(source, tmp_path / "data", quiet=True)

        assert len(records) == 2
        assert records[0]["name"] == "Alice"
        assert records[1]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_collect_llm_returns_empty_if_no_parent(self, tmp_path):
        """LLM source returns empty list if parent has no data."""
        from anysite.dataset.collector import _collect_llm

        # No parent data exists
        source = LlmSource(
            id="enriched",
            type="llm",
            dependency=SourceDependency(from_source="missing_parent", field="name"),
            llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
        )

        records = await _collect_llm(source, tmp_path / "data", quiet=True)

        assert records == []

    @pytest.mark.asyncio
    async def test_llm_source_in_topological_order(self, tmp_path):
        """LLM source is correctly ordered after its parent."""
        config = DatasetConfig(
            name="test",
            sources=[
                LlmSource(
                    id="enriched",
                    type="llm",
                    dependency=SourceDependency(from_source="profiles", field="name"),
                    llm=[LLMStepConfig(type="enrich", add=["sentiment:positive/negative"])],
                ),
                ApiSource(id="profiles", endpoint="/api/profiles"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        ordered = config.topological_sort()
        ids = [s.id for s in ordered]

        assert ids.index("profiles") < ids.index("enriched")

    @pytest.mark.asyncio
    async def test_llm_source_dry_run_plan(self, tmp_path):
        """Dry run shows LLM source with correct kind."""
        from datetime import date

        from anysite.dataset.collector import _build_plan
        from anysite.dataset.storage import MetadataStore, write_parquet

        # Create parent data
        parent_dir = tmp_path / "data" / "raw" / "profiles"
        parent_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice"}, {"name": "Bob"}],
            parent_dir / "2026-01-15.parquet",
        )

        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="profiles", endpoint="/api/profiles"),
                LlmSource(
                    id="enriched",
                    type="llm",
                    dependency=SourceDependency(from_source="profiles", field="name"),
                    llm=[LLMStepConfig(type="enrich", add=["score:1-10"])],
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        metadata = MetadataStore(tmp_path / "data")
        plan = _build_plan(
            config.topological_sort(), tmp_path / "data",
            metadata, False, date.today(),
        )

        llm_step = [s for s in plan.steps if s["source"] == "enriched"][0]
        assert llm_step["kind"] == "llm"
        assert llm_step["endpoint"] is None
        assert llm_step["dependency"] == "profiles"
        assert llm_step["llm_steps"] == 1


class TestUnionSourceType:
    """Tests for type='union' sources that combine records from multiple parents."""

    @pytest.mark.asyncio
    async def test_collect_union_combines_records(self, tmp_path):
        """Union source combines records from multiple parent sources."""
        # Create parent data
        search_a_dir = tmp_path / "data" / "raw" / "search_a"
        search_a_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice", "urn": "u1"}],
            search_a_dir / "2026-01-15.parquet",
        )

        search_b_dir = tmp_path / "data" / "raw" / "search_b"
        search_b_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Bob", "urn": "u2"}],
            search_b_dir / "2026-01-15.parquet",
        )

        source = UnionSource(
            id="combined",
            type="union",
            sources=["search_a", "search_b"],
        )

        records = await _collect_union(source, tmp_path / "data", quiet=True)

        assert len(records) == 2
        names = {r["name"] for r in records}
        assert names == {"Alice", "Bob"}
        # Check provenance metadata
        assert all("_union_source" in r for r in records)
        union_sources = {r["_union_source"] for r in records}
        assert union_sources == {"search_a", "search_b"}

    @pytest.mark.asyncio
    async def test_collect_union_with_dedupe(self, tmp_path):
        """Union source with dedupe_by removes duplicates."""
        # Create parent data with overlapping urns
        search_a_dir = tmp_path / "data" / "raw" / "search_a"
        search_a_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice", "urn": "u1"}, {"name": "Charlie", "urn": "u3"}],
            search_a_dir / "2026-01-15.parquet",
        )

        search_b_dir = tmp_path / "data" / "raw" / "search_b"
        search_b_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice2", "urn": "u1"}, {"name": "Bob", "urn": "u2"}],
            search_b_dir / "2026-01-15.parquet",
        )

        source = UnionSource(
            id="combined",
            type="union",
            sources=["search_a", "search_b"],
            dedupe_by="urn",
        )

        records = await _collect_union(source, tmp_path / "data", quiet=True)

        assert len(records) == 3  # u1, u2, u3 (deduplicated)
        urns = {r["urn"] for r in records}
        assert urns == {"u1", "u2", "u3"}
        # First occurrence of u1 should be kept (Alice from search_a)
        u1_record = next(r for r in records if r["urn"] == "u1")
        assert u1_record["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_collect_union_empty_parent(self, tmp_path):
        """Union source handles missing parent data gracefully."""
        # Only create data for one parent
        search_a_dir = tmp_path / "data" / "raw" / "search_a"
        search_a_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice", "urn": "u1"}],
            search_a_dir / "2026-01-15.parquet",
        )

        # search_b has no data

        source = UnionSource(
            id="combined",
            type="union",
            sources=["search_a", "search_b"],
        )

        records = await _collect_union(source, tmp_path / "data", quiet=True)

        assert len(records) == 1
        assert records[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_collect_union_nested_dedupe_field(self, tmp_path):
        """Union source can dedupe by nested field."""
        import json

        # Create parent data with nested urn objects
        search_a_dir = tmp_path / "data" / "raw" / "search_a"
        search_a_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice", "urn": json.dumps({"value": "u1"})}],
            search_a_dir / "2026-01-15.parquet",
        )

        search_b_dir = tmp_path / "data" / "raw" / "search_b"
        search_b_dir.mkdir(parents=True)
        write_parquet(
            [
                {"name": "Alice2", "urn": json.dumps({"value": "u1"})},
                {"name": "Bob", "urn": json.dumps({"value": "u2"})},
            ],
            search_b_dir / "2026-01-15.parquet",
        )

        source = UnionSource(
            id="combined",
            type="union",
            sources=["search_a", "search_b"],
            dedupe_by="urn.value",
        )

        records = await _collect_union(source, tmp_path / "data", quiet=True)

        assert len(records) == 2  # u1 and u2


class TestDedupeRecords:
    """Tests for _dedupe_records helper."""

    def test_dedupe_simple_field(self):
        """Dedupe by simple string field."""
        records = [
            {"name": "Alice", "urn": "u1"},
            {"name": "Bob", "urn": "u2"},
            {"name": "Alice2", "urn": "u1"},  # duplicate
        ]
        result = _dedupe_records(records, "urn")
        assert len(result) == 2
        urns = [r["urn"] for r in result]
        assert urns == ["u1", "u2"]

    def test_dedupe_preserves_order(self):
        """Dedupe preserves first occurrence."""
        records = [
            {"name": "First", "id": "1"},
            {"name": "Second", "id": "2"},
            {"name": "FirstDupe", "id": "1"},
            {"name": "Third", "id": "3"},
        ]
        result = _dedupe_records(records, "id")
        assert len(result) == 3
        assert result[0]["name"] == "First"
        assert result[1]["name"] == "Second"
        assert result[2]["name"] == "Third"


class TestUnionDryRun:
    """Tests for union source in dry-run plan."""

    @pytest.mark.asyncio
    async def test_union_dry_run_plan(self, tmp_path):
        """Dry run shows union source with correct kind and dependencies."""
        from anysite.dataset.collector import _build_plan
        from anysite.dataset.storage import MetadataStore

        # Create parent data
        search_a_dir = tmp_path / "data" / "raw" / "search_a"
        search_a_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice"}, {"name": "Bob"}],
            search_a_dir / "2026-01-15.parquet",
        )

        search_b_dir = tmp_path / "data" / "raw" / "search_b"
        search_b_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Charlie"}],
            search_b_dir / "2026-01-15.parquet",
        )

        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="search_a", endpoint="/api/search"),
                ApiSource(id="search_b", endpoint="/api/search"),
                UnionSource(
                    id="combined",
                    type="union",
                    sources=["search_a", "search_b"],
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        metadata = MetadataStore(tmp_path / "data")
        plan = _build_plan(
            config.topological_sort(), tmp_path / "data",
            metadata, False, date.today(),
        )

        union_step = [s for s in plan.steps if s["source"] == "combined"][0]
        assert union_step["kind"] == "union"
        assert union_step["endpoint"] is None
        assert union_step["dependency"] == "search_a,search_b"
        assert union_step["estimated_requests"] == 3  # 2 + 1 records


class TestFilterSourcesWithUnion:
    """Tests for _filter_sources with union sources."""

    def test_filter_union_includes_parents(self):
        """Filtering by union source includes all parent sources."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="search_a", endpoint="/api/search"),
                ApiSource(id="search_b", endpoint="/api/search"),
                ApiSource(id="unrelated", endpoint="/api/other"),
                UnionSource(
                    id="combined",
                    type="union",
                    sources=["search_a", "search_b"],
                ),
            ],
        )
        ordered = config.topological_sort()
        filtered = _filter_sources(ordered, "combined", config)
        ids = {s.id for s in filtered}
        assert ids == {"search_a", "search_b", "combined"}
        assert "unrelated" not in ids

    def test_filter_dependent_of_union_includes_all(self):
        """Filtering by source that depends on union includes union and its parents."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="search_a", endpoint="/api/search"),
                ApiSource(id="search_b", endpoint="/api/search"),
                UnionSource(
                    id="combined",
                    type="union",
                    sources=["search_a", "search_b"],
                ),
                ApiSource(
                    id="profiles",
                    endpoint="/api/profiles",
                    dependency=SourceDependency(from_source="combined", field="urn"),
                    input_key="user",
                ),
            ],
        )
        ordered = config.topological_sort()
        filtered = _filter_sources(ordered, "profiles", config)
        ids = {s.id for s in filtered}
        assert ids == {"search_a", "search_b", "combined", "profiles"}


# ---------------------------------------------------------------------------
# Source-level filter (before LLM and Parquet)
# ---------------------------------------------------------------------------


class TestSourceFilter:
    @pytest.mark.asyncio
    async def test_source_filter_drops_records_before_parquet(self, tmp_path):
        """source.filter should drop records before Parquet write."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="items",
                    endpoint="/api/items",
                    filter=".score > 50",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                return_value=[
                    {"name": "Alice", "score": 80},
                    {"name": "Bob", "score": 30},
                    {"name": "Carol", "score": 60},
                ]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(config, quiet=True)

        # Only 2 of 3 pass the filter
        assert results["items"] == 2
        records = read_parquet(tmp_path / "data" / "raw" / "items")
        assert len(records) == 2
        names = {r["name"] for r in records}
        assert names == {"Alice", "Carol"}

    @pytest.mark.asyncio
    async def test_source_filter_before_llm(self, tmp_path):
        """source.filter should run before LLM enrichment."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="items",
                    endpoint="/api/items",
                    filter=".is_relevant == 1",
                    llm=[LLMStepConfig(type="enrich", add=["mood:happy/sad"])],
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                return_value=[
                    {"name": "Alice", "is_relevant": 1},
                    {"name": "Bob", "is_relevant": 0},
                ]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            with patch("anysite.dataset.llm_enrichment.enrich_records") as mock_enrich:
                mock_enrich.return_value = [
                    {"name": "Alice", "is_relevant": 1, "mood": "happy"},
                ]
                results = await collect_dataset(config, quiet=True)

                # enrich_records should only receive the filtered record
                mock_enrich.assert_called_once()
                enriched_input = mock_enrich.call_args[0][0]
                assert len(enriched_input) == 1
                assert enriched_input[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_source_filter_none_is_noop(self, tmp_path):
        """When source.filter is None, all records pass through."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="items", endpoint="/api/items"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                return_value=[{"name": "A"}, {"name": "B"}]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(config, quiet=True)

        assert results["items"] == 2

    @pytest.mark.asyncio
    async def test_source_filter_boolean(self, tmp_path):
        """source.filter supports boolean literals."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(
                    id="items",
                    endpoint="/api/items",
                    filter=".is_author == false",
                ),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                return_value=[
                    {"text": "hello", "is_author": True},
                    {"text": "world", "is_author": False},
                    {"text": "test", "is_author": True},
                ]
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(config, quiet=True)

        assert results["items"] == 1
        records = read_parquet(tmp_path / "data" / "raw" / "items")
        assert len(records) == 1
        assert records[0]["text"] == "world"


# ---------------------------------------------------------------------------
# Per-source error handling (skip vs stop)
# ---------------------------------------------------------------------------


class TestSourceErrorHandling:
    """Test that a failing source is skipped (default) or stops the pipeline."""

    @pytest.mark.asyncio
    async def test_independent_source_error_skipped_by_default(self, tmp_path):
        """A 4xx error on an independent source should be skipped, not crash the pipeline."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="bad_source", endpoint="/api/bad"),
                ApiSource(id="good_source", endpoint="/api/good"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):  # noqa: ARG001
                if endpoint == "/api/bad":
                    raise Exception("404 Not Found")
                return [{"name": "Alice"}]

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(config, quiet=True)

        # bad_source should be 0 (skipped), good_source should succeed
        assert results["bad_source"] == 0
        assert results["good_source"] == 1

    @pytest.mark.asyncio
    async def test_source_error_stop_raises(self, tmp_path):
        """When on_error='stop', a failing source should raise and stop the pipeline."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="bad_source", endpoint="/api/bad", on_error="stop"),
                ApiSource(id="good_source", endpoint="/api/good"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):  # noqa: ARG001
                if endpoint == "/api/bad":
                    raise Exception("500 Server Error")
                return [{"name": "Alice"}]

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            with pytest.raises(Exception, match="500 Server Error"):
                await collect_dataset(config, quiet=True)

    @pytest.mark.asyncio
    async def test_multiple_sources_first_fails_rest_continue(self, tmp_path):
        """Multiple sources: first fails (skip), second and third succeed."""
        config = DatasetConfig(
            name="test",
            sources=[
                ApiSource(id="src_a", endpoint="/api/a"),
                ApiSource(id="src_b", endpoint="/api/b"),
                ApiSource(id="src_c", endpoint="/api/c"),
            ],
            storage={"format": "parquet", "path": str(tmp_path / "data")},
        )

        with patch("anysite.dataset.collector.create_client") as mock_create:
            mock_client = AsyncMock()

            async def mock_post(endpoint, data=None):  # noqa: ARG001
                if endpoint == "/api/a":
                    raise Exception("Rate limit exceeded")
                return [{"result": endpoint}]

            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_client

            results = await collect_dataset(config, quiet=True)

        assert results["src_a"] == 0
        assert results["src_b"] == 1
        assert results["src_c"] == 1


class TestCollectSql:
    """Tests for SQL source collection."""

    async def test_sql_source_returns_rows(self, tmp_path):
        """SQL source collects rows via fetch_all."""
        config = DatasetConfig(
            name="sql-test",
            sources=[
                SqlSource(
                    id="billing",
                    type="sql",
                    connection="testdb",
                    query="SELECT name, email FROM users",
                ),
            ],
            storage={"path": str(tmp_path / "data")},
        )

        mock_adapter = MagicMock()
        mock_adapter.__enter__ = MagicMock(return_value=mock_adapter)
        mock_adapter.__exit__ = MagicMock(return_value=None)
        mock_adapter.fetch_all.return_value = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]

        mock_manager = MagicMock()
        mock_manager.get_adapter_by_name.return_value = mock_adapter

        with patch("anysite.db.manager.ConnectionManager", return_value=mock_manager):
            results = await collect_dataset(config, quiet=True)

        assert results["billing"] == 2
        mock_manager.get_adapter_by_name.assert_called_once_with("testdb")
        mock_adapter.fetch_all.assert_called_once_with("SELECT name, email FROM users")

    async def test_sql_source_with_query_file(self, tmp_path):
        """SQL source reads query from file."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT name FROM users WHERE active = true")

        config = DatasetConfig(
            name="sql-test",
            sources=[
                SqlSource(
                    id="billing",
                    type="sql",
                    connection="testdb",
                    query_file=str(sql_file),
                ),
            ],
            storage={"path": str(tmp_path / "data")},
        )

        mock_adapter = MagicMock()
        mock_adapter.__enter__ = MagicMock(return_value=mock_adapter)
        mock_adapter.__exit__ = MagicMock(return_value=None)
        mock_adapter.fetch_all.return_value = [{"name": "Alice"}]

        mock_manager = MagicMock()
        mock_manager.get_adapter_by_name.return_value = mock_adapter

        with patch("anysite.db.manager.ConnectionManager", return_value=mock_manager):
            results = await collect_dataset(config, quiet=True)

        assert results["billing"] == 1
        mock_adapter.fetch_all.assert_called_once_with(
            "SELECT name FROM users WHERE active = true"
        )

    async def test_sql_to_api_chain(self, tmp_path):
        """SQL source feeds dependent API source."""
        config = DatasetConfig(
            name="sql-chain",
            sources=[
                SqlSource(
                    id="billing",
                    type="sql",
                    connection="testdb",
                    query="SELECT name FROM users",
                ),
                ApiSource(
                    id="profiles",
                    endpoint="/api/linkedin/search/users",
                    dependency=SourceDependency(from_source="billing", field="name"),
                    input_key="keywords",
                ),
            ],
            storage={"path": str(tmp_path / "data")},
        )

        mock_adapter = MagicMock()
        mock_adapter.__enter__ = MagicMock(return_value=mock_adapter)
        mock_adapter.__exit__ = MagicMock(return_value=None)
        mock_adapter.fetch_all.return_value = [
            {"name": "Alice"},
            {"name": "Bob"},
        ]

        mock_manager = MagicMock()
        mock_manager.get_adapter_by_name.return_value = mock_adapter

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=[{"urn": "urn:1", "name": "Result"}])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("anysite.db.manager.ConnectionManager", return_value=mock_manager),
            patch("anysite.dataset.collector.create_client", return_value=mock_client),
        ):
            results = await collect_dataset(config, quiet=True)

        assert results["billing"] == 2
        assert results["profiles"] == 2  # one API call per name

    async def test_sql_source_dry_run(self, tmp_path):
        """Dry run shows SQL source in plan."""
        config = DatasetConfig(
            name="sql-plan",
            sources=[
                SqlSource(
                    id="billing",
                    type="sql",
                    connection="testdb",
                    query="SELECT name FROM users",
                ),
            ],
            storage={"path": str(tmp_path / "data")},
        )

        results = await collect_dataset(config, dry_run=True, quiet=True)
        plan_steps = results["_plan"]
        assert len(plan_steps) == 1
        assert plan_steps[0]["kind"] == "sql"
        assert plan_steps[0]["estimated_requests"] == 1
        assert plan_steps[0]["params"]["connection"] == "testdb"

    async def test_sql_source_duckdb_views(self, tmp_path):
        """SQL source without connection queries dataset Parquet via DuckDB."""
        data_dir = tmp_path / "data"

        # Write some parquet data as if a prior source collected it
        source_dir = data_dir / "raw" / "users"
        source_dir.mkdir(parents=True)
        write_parquet(
            [
                {"name": "Alice", "score": 10},
                {"name": "Bob", "score": 20},
            ],
            source_dir / "2026-03-12.parquet",
        )

        config = DatasetConfig(
            name="duckdb-test",
            sources=[
                SqlSource(
                    id="filtered",
                    type="sql",
                    query="SELECT name FROM users WHERE score > 15",
                ),
            ],
            storage={"path": str(data_dir)},
        )

        results = await collect_dataset(config, quiet=True)
        assert results["filtered"] == 1

        # Verify the result was stored in parquet
        stored = read_parquet(data_dir / "raw" / "filtered")
        assert len(stored) == 1
        assert stored[0]["name"] == "Bob"

    async def test_sql_source_duckdb_join(self, tmp_path):
        """SQL source without connection can JOIN multiple dataset sources."""
        data_dir = tmp_path / "data"

        profiles_dir = data_dir / "raw" / "profiles"
        profiles_dir.mkdir(parents=True)
        write_parquet(
            [{"user_id": "u1", "name": "Alice"}, {"user_id": "u2", "name": "Bob"}],
            profiles_dir / "2026-03-12.parquet",
        )

        companies_dir = data_dir / "raw" / "companies"
        companies_dir.mkdir(parents=True)
        write_parquet(
            [{"user_id": "u1", "company": "Acme"}, {"user_id": "u2", "company": "Globex"}],
            companies_dir / "2026-03-12.parquet",
        )

        config = DatasetConfig(
            name="join-test",
            sources=[
                SqlSource(
                    id="combined",
                    type="sql",
                    query=(
                        "SELECT p.name, c.company "
                        "FROM profiles p "
                        "JOIN companies c ON p.user_id = c.user_id"
                    ),
                ),
            ],
            storage={"path": str(data_dir)},
        )

        results = await collect_dataset(config, quiet=True)
        assert results["combined"] == 2

        stored = read_parquet(data_dir / "raw" / "combined")
        names = {r["name"] for r in stored}
        assert names == {"Alice", "Bob"}
        assert stored[0]["company"] in ("Acme", "Globex")

    async def test_sql_source_duckdb_dry_run(self, tmp_path):
        """Dry run shows dataset views for connectionless SQL source."""
        config = DatasetConfig(
            name="duckdb-plan",
            sources=[
                SqlSource(
                    id="filtered",
                    type="sql",
                    query="SELECT * FROM users",
                ),
            ],
            storage={"path": str(tmp_path / "data")},
        )

        results = await collect_dataset(config, dry_run=True, quiet=True)
        plan_steps = results["_plan"]
        assert plan_steps[0]["params"]["connection"] == "(dataset views)"

    async def test_sql_source_duckdb_hyphenated_source_id(self, tmp_path):
        """Source ids with hyphens are sanitized to underscores for DuckDB views."""
        data_dir = tmp_path / "data"

        source_dir = data_dir / "raw" / "my-source"
        source_dir.mkdir(parents=True)
        write_parquet(
            [{"name": "Alice"}],
            source_dir / "2026-03-12.parquet",
        )

        config = DatasetConfig(
            name="hyphen-test",
            sources=[
                SqlSource(
                    id="result",
                    type="sql",
                    query="SELECT * FROM my_source",
                ),
            ],
            storage={"path": str(data_dir)},
        )

        results = await collect_dataset(config, quiet=True)
        assert results["result"] == 1
