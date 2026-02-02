"""Pydantic models for LLM configuration and responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM provider."""

    provider: str  # "openai" or "anthropic"
    api_key_env: str  # env var name
    default_model: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> LLMProviderConfig:
        return LLMProviderConfig(
            provider=data["provider"],
            api_key_env=data.get("api_key_env", ""),
            default_model=data.get("default_model", ""),
        )


@dataclass
class LLMConfig:
    """Top-level LLM configuration."""

    default_provider: str = "openai"
    providers: dict[str, LLMProviderConfig] = field(default_factory=dict)
    cache_enabled: bool = True
    default_temperature: float = 0.0
    default_max_tokens: int = 4096
    rate_limit: str | None = "50/m"

    @staticmethod
    def from_dict(data: dict[str, Any]) -> LLMConfig:
        providers: dict[str, LLMProviderConfig] = {}
        for name, pdata in data.get("providers", {}).items():
            providers[name] = LLMProviderConfig.from_dict(pdata)
        return LLMConfig(
            default_provider=data.get("default_provider", "openai"),
            providers=providers,
            cache_enabled=data.get("cache_enabled", True),
            default_temperature=data.get("default_temperature", 0.0),
            default_max_tokens=data.get("default_max_tokens", 4096),
            rate_limit=data.get("rate_limit", "50/m"),
        )


@dataclass
class LLMMessage:
    """A single message in the LLM conversation."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StructuredSchema:
    """JSON schema for structured output."""

    name: str
    schema: dict[str, Any]


@dataclass
class ProcessorResult:
    """Result of processing records through the LLM."""

    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cache_hits: int = 0
    llm_calls: int = 0
