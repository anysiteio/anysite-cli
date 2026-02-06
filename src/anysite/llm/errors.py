"""LLM-specific error classes."""

from anysite.api.errors import AnysiteError


class LLMError(AnysiteError):
    """Base error for LLM operations."""

    error_code = "LLM_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ProviderError(LLMError):
    """Raised when an LLM provider returns an error."""

    error_code = "LLM_PROVIDER_ERROR"
    retryable = True

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class ConfigError(LLMError):
    """Raised when LLM configuration is invalid or missing."""

    error_code = "CONFIG_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)

    @property
    def suggestions(self) -> list[str]:
        return ["Run 'anysite llm setup' to configure LLM provider"]


class PromptError(LLMError):
    """Raised when prompt template is invalid."""

    error_code = "PROMPT_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
