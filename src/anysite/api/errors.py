"""API error classes with helpful messages."""

from typing import Any

from anysite.cli.exit_codes import (
    EXIT_AUTH,
    EXIT_ERROR,
    EXIT_NETWORK,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
)


class AnysiteError(Exception):
    """Base exception for Anysite API errors."""

    error_code: str = "UNKNOWN_ERROR"
    exit_code: int = EXIT_ERROR
    retryable: bool = False

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def __str__(self) -> str:
        return self.message

    @property
    def suggestions(self) -> list[str]:
        """Actionable suggestions for resolving this error."""
        return []

    def to_dict(self) -> dict[str, Any]:
        """Serialize error for JSON output."""
        result: dict[str, Any] = {
            "code": self.error_code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.suggestions:
            result["suggestions"] = self.suggestions
        if self.details:
            result["details"] = self.details
        return result


class AuthenticationError(AnysiteError):
    """Raised when API authentication fails (401)."""

    error_code = "AUTH_FAILED"
    exit_code = EXIT_AUTH

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        default_message = """Authentication failed

Your API key is invalid or expired.

To fix this:
  1. Log in with: anysite auth login
  2. Or get your API key at https://app.anysite.io/
  3. Set it with: anysite config set api_key <your-key>

Or set environment variable:
  export ANYSITE_API_KEY=sk-xxxxx"""

        super().__init__(message or default_message, details)

    @property
    def suggestions(self) -> list[str]:
        return [
            "Log in with: anysite auth login",
            "Or get your API key at https://app.anysite.io/",
            "Set it with: anysite config set api_key <your-key>",
            "Or set: export ANYSITE_API_KEY=sk-xxxxx",
        ]


class RateLimitError(AnysiteError):
    """Raised when rate limit is exceeded (429)."""

    error_code = "RATE_LIMIT"
    exit_code = EXIT_NETWORK
    retryable = True

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

    @property
    def suggestions(self) -> list[str]:
        hints = ["Wait before retrying"]
        if self.retry_after:
            hints[0] = f"Wait {self.retry_after} seconds before retrying"
        hints.append("Use --rate-limit to throttle requests (e.g., --rate-limit '5/s')")
        return hints


class NotFoundError(AnysiteError):
    """Raised when a resource is not found (404)."""

    error_code = "NOT_FOUND"
    exit_code = EXIT_NOT_FOUND

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

    error_code = "VALIDATION_ERROR"
    exit_code = EXIT_USAGE

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

    @property
    def suggestions(self) -> list[str]:
        return ["Check parameter names and types with: anysite describe <endpoint>"]


class ServerError(AnysiteError):
    """Raised when API returns a server error (5xx)."""

    error_code = "SERVER_ERROR"
    retryable = True

    def __init__(
        self,
        message: str | None = None,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        default_message = f"Server error ({status_code}). Please try again later."
        super().__init__(message or default_message, details)

    @property
    def suggestions(self) -> list[str]:
        return ["Retry the request", "If the error persists, check https://status.anysite.io/"]


class NetworkError(AnysiteError):
    """Raised when a network error occurs."""

    error_code = "NETWORK_ERROR"
    exit_code = EXIT_NETWORK
    retryable = True

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

    @property
    def suggestions(self) -> list[str]:
        return [
            "Check your internet connection",
            "Verify the API base URL with: anysite config get base_url",
        ]


class TimeoutError(AnysiteError):
    """Raised when a request times out."""

    error_code = "TIMEOUT"
    exit_code = EXIT_NETWORK
    retryable = True

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

    @property
    def suggestions(self) -> list[str]:
        return ["Increase timeout with --timeout option", "Retry the request"]
