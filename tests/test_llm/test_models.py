"""Tests for LLM models."""

from anysite.llm.models import (
    LLMConfig,
    LLMMessage,
    LLMProviderConfig,
    LLMResponse,
    ProcessorResult,
    StructuredSchema,
)


def test_provider_config_from_dict():
    data = {
        "provider": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4.1-mini",
    }
    config = LLMProviderConfig.from_dict(data)
    assert config.provider == "openai"
    assert config.api_key_env == "OPENAI_API_KEY"
    assert config.default_model == "gpt-4.1-mini"


def test_provider_config_defaults():
    data = {"provider": "anthropic"}
    config = LLMProviderConfig.from_dict(data)
    assert config.provider == "anthropic"
    assert config.api_key_env == ""
    assert config.default_model == ""


def test_llm_config_from_dict():
    data = {
        "default_provider": "anthropic",
        "providers": {
            "openai": {
                "provider": "openai",
                "api_key_env": "OPENAI_API_KEY",
                "default_model": "gpt-4.1-mini",
            },
            "anthropic": {
                "provider": "anthropic",
                "api_key_env": "ANTHROPIC_API_KEY",
                "default_model": "claude-sonnet-4-5-20250514",
            },
        },
        "cache_enabled": False,
        "default_temperature": 0.5,
        "default_max_tokens": 2048,
        "rate_limit": "100/m",
    }
    config = LLMConfig.from_dict(data)
    assert config.default_provider == "anthropic"
    assert len(config.providers) == 2
    assert config.cache_enabled is False
    assert config.default_temperature == 0.5
    assert config.default_max_tokens == 2048
    assert config.rate_limit == "100/m"


def test_llm_config_defaults():
    config = LLMConfig.from_dict({})
    assert config.default_provider == "openai"
    assert config.cache_enabled is True
    assert config.default_temperature == 0.0
    assert config.default_max_tokens == 4096
    assert config.rate_limit == "50/m"


def test_llm_message():
    msg = LLMMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_llm_response():
    resp = LLMResponse(
        content='{"summary": "test"}',
        model="gpt-4.1-mini",
        input_tokens=10,
        output_tokens=5,
    )
    assert resp.content == '{"summary": "test"}'
    assert resp.model == "gpt-4.1-mini"
    assert resp.input_tokens == 10
    assert resp.output_tokens == 5


def test_structured_schema():
    schema = StructuredSchema(
        name="test",
        schema={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    assert schema.name == "test"
    assert "properties" in schema.schema


def test_processor_result_defaults():
    result = ProcessorResult()
    assert result.results == []
    assert result.errors == []
    assert result.total_input_tokens == 0
    assert result.total_output_tokens == 0
    assert result.cache_hits == 0
    assert result.llm_calls == 0
