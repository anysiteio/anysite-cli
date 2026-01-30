"""Retry logic with exponential backoff."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from anysite.api.errors import (
    NetworkError,
    RateLimitError,
    ServerError,
)
from anysite.api.errors import (
    TimeoutError as AnysiteTimeoutError,
)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on: tuple[type[Exception], ...] = field(
        default_factory=lambda: (
            RateLimitError,
            ServerError,
            NetworkError,
            AnysiteTimeoutError,
        )
    )


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay for retry attempt using exponential backoff.

    Args:
        attempt: Zero-based attempt number
        config: Retry configuration

    Returns:
        Delay in seconds
    """
    delay = config.initial_delay * (config.exponential_base ** attempt)
    delay = min(delay, config.max_delay)

    if config.jitter:
        delay = delay * (0.5 + random.random() * 0.5)

    return delay


def should_retry(exception: Exception, config: RetryConfig) -> bool:
    """Determine if an exception should trigger a retry.

    Args:
        exception: The exception to check
        config: Retry configuration

    Returns:
        True if the exception is retryable
    """
    return isinstance(exception, config.retry_on)


async def retry_async(
    func: Callable[..., Awaitable[Any]],
    config: RetryConfig | None = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute an async function with retry logic.

    Args:
        func: Async function to execute
        config: Retry configuration (uses defaults if None)
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result of the function

    Raises:
        The last exception if all retries are exhausted
    """
    if config is None:
        config = RetryConfig()

    last_error: Exception | None = None

    for attempt in range(config.max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if not should_retry(e, config):
                raise

            if attempt < config.max_attempts - 1:
                delay = calculate_delay(attempt, config)
                await asyncio.sleep(delay)
            else:
                raise

    raise last_error  # type: ignore[misc]
