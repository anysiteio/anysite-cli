"""LLM-specific error classes."""

from anysite.api.errors import AnysiteError


class LLMError(AnysiteError):
    """Base error for LLM operations."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ProviderError(LLMError):
    """Raised when an LLM provider returns an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class ConfigError(LLMError):
    """Raised when LLM configuration is invalid or missing."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PromptError(LLMError):
    """Raised when prompt template is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
