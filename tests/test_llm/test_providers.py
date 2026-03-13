"""Tests for LLM providers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from anysite.llm.errors import ConfigError, ProviderError
from anysite.llm.models import LLMMessage, StructuredSchema
from anysite.llm.providers import AnthropicProvider, OpenAIProvider, create_provider


class TestOpenAIProvider:
    """Tests for OpenAI provider."""

    @patch("openai.AsyncOpenAI")
    def test_init(self, mock_async_client):
        provider = OpenAIProvider(api_key="test-key", model="gpt-4.1-mini")
        assert provider.model == "gpt-4.1-mini"
        mock_async_client.assert_called_once_with(api_key="test-key", max_retries=3)

    @pytest.mark.asyncio
    @patch("openai.AsyncOpenAI")
    async def test_complete_basic(self, mock_async_client):
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 20

        mock_choice = MagicMock()
        mock_choice.message.content = '{"summary": "test"}'

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4.1-mini"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_async_client.return_value = mock_client

        provider = OpenAIProvider(api_key="test-key")
        messages = [LLMMessage(role="user", content="Hello")]
        response = await provider.complete(messages)

        assert response.content == '{"summary": "test"}'
        assert response.model == "gpt-4.1-mini"
        assert response.input_tokens == 10
        assert response.output_tokens == 20

    @pytest.mark.asyncio
    @patch("openai.AsyncOpenAI")
    async def test_complete_with_structured(self, mock_async_client):
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 20

        mock_choice = MagicMock()
        mock_choice.message.content = '{"summary": "test"}'

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4.1-mini"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_async_client.return_value = mock_client

        provider = OpenAIProvider(api_key="test-key")
        schema = StructuredSchema(
            name="test",
            schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )
        messages = [LLMMessage(role="user", content="Summarize")]
        await provider.complete(messages, structured=schema)

        # Verify response_format was passed
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"

    @pytest.mark.asyncio
    async def test_auth_error(self):
        import openai

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.AuthenticationError(
                message="bad key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            provider = OpenAIProvider(api_key="bad-key")
            with pytest.raises(ConfigError, match="authentication failed"):
                await provider.complete([LLMMessage(role="user", content="Hi")])

    @pytest.mark.asyncio
    async def test_bad_request_error(self):
        import openai

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=openai.BadRequestError(
                message="invalid",
                response=MagicMock(status_code=400),
                body=None,
            )
        )

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            provider = OpenAIProvider(api_key="key")
            with pytest.raises(ProviderError, match="bad request"):
                await provider.complete([LLMMessage(role="user", content="Hi")])

    @pytest.mark.asyncio
    @patch("openai.AsyncOpenAI")
    async def test_close(self, mock_async_client):
        mock_client = AsyncMock()
        mock_async_client.return_value = mock_client

        provider = OpenAIProvider(api_key="key")
        await provider.close()
        mock_client.close.assert_called_once()


class TestAnthropicProvider:
    """Tests for Anthropic provider."""

    @patch("anthropic.AsyncAnthropic")
    def test_init(self, mock_async_client):
        provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-5-20250514")
        assert provider.model == "claude-sonnet-4-5-20250514"
        mock_async_client.assert_called_once_with(api_key="test-key", max_retries=3)

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
    async def test_complete_basic(self, mock_async_client):
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = '{"result": "ok"}'

        mock_usage = MagicMock()
        mock_usage.input_tokens = 15
        mock_usage.output_tokens = 25

        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage = mock_usage
        mock_response.model = "claude-sonnet-4-5-20250514"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_async_client.return_value = mock_client

        provider = AnthropicProvider(api_key="test-key")
        messages = [
            LLMMessage(role="system", content="Be helpful"),
            LLMMessage(role="user", content="Hello"),
        ]
        response = await provider.complete(messages)

        assert response.content == '{"result": "ok"}'
        assert response.input_tokens == 15
        assert response.output_tokens == 25

        # Verify system message was separated
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "Be helpful"
        assert len(call_kwargs["messages"]) == 1
        assert call_kwargs["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_auth_error(self):
        import anthropic

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.AuthenticationError(
                message="bad key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            provider = AnthropicProvider(api_key="bad-key")
            with pytest.raises(ConfigError, match="authentication failed"):
                await provider.complete([LLMMessage(role="user", content="Hi")])


    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
    async def test_complete_structured_uses_tool_use(self, mock_async_client):
        """Structured output uses tool_use and extracts input from tool_use block."""
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.input = {"sentiment": "positive", "score": 8}

        mock_usage = MagicMock()
        mock_usage.input_tokens = 20
        mock_usage.output_tokens = 30

        mock_response = MagicMock()
        mock_response.content = [mock_tool_block]
        mock_response.usage = mock_usage
        mock_response.model = "claude-sonnet-4-5-20250514"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_async_client.return_value = mock_client

        provider = AnthropicProvider(api_key="test-key")
        schema = StructuredSchema(
            name="enrich_output",
            schema={
                "type": "object",
                "properties": {
                    "sentiment": {"type": "string", "enum": ["positive", "negative"]},
                    "score": {"type": "integer"},
                },
                "required": ["sentiment", "score"],
                "additionalProperties": False,
            },
        )
        messages = [
            LLMMessage(role="system", content="Analyze sentiment"),
            LLMMessage(role="user", content="Great product!"),
        ]
        response = await provider.complete(messages, structured=schema)

        # Should return serialized JSON from tool_use block
        assert '"sentiment"' in response.content
        assert '"positive"' in response.content

        # Verify tool_use was passed to API
        call_kwargs = mock_client.messages.create.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["name"] == "enrich_output"
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "enrich_output"}
        # additionalProperties should be stripped
        assert "additionalProperties" not in call_kwargs["tools"][0]["input_schema"]


class TestCreateProvider:
    @patch("openai.AsyncOpenAI")
    def test_create_openai(self, _mock_client):
        provider = create_provider("openai", "key")
        assert isinstance(provider, OpenAIProvider)

    @patch("anthropic.AsyncAnthropic")
    def test_create_anthropic(self, _mock_client):
        provider = create_provider("anthropic", "key")
        assert isinstance(provider, AnthropicProvider)

    def test_create_unknown_raises(self):
        with pytest.raises(ConfigError, match="Unknown LLM provider"):
            create_provider("unknown", "key")

    @patch("openai.AsyncOpenAI")
    def test_create_with_model_override(self, _mock_client):
        provider = create_provider("openai", "key", model="gpt-4.1")
        assert provider.model == "gpt-4.1"
