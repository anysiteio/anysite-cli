"""Tests for dataset LLM enrichment pipeline integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from anysite.dataset.llm_enrichment import (
    _build_schema_from_specs,
    _merge_results,
    _parse_add_specs,
    _set_none_fields,
)
from anysite.dataset.models import LLMStepConfig
from anysite.llm.models import LLMResponse, ProcessorResult


# ── _parse_add_specs ────────────────────────────────────────────────────────


class TestParseAddSpecs:
    def test_enum_spec(self):
        result = _parse_add_specs(["sentiment:positive/negative/neutral"])
        assert result == {"sentiment": "positive/negative/neutral"}

    def test_type_spec(self):
        result = _parse_add_specs(["language:string", "score:integer"])
        assert result == {"language": "string", "score": "integer"}

    def test_range_spec(self):
        result = _parse_add_specs(["quality:1-10"])
        assert result == {"quality": "1-10"}

    def test_multiple(self):
        result = _parse_add_specs([
            "sentiment:positive/negative/neutral",
            "lang:string",
            "score:1-10",
        ])
        assert len(result) == 3

    def test_invalid_no_colon(self):
        from anysite.dataset.errors import DatasetError

        with pytest.raises(DatasetError, match="Invalid LLM enrich spec"):
            _parse_add_specs(["bad_spec"])

    def test_whitespace_handling(self):
        result = _parse_add_specs(["  name : string  "])
        assert result == {"name": "string"}


# ── _build_schema_from_specs ────────────────────────────────────────────────


class TestBuildSchemaFromSpecs:
    def test_enum(self):
        props, req = _build_schema_from_specs({"mood": "happy/sad/neutral"})
        assert props["mood"]["type"] == "string"
        assert props["mood"]["enum"] == ["happy", "sad", "neutral"]
        assert req == ["mood"]

    def test_string_type(self):
        props, req = _build_schema_from_specs({"lang": "string"})
        assert props["lang"] == {"type": "string"}

    def test_integer_type(self):
        props, req = _build_schema_from_specs({"count": "integer"})
        assert props["count"] == {"type": "integer"}

    def test_range_becomes_integer(self):
        props, req = _build_schema_from_specs({"score": "1-10"})
        assert props["score"] == {"type": "integer"}

    def test_number_type(self):
        props, req = _build_schema_from_specs({"weight": "number"})
        assert props["weight"] == {"type": "number"}

    def test_boolean_type(self):
        props, req = _build_schema_from_specs({"active": "boolean"})
        assert props["active"] == {"type": "boolean"}

    def test_unknown_defaults_to_string(self):
        props, req = _build_schema_from_specs({"foo": "whatever"})
        assert props["foo"] == {"type": "string"}


# ── _merge_results ──────────────────────────────────────────────────────────


class TestMergeResults:
    def test_successful_merge(self):
        records = [{"name": "Alice"}, {"name": "Bob"}]
        result = ProcessorResult(
            results=[
                {"name": "Alice", "sentiment": "positive"},
                {"name": "Bob", "sentiment": "negative"},
            ]
        )
        merged = _merge_results(records, result, ["sentiment"])
        assert merged[0]["sentiment"] == "positive"
        assert merged[1]["sentiment"] == "negative"
        assert merged[0]["name"] == "Alice"

    def test_partial_results_fills_none(self):
        records = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"}]
        result = ProcessorResult(
            results=[
                {"name": "Alice", "sentiment": "positive"},
            ]
        )
        merged = _merge_results(records, result, ["sentiment"])
        assert merged[0]["sentiment"] == "positive"
        assert merged[1]["sentiment"] is None
        assert merged[2]["sentiment"] is None

    def test_multiple_output_keys(self):
        records = [{"name": "Alice"}]
        result = ProcessorResult(
            results=[{"name": "Alice", "a": 1, "b": 2}]
        )
        merged = _merge_results(records, result, ["a", "b"])
        assert merged[0]["a"] == 1
        assert merged[0]["b"] == 2


# ── _set_none_fields ────────────────────────────────────────────────────────


class TestSetNoneFields:
    def test_enrich(self):
        records = [{"name": "Alice"}]
        step = LLMStepConfig(type="enrich", add=["mood:happy/sad"])
        _set_none_fields(records, step)
        assert records[0]["mood"] is None

    def test_classify(self):
        records = [{"name": "Alice"}]
        step = LLMStepConfig(type="classify")
        _set_none_fields(records, step)
        assert records[0]["category"] is None
        assert records[0]["category_confidence"] is None

    def test_classify_custom_column(self):
        records = [{"name": "Alice"}]
        step = LLMStepConfig(type="classify", output_column="role")
        _set_none_fields(records, step)
        assert records[0]["role"] is None
        assert records[0]["role_confidence"] is None

    def test_summarize(self):
        records = [{"name": "Alice"}]
        step = LLMStepConfig(type="summarize")
        _set_none_fields(records, step)
        assert records[0]["summary"] is None

    def test_generate(self):
        records = [{"name": "Alice"}]
        step = LLMStepConfig(type="generate", prompt="test {name}")
        _set_none_fields(records, step)
        assert records[0]["text"] is None


# ── Integration tests with mocked LLM ──────────────────────────────────────


@pytest.fixture
def mock_llm_config():
    """Mock LLM config."""
    from anysite.llm.models import LLMConfig, LLMProviderConfig

    return LLMConfig(
        default_provider="openai",
        providers={
            "openai": LLMProviderConfig(
                provider="openai",
                api_key_env="OPENAI_API_KEY",
                default_model="gpt-4.1-mini",
            ),
        },
        cache_enabled=False,
        default_temperature=0.0,
        default_max_tokens=4096,
        rate_limit=None,
    )


@pytest.fixture
def mock_provider():
    """Mock LLM provider."""
    provider = AsyncMock()
    provider.close = AsyncMock()
    return provider


def _make_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        input_tokens=10,
        output_tokens=5,
    )


@pytest.mark.asyncio
async def test_enrich_step_integration(mock_llm_config, mock_provider):
    """Test enrich step adds columns to records."""
    mock_provider.complete = AsyncMock(
        return_value=_make_response('{"sentiment": "positive", "language": "en"}')
    )

    records = [
        {"name": "Alice", "headline": "Engineer"},
        {"name": "Bob", "headline": "Manager"},
    ]
    step = LLMStepConfig(
        type="enrich",
        add=["sentiment:positive/negative/neutral", "language:string"],
        fields=["headline"],
    )

    with (
        patch("anysite.llm.check_llm_deps"),
        patch("anysite.llm.load_llm_config", return_value=mock_llm_config),
        patch("anysite.llm.get_api_key", return_value="test-key"),
        patch("anysite.llm.providers.create_provider", return_value=mock_provider),
    ):
        from anysite.dataset.llm_enrichment import enrich_records

        result = await enrich_records(records, [step], quiet=True)

    assert result[0]["sentiment"] == "positive"
    assert result[0]["language"] == "en"
    assert result[0]["name"] == "Alice"  # Original fields preserved


@pytest.mark.asyncio
async def test_summarize_step_integration(mock_llm_config, mock_provider):
    """Test summarize step adds summary column."""
    mock_provider.complete = AsyncMock(
        return_value=_make_response('{"summary": "A brief summary"}')
    )

    records = [{"name": "Alice", "headline": "Engineer"}]
    step = LLMStepConfig(type="summarize", max_length=50, output_column="bio")

    with (
        patch("anysite.llm.check_llm_deps"),
        patch("anysite.llm.load_llm_config", return_value=mock_llm_config),
        patch("anysite.llm.get_api_key", return_value="test-key"),
        patch("anysite.llm.providers.create_provider", return_value=mock_provider),
    ):
        from anysite.dataset.llm_enrichment import enrich_records

        result = await enrich_records(records, [step], quiet=True)

    assert result[0]["bio"] == "A brief summary"


@pytest.mark.asyncio
async def test_generate_step_integration(mock_llm_config, mock_provider):
    """Test generate step adds text column."""
    mock_provider.complete = AsyncMock(
        return_value=_make_response('{"text": "Hello Alice!"}')
    )

    records = [{"name": "Alice"}]
    step = LLMStepConfig(
        type="generate",
        prompt="Write a greeting for {name}",
        output_column="greeting",
    )

    with (
        patch("anysite.llm.check_llm_deps"),
        patch("anysite.llm.load_llm_config", return_value=mock_llm_config),
        patch("anysite.llm.get_api_key", return_value="test-key"),
        patch("anysite.llm.providers.create_provider", return_value=mock_provider),
    ):
        from anysite.dataset.llm_enrichment import enrich_records

        result = await enrich_records(records, [step], quiet=True)

    assert result[0]["greeting"] == "Hello Alice!"


@pytest.mark.asyncio
async def test_multiple_steps_sequential(mock_llm_config, mock_provider):
    """Test multiple steps run in order and accumulate columns."""
    call_count = 0

    async def _complete(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return _make_response('{"summary": "A summary"}')
        return _make_response('{"sentiment": "positive"}')

    mock_provider.complete = AsyncMock(side_effect=_complete)

    records = [{"name": "Alice", "headline": "Engineer"}]
    steps = [
        LLMStepConfig(type="summarize", output_column="bio"),
        LLMStepConfig(type="enrich", add=["sentiment:positive/negative"]),
    ]

    with (
        patch("anysite.llm.check_llm_deps"),
        patch("anysite.llm.load_llm_config", return_value=mock_llm_config),
        patch("anysite.llm.get_api_key", return_value="test-key"),
        patch("anysite.llm.providers.create_provider", return_value=mock_provider),
    ):
        from anysite.dataset.llm_enrichment import enrich_records

        result = await enrich_records(records, steps, quiet=True)

    assert result[0]["bio"] == "A summary"
    assert result[0]["sentiment"] == "positive"
    assert result[0]["name"] == "Alice"  # Original preserved


@pytest.mark.asyncio
async def test_step_failure_sets_none(mock_llm_config, mock_provider):
    """Test that a failing step sets enriched fields to None."""
    mock_provider.complete = AsyncMock(side_effect=Exception("LLM down"))

    records = [{"name": "Alice"}]
    step = LLMStepConfig(type="enrich", add=["mood:happy/sad"])

    with (
        patch("anysite.llm.check_llm_deps"),
        patch("anysite.llm.load_llm_config", return_value=mock_llm_config),
        patch("anysite.llm.get_api_key", return_value="test-key"),
        patch("anysite.llm.providers.create_provider", return_value=mock_provider),
    ):
        from anysite.dataset.llm_enrichment import enrich_records

        result = await enrich_records(records, [step], quiet=True)

    assert result[0]["mood"] is None
    assert result[0]["name"] == "Alice"  # Original preserved
