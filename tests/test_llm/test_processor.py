"""Tests for LLM processor."""

from unittest.mock import AsyncMock

import pytest

from anysite.llm.cache import LLMCache
from anysite.llm.models import LLMResponse
from anysite.llm.processor import LLMProcessor, _parse_response
from anysite.llm.prompts import PromptBuilder


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"summary": "Test summary"}',
            model="test-model",
            input_tokens=10,
            output_tokens=5,
        )
    )
    return provider


@pytest.fixture
def cache(tmp_path):
    c = LLMCache(db_path=tmp_path / "test_cache.db")
    yield c
    c.close()


class TestParseResponse:
    def test_parse_json_single(self):
        batch = [{"name": "Alice"}]
        result = _parse_response('{"summary": "Test"}', batch)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"
        assert result[0]["summary"] == "Test"

    def test_parse_json_batch_results(self):
        batch = [{"name": "Alice"}, {"name": "Bob"}]
        content = '{"results": [{"index": 0, "category": "A"}, {"index": 1, "category": "B"}]}'
        result = _parse_response(content, batch)
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[0]["category"] == "A"

    def test_parse_json_matches(self):
        # With multiple batch records, matches key returns the list directly
        batch = [{"name": "Alice"}, {"name": "Bob"}]
        content = '{"matches": [{"index": 0, "score": 0.9, "reason": "test"}]}'
        result = _parse_response(content, batch)
        assert len(result) == 1
        assert result[0]["score"] == 0.9

    def test_parse_json_duplicates(self):
        batch = [{"name": "Alice"}, {"name": "Alice Inc"}]
        content = '{"duplicates": [{"ids": [0, 1], "confidence": 0.95}]}'
        result = _parse_response(content, batch)
        assert len(result) == 1
        assert result[0]["confidence"] == 0.95

    def test_parse_invalid_json(self):
        batch = [{"name": "Alice"}]
        result = _parse_response("Not JSON at all", batch)
        assert len(result) == 1
        assert result[0]["_llm_response"] == "Not JSON at all"

    def test_parse_json_list(self):
        batch = [{"name": "Alice"}]
        result = _parse_response('[{"x": 1}, {"x": 2}]', batch)
        assert len(result) == 2

    def test_parse_markdown_wrapped_json(self):
        """JSON wrapped in markdown code fences is parsed correctly."""
        batch = [{"name": "Alice"}]
        content = '```json\n{"sentiment": "positive", "score": 8}\n```'
        result = _parse_response(content, batch)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"
        assert result[0]["sentiment"] == "positive"
        assert result[0]["score"] == 8

    def test_parse_markdown_wrapped_json_no_lang(self):
        """Markdown fences without language tag are also handled."""
        batch = [{"name": "Bob"}]
        content = '```\n{"category": "tech"}\n```'
        result = _parse_response(content, batch)
        assert len(result) == 1
        assert result[0]["category"] == "tech"


class TestLLMProcessor:
    @pytest.mark.asyncio
    async def test_process_single_record(self, mock_provider):
        processor = LLMProcessor(mock_provider, parallel=1)
        builder = PromptBuilder(template="Summarize: {record}")

        result = await processor.process_records(
            [{"name": "Alice", "title": "Engineer"}],
            builder,
            system_prompt="Be concise",
            batch_size=1,
        )

        assert len(result.results) == 1
        assert result.llm_calls == 1
        assert result.total_input_tokens == 10
        assert result.total_output_tokens == 5

    @pytest.mark.asyncio
    async def test_process_multiple_records(self, mock_provider):
        processor = LLMProcessor(mock_provider, parallel=2)
        builder = PromptBuilder(template="Summarize: {record}")

        records = [{"name": f"Person {i}"} for i in range(3)]
        result = await processor.process_records(
            records, builder, batch_size=1,
        )

        assert result.llm_calls == 3
        assert result.total_input_tokens == 30

    @pytest.mark.asyncio
    async def test_process_with_batch_size(self, mock_provider):
        mock_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"results": [{"index": 0, "category": "A"}, {"index": 1, "category": "B"}]}',
                model="test-model",
                input_tokens=20,
                output_tokens=10,
            )
        )
        processor = LLMProcessor(mock_provider, parallel=1)
        builder = PromptBuilder(template="Classify: {records}")

        records = [{"name": "Alice"}, {"name": "Bob"}]
        result = await processor.process_records(
            records, builder, batch_size=2,
        )

        # Should be 1 LLM call for 2 records
        assert result.llm_calls == 1

    @pytest.mark.asyncio
    async def test_process_with_cache(self, mock_provider, cache):
        processor = LLMProcessor(mock_provider, cache=cache, parallel=1)
        builder = PromptBuilder(template="Summarize: {record}")

        records = [{"name": "Alice"}]

        # First call — should call LLM
        result1 = await processor.process_records(records, builder, batch_size=1)
        assert result1.llm_calls == 1
        assert result1.cache_hits == 0

        # Second call — should hit cache
        result2 = await processor.process_records(records, builder, batch_size=1)
        assert result2.llm_calls == 0
        assert result2.cache_hits == 1

    @pytest.mark.asyncio
    async def test_process_with_no_cache(self, mock_provider, cache):
        processor = LLMProcessor(mock_provider, cache=cache, parallel=1)
        builder = PromptBuilder(template="Summarize: {record}")

        records = [{"name": "Alice"}]

        # First call
        await processor.process_records(records, builder, batch_size=1)
        # Second call with no_cache — should still call LLM
        result = await processor.process_records(records, builder, batch_size=1, no_cache=True)
        assert result.llm_calls == 1

    @pytest.mark.asyncio
    async def test_process_with_fields_filter(self, mock_provider):
        processor = LLMProcessor(mock_provider, parallel=1)
        builder = PromptBuilder(template="Summarize: {record}")

        records = [{"name": "Alice", "age": 30, "city": "NYC"}]
        result = await processor.process_records(
            records, builder, batch_size=1, fields=["name"],
        )

        assert result.llm_calls == 1

    @pytest.mark.asyncio
    async def test_process_error_skip(self, mock_provider):
        mock_provider.complete = AsyncMock(side_effect=Exception("API down"))
        processor = LLMProcessor(mock_provider, parallel=1, on_error="skip")
        builder = PromptBuilder(template="Summarize: {record}")

        result = await processor.process_records(
            [{"name": "Alice"}], builder, batch_size=1,
        )

        assert len(result.errors) == 1
        assert result.llm_calls == 0

    @pytest.mark.asyncio
    async def test_process_error_stop(self, mock_provider):
        # Make first call fail, second succeed
        mock_provider.complete = AsyncMock(side_effect=Exception("API down"))
        processor = LLMProcessor(mock_provider, parallel=1, on_error="stop")
        builder = PromptBuilder(template="Summarize: {record}")

        records = [{"name": "Alice"}, {"name": "Bob"}]
        result = await processor.process_records(
            records, builder, batch_size=1,
        )

        # Should stop after first error
        assert len(result.errors) >= 1
