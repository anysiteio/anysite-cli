"""LLM provider implementations using official SDKs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import orjson

from anysite.llm.errors import ConfigError, ProviderError
from anysite.llm.models import LLMMessage, LLMResponse, StructuredSchema


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        structured: StructuredSchema | None = None,
    ) -> LLMResponse:
        """Send a completion request to the LLM."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the provider client."""
        ...


class OpenAIProvider(LLMProvider):
    """OpenAI provider using the official openai SDK."""

    def __init__(self, api_key: str, model: str = "gpt-4.1-mini", max_retries: int = 3) -> None:
        import openai

        self.model = model
        self._client = openai.AsyncOpenAI(api_key=api_key, max_retries=max_retries)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        structured: StructuredSchema | None = None,
    ) -> LLMResponse:
        import openai

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if structured:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": structured.name,
                    "strict": True,
                    "schema": structured.schema,
                },
            }

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as e:
            raise ConfigError(f"OpenAI authentication failed: {e}") from e
        except openai.BadRequestError as e:
            raise ProviderError(f"OpenAI bad request: {e}", status_code=400) from e
        except openai.APIError as e:
            raise ProviderError(f"OpenAI API error: {e}") from e

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage

        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def close(self) -> None:
        await self._client.close()


class AnthropicProvider(LLMProvider):
    """Anthropic provider using the official anthropic SDK."""

    def __init__(
        self, api_key: str, model: str = "claude-sonnet-4-5-20250514", max_retries: int = 3
    ) -> None:
        import anthropic

        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=max_retries)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        structured: StructuredSchema | None = None,
    ) -> LLMResponse:
        import anthropic

        # Separate system message from conversation
        system_text = ""
        conversation: list[dict[str, str]] = []
        for m in messages:
            if m.role == "system":
                system_text = m.content
            else:
                conversation.append({"role": m.role, "content": m.content})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": conversation,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_text:
            kwargs["system"] = system_text

        if structured:
            # Use prefill approach: ask for JSON in system prompt and parse
            schema_str = orjson.dumps(structured.schema).decode()
            suffix = (
                f"\n\nYou MUST respond with valid JSON matching this schema: {schema_str}"
                "\nRespond with ONLY the JSON object, no other text."
            )
            if system_text:
                kwargs["system"] = system_text + suffix
            else:
                kwargs["system"] = suffix.strip()

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise ConfigError(f"Anthropic authentication failed: {e}") from e
        except anthropic.BadRequestError as e:
            raise ProviderError(f"Anthropic bad request: {e}", status_code=400) from e
        except anthropic.APIError as e:
            raise ProviderError(f"Anthropic API error: {e}") from e

        content = ""
        for block in response.content:
            if block.type == "text":
                content = block.text
                break

        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    async def close(self) -> None:
        await self._client.close()


def create_provider(
    provider_type: str,
    api_key: str,
    model: str | None = None,
    max_retries: int = 3,
) -> LLMProvider:
    """Factory to create the appropriate LLM provider.

    Args:
        provider_type: "openai" or "anthropic"
        api_key: API key for the provider
        model: Optional model override
        max_retries: Number of retries for transient errors

    Returns:
        An LLMProvider instance
    """
    if provider_type == "openai":
        return OpenAIProvider(api_key, model=model or "gpt-4.1-mini", max_retries=max_retries)
    elif provider_type == "anthropic":
        return AnthropicProvider(
            api_key, model=model or "claude-sonnet-4-5-20250514", max_retries=max_retries
        )
    else:
        raise ConfigError(f"Unknown LLM provider: {provider_type}. Use 'openai' or 'anthropic'.")
