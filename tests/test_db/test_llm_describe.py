"""Tests for LLM-powered catalog descriptions (mocked provider)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anysite.db.discovery import (
    ColumnInfo,
    DatabaseCatalog,
    ForeignKeyInfo,
    TableInfo,
)
from anysite.db.llm_describe import (
    _describe_columns,
    _describe_database,
    _describe_table,
    _detect_relationships,
    _llm_call,
    llm_describe_catalog,
)
from anysite.llm.models import LLMResponse


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete = AsyncMock()
    provider.close = AsyncMock()
    return provider


@pytest.fixture
def sample_catalog():
    return DatabaseCatalog(
        connection_name="testdb",
        database_type="sqlite",
        server_info={"type": "sqlite"},
        tables=[
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(name="id", type="INTEGER", primary_key=True),
                    ColumnInfo(name="name", type="TEXT"),
                    ColumnInfo(name="email", type="TEXT"),
                ],
                row_count=100,
                sample_rows=[{"id": 1, "name": "Alice", "email": "alice@test.com"}],
            ),
            TableInfo(
                name="posts",
                columns=[
                    ColumnInfo(name="id", type="INTEGER", primary_key=True),
                    ColumnInfo(name="user_id", type="INTEGER"),
                    ColumnInfo(name="title", type="TEXT"),
                ],
                row_count=500,
                sample_rows=[{"id": 1, "user_id": 1, "title": "Hello"}],
                foreign_keys=[
                    ForeignKeyInfo(
                        constrained_columns=["user_id"],
                        referred_table="users",
                        referred_columns=["id"],
                    )
                ],
            ),
        ],
        discovered_at="2026-02-06T14:00:00+00:00",
    )


class TestLlmCall:
    @pytest.mark.asyncio
    async def test_llm_call_basic(self, mock_provider):
        mock_provider.complete.return_value = LLMResponse(
            content='{"description": "A test table"}',
            model="test-model",
            input_tokens=10,
            output_tokens=5,
        )
        result = await _llm_call(
            mock_provider, None, "Describe this table", None, True, "test"
        )
        assert result == {"description": "A test table"}
        mock_provider.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_call_with_cache_hit(self, mock_provider):
        cache = MagicMock()
        cache.get.return_value = {
            "content": '{"description": "Cached result"}',
            "input_tokens": 0,
            "output_tokens": 0,
        }

        result = await _llm_call(
            mock_provider, cache, "Describe this", None, False, "test"
        )
        assert result == {"description": "Cached result"}
        mock_provider.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_call_caches_response(self, mock_provider):
        cache = MagicMock()
        cache.get.return_value = None  # cache miss

        mock_provider.complete.return_value = LLMResponse(
            content='{"description": "Fresh result"}',
            model="test-model",
            input_tokens=10,
            output_tokens=5,
        )

        result = await _llm_call(
            mock_provider, cache, "Describe this", None, False, "test"
        )
        assert result == {"description": "Fresh result"}
        cache.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_call_invalid_json(self, mock_provider):
        mock_provider.complete.return_value = LLMResponse(
            content="not valid json",
            model="test-model",
        )
        result = await _llm_call(
            mock_provider, None, "Describe", None, True, "test"
        )
        assert result == {}


class TestDescribeTable:
    @pytest.mark.asyncio
    async def test_describe_table(self, mock_provider, sample_catalog):
        mock_provider.complete.return_value = LLMResponse(
            content='{"description": "User account records"}',
            model="test-model",
        )
        table = sample_catalog.get_table("users")
        desc = await _describe_table(mock_provider, None, table, True)
        assert desc == "User account records"

    @pytest.mark.asyncio
    async def test_describe_table_empty_response(self, mock_provider, sample_catalog):
        mock_provider.complete.return_value = LLMResponse(
            content="{}",
            model="test-model",
        )
        table = sample_catalog.get_table("users")
        desc = await _describe_table(mock_provider, None, table, True)
        assert desc == ""


class TestDescribeColumns:
    @pytest.mark.asyncio
    async def test_describe_columns(self, mock_provider, sample_catalog):
        mock_provider.complete.return_value = LLMResponse(
            content=(
                '{"columns": ['
                '{"name": "id", "description": "Primary key"},'
                '{"name": "name", "description": "User display name"},'
                '{"name": "email", "description": "Email address"}'
                "]}"
            ),
            model="test-model",
        )
        table = sample_catalog.get_table("users")
        descs = await _describe_columns(mock_provider, None, table, True)
        assert descs["id"] == "Primary key"
        assert descs["name"] == "User display name"
        assert descs["email"] == "Email address"

    @pytest.mark.asyncio
    async def test_describe_columns_filters_unknown(self, mock_provider, sample_catalog):
        mock_provider.complete.return_value = LLMResponse(
            content=(
                '{"columns": ['
                '{"name": "id", "description": "PK"},'
                '{"name": "nonexistent", "description": "Ghost"}'
                "]}"
            ),
            model="test-model",
        )
        table = sample_catalog.get_table("users")
        descs = await _describe_columns(mock_provider, None, table, True)
        assert "id" in descs
        assert "nonexistent" not in descs


class TestDetectRelationships:
    @pytest.mark.asyncio
    async def test_detect_relationships(self, mock_provider, sample_catalog):
        # Remove the explicit FK to test implicit detection
        sample_catalog.tables[1].foreign_keys = []

        mock_provider.complete.return_value = LLMResponse(
            content=(
                '{"relationships": [{'
                '"from_table": "posts", "from_column": "user_id",'
                '"to_table": "users", "to_column": "id",'
                '"confidence": 0.95, "reason": "Naming convention"'
                "}]}"
            ),
            model="test-model",
        )
        rels = await _detect_relationships(mock_provider, None, sample_catalog, True)
        assert len(rels) == 1
        assert rels[0].from_table == "posts"
        assert rels[0].to_column == "id"

    @pytest.mark.asyncio
    async def test_detect_relationships_excludes_existing_fks(self, mock_provider, sample_catalog):
        # Keep the explicit FK — the result should be filtered out
        mock_provider.complete.return_value = LLMResponse(
            content=(
                '{"relationships": [{'
                '"from_table": "posts", "from_column": "user_id",'
                '"to_table": "users", "to_column": "id",'
                '"confidence": 0.95, "reason": "Naming"'
                "}]}"
            ),
            model="test-model",
        )
        rels = await _detect_relationships(mock_provider, None, sample_catalog, True)
        assert len(rels) == 0  # filtered because already declared as FK

    @pytest.mark.asyncio
    async def test_detect_relationships_filters_invalid(self, mock_provider, sample_catalog):
        mock_provider.complete.return_value = LLMResponse(
            content=(
                '{"relationships": [{'
                '"from_table": "nonexistent", "from_column": "user_id",'
                '"to_table": "users", "to_column": "id",'
                '"confidence": 0.9, "reason": "?"'
                "}]}"
            ),
            model="test-model",
        )
        rels = await _detect_relationships(mock_provider, None, sample_catalog, True)
        assert len(rels) == 0

    @pytest.mark.asyncio
    async def test_detect_relationships_single_table(self, mock_provider):
        catalog = DatabaseCatalog(
            connection_name="test",
            database_type="sqlite",
            server_info={},
            tables=[TableInfo(name="only", columns=[])],
            discovered_at="",
        )
        rels = await _detect_relationships(mock_provider, None, catalog, True)
        assert len(rels) == 0
        mock_provider.complete.assert_not_called()


class TestDescribeDatabase:
    @pytest.mark.asyncio
    async def test_describe_database(self, mock_provider, sample_catalog):
        mock_provider.complete.return_value = LLMResponse(
            content='{"description": "A blog platform database with users and posts"}',
            model="test-model",
        )
        desc = await _describe_database(mock_provider, None, sample_catalog, True)
        assert "blog" in desc.lower()


class TestLlmDescribeCatalog:
    @pytest.mark.asyncio
    async def test_full_enrichment(self, mock_provider, sample_catalog):
        call_count = 0

        async def mock_complete(messages, **kwargs):  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            # Return different responses based on call sequence
            # 1-2: describe_table (one per table)
            # 3-4: describe_columns (one per table)
            # 5: detect_relationships
            # 6: describe_database
            if call_count <= 2:
                return LLMResponse(
                    content=f'{{"description": "Table {call_count} description"}}',
                    model="test",
                )
            elif call_count <= 4:
                return LLMResponse(
                    content='{"columns": []}',
                    model="test",
                )
            elif call_count == 5:
                return LLMResponse(
                    content='{"relationships": []}',
                    model="test",
                )
            else:
                return LLMResponse(
                    content='{"description": "Overall DB description"}',
                    model="test",
                )

        mock_provider.complete = AsyncMock(side_effect=mock_complete)

        with (
            patch("anysite.llm.load_llm_config") as mock_config,
            patch("anysite.llm.get_api_key") as mock_key,
            patch("anysite.llm.providers.create_provider") as mock_create,
        ):
            mock_cfg = MagicMock()
            mock_cfg.default_provider = "openai"
            mock_cfg.cache_enabled = False
            mock_cfg.providers = {"openai": MagicMock(default_model="gpt-4.1-mini")}
            mock_config.return_value = mock_cfg
            mock_key.return_value = "test-key"
            mock_create.return_value = mock_provider

            await llm_describe_catalog(sample_catalog)

        assert sample_catalog.llm_enriched is True
        assert sample_catalog.description == "Overall DB description"
        assert sample_catalog.tables[0].description is not None
        mock_provider.close.assert_called_once()
