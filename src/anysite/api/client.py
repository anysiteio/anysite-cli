"""Anysite API client with authentication and retry logic."""

import asyncio
from typing import Any

import httpx

from anysite import __version__
from anysite.api.errors import (
    AnysiteError,
    AuthenticationError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
)


class AnysiteClient:
    """HTTP client for Anysite API.

    Features:
    - Authentication via access-token header
    - Automatic retry with exponential backoff
    - Proper error handling with helpful messages
    """

    DEFAULT_BASE_URL = "https://api.anysite.io"
    DEFAULT_TIMEOUT = 300  # 5 minutes
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 2, 4]  # Exponential backoff

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ) -> None:
        """Initialize the API client.

        Args:
            api_key: Anysite API key
            base_url: API base URL (default: https://api.anysite.io)
            timeout: Request timeout in seconds (default: 300)
        """
        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout or self.DEFAULT_TIMEOUT

        self._client: httpx.AsyncClient | None = None

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication."""
        headers = {
            "User-Agent": f"anysite-cli/{__version__}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["access-token"] = self.api_key
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AnysiteClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle error responses from the API."""
        status_code = response.status_code

        # Try to parse error details from JSON
        try:
            raw = response.json()
            error_data = raw if isinstance(raw, dict) else {"detail": raw}
        except Exception:
            error_data = {"detail": response.text}

        # Handle specific status codes
        if status_code == 401:
            raise AuthenticationError(details=error_data)

        if status_code == 404:
            detail = error_data.get("detail", "Resource not found")
            raise NotFoundError(resource=str(detail), details=error_data)

        if status_code == 422:
            # Validation error - FastAPI format
            detail = error_data.get("detail", [])
            if isinstance(detail, list):
                raise ValidationError(errors=detail, details=error_data)
            raise ValidationError(message=str(detail), details=error_data)

        if status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(
                retry_after=int(retry_after) if retry_after else None,
                details=error_data,
            )

        if 500 <= status_code < 600:
            raise ServerError(status_code=status_code, details=error_data)

        # Generic error for other status codes
        detail = error_data.get("detail", f"Request failed with status {status_code}")
        raise AnysiteError(message=str(detail), details=error_data)

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a request with retry logic.

        Args:
            method: HTTP method
            endpoint: API endpoint path
            **kwargs: Additional arguments for httpx

        Returns:
            Response object

        Raises:
            Various AnysiteError subclasses on failure
        """
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.request(method, endpoint, **kwargs)

                # Success - return response
                if response.is_success:
                    return response

                # Don't retry client errors (4xx) except rate limit
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    self._handle_error_response(response)

                # Rate limit - wait and retry
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after else self.RETRY_DELAYS[attempt]
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(wait_time)
                        continue
                    self._handle_error_response(response)

                # Server error - retry with backoff
                if response.status_code >= 500:
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(self.RETRY_DELAYS[attempt])
                        continue
                    self._handle_error_response(response)

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                    continue
                raise TimeoutError(timeout=self.timeout) from e

            except httpx.NetworkError as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                    continue
                raise NetworkError(original_error=e) from e

            except (AuthenticationError, NotFoundError, ValidationError):
                # Don't retry these errors
                raise

        # Should not reach here, but just in case
        raise NetworkError(
            message="Request failed after multiple retries",
            original_error=last_error,
        )

    async def post(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Make a POST request to the API.

        All Anysite API endpoints use POST with JSON body.

        Args:
            endpoint: API endpoint path (e.g., '/api/linkedin/user')
            data: Request body as dict

        Returns:
            Response data as list of dicts (API always returns arrays)
        """
        response = await self._request_with_retry(
            "POST",
            endpoint,
            json=data or {},
        )
        return response.json()  # type: ignore[no-any-return]

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make a GET request to the API.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            Response data
        """
        response = await self._request_with_retry(
            "GET",
            endpoint,
            params=params,
        )
        return response.json()


def create_client(
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int | None = None,
) -> AnysiteClient:
    """Create an API client with settings from config if not provided.

    Args:
        api_key: API key (falls back to config/env)
        base_url: Base URL (falls back to config/env)
        timeout: Timeout in seconds (falls back to config/env)

    Returns:
        Configured AnysiteClient instance
    """
    from anysite.config import get_settings

    settings = get_settings()

    return AnysiteClient(
        api_key=api_key or settings.api_key,
        base_url=base_url or settings.base_url,
        timeout=timeout or settings.timeout,
    )
