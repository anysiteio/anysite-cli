"""API error classes with helpful messages."""

from typing import Any


class AnysiteError(Exception):
    """Base exception for Anysite API errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class AuthenticationError(AnysiteError):
    """Raised when API authentication fails (401)."""

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        default_message = """Authentication failed

Your API key is invalid or expired.

To fix this:
  1. Get your API key at https://app.anysite.io/
  2. Set it with: anysite config set api_key <your-key>

Or set environment variable:
  export ANYSITE_API_KEY=sk-xxxxx"""

        super().__init__(message or default_message, details)


class RateLimitError(AnysiteError):
    """Raised when rate limit is exceeded (429)."""

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        retry_after: int | None = None,
    ) -> None:
        self.retry_after = retry_after
        default_message = "Rate limit exceeded. Please wait before making more requests."
        if retry_after:
            default_message += f"\nRetry after: {retry_after} seconds"
        super().__init__(message or default_message, details)


class NotFoundError(AnysiteError):
    """Raised when a resource is not found (404)."""

    def __init__(
        self,
        resource: str = "Resource",
        identifier: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.resource = resource
        self.identifier = identifier
        message = f"{resource} not found"
        if identifier:
            message = f"{resource} '{identifier}' not found"
        super().__init__(message, details)


class ValidationError(AnysiteError):
    """Raised when request validation fails (400/422)."""

    def __init__(
        self,
        message: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.errors = errors or []
        default_message = "Validation error"
        if errors:
            error_msgs = []
            for error in errors:
                loc = ".".join(str(x) for x in error.get("loc", []))
                msg = error.get("msg", "Invalid value")
                if loc:
                    error_msgs.append(f"  - {loc}: {msg}")
                else:
                    error_msgs.append(f"  - {msg}")
            default_message = "Validation errors:\n" + "\n".join(error_msgs)
        super().__init__(message or default_message, details)


class ServerError(AnysiteError):
    """Raised when API returns a server error (5xx)."""

    def __init__(
        self,
        message: str | None = None,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        default_message = f"Server error ({status_code}). Please try again later."
        super().__init__(message or default_message, details)


class NetworkError(AnysiteError):
    """Raised when a network error occurs."""

    def __init__(
        self,
        message: str | None = None,
        original_error: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.original_error = original_error
        default_message = "Network error. Please check your internet connection."
        if original_error:
            default_message += f"\nDetails: {original_error}"
        super().__init__(message or default_message, details)


class TimeoutError(AnysiteError):
    """Raised when a request times out."""

    def __init__(
        self,
        message: str | None = None,
        timeout: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.timeout = timeout
        default_message = "Request timed out."
        if timeout:
            default_message = f"Request timed out after {timeout} seconds."
        default_message += "\nTry increasing the timeout with --timeout option."
        super().__init__(message or default_message, details)
