"""Tests for LLM prompts."""

import pytest

from anysite.llm.errors import PromptError
from anysite.llm.prompts import (
    BUILTIN_PROMPTS,
    PromptBuilder,
    _format_record,
    _format_records_batch,
    _safe_format,
    filter_record_fields,
)


def test_safe_format_basic():
    result = _safe_format("Hello {name}!", {"name": "World"})
    assert result == "Hello World!"


def test_safe_format_missing_key():
    result = _safe_format("Hello {name} and {missing}!", {"name": "World"})
    assert result == "Hello World and {missing}!"


def test_safe_format_multiple():
    result = _safe_format("{a} + {b} = {c}", {"a": "1", "b": "2", "c": "3"})
    assert result == "1 + 2 = 3"


def test_format_record():
    record = {"name": "Alice", "age": 30, "_internal": "skip"}
    result = _format_record(record)
    assert "name: Alice" in result
    assert "age: 30" in result
    assert "_internal" not in result


def test_format_records_batch():
    records = [{"name": "Alice"}, {"name": "Bob"}]
    result = _format_records_batch(records)
    assert "[0]" in result
    assert "[1]" in result
    assert "Alice" in result
    assert "Bob" in result


def test_prompt_builder_with_template():
    builder = PromptBuilder(template="Summarize: {record}")
    prompt = builder.build({"name": "Alice", "title": "Engineer"})
    assert "Alice" in prompt
    assert "Engineer" in prompt


def test_prompt_builder_with_builtin():
    builder = PromptBuilder(builtin_key="summarize")
    assert "{max_length}" in builder.template or "max_length" in builder.template


def test_prompt_builder_no_template_raises():
    with pytest.raises(PromptError):
        PromptBuilder()


def test_prompt_builder_build_with_variables():
    builder = PromptBuilder(template="Summary in {max_length} words: {record}")
    prompt = builder.build(
        {"name": "Alice"},
        variables={"max_length": "100"},
    )
    assert "100" in prompt
    assert "Alice" in prompt


def test_prompt_builder_build_for_batch():
    builder = PromptBuilder(template="Classify: {records}")
    prompt = builder.build_for_batch(
        [{"name": "Alice"}, {"name": "Bob"}],
        variables={"categories": "A,B,C"},
    )
    assert "Alice" in prompt
    assert "Bob" in prompt


def test_prompt_builder_field_substitution():
    builder = PromptBuilder(template="Hello {name}, you are {title}")
    prompt = builder.build({"name": "Alice", "title": "CTO"})
    assert prompt == "Hello Alice, you are CTO"


def test_filter_record_fields_basic():
    record = {"name": "Alice", "age": 30, "city": "NYC"}
    result = filter_record_fields(record, ["name", "age"])
    assert result == {"name": "Alice", "age": 30}


def test_filter_record_fields_dot_notation():
    record = {"profile": {"name": "Alice", "age": 30}}
    result = filter_record_fields(record, ["profile.name"])
    assert result == {"profile.name": "Alice"}


def test_filter_record_fields_missing():
    record = {"name": "Alice"}
    result = filter_record_fields(record, ["name", "nonexistent"])
    assert result == {"name": "Alice"}


def test_builtin_prompts_exist():
    assert "summarize" in BUILTIN_PROMPTS
    assert "classify" in BUILTIN_PROMPTS
    assert "match" in BUILTIN_PROMPTS
    assert "deduplicate" in BUILTIN_PROMPTS
    assert "enrich" in BUILTIN_PROMPTS
