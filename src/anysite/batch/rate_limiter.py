"""Token bucket rate limiter for controlling request rates."""

import asyncio
import time


class RateLimiter:
    """Async rate limiter using the token bucket algorithm.

    Usage:
        limiter = RateLimiter("10/s")
        async with limiter:
            await make_request()
    """

    def __init__(self, rate_string: str) -> None:
        """Initialize rate limiter from a rate string.

        Args:
            rate_string: Rate limit string (e.g., '10/s', '100/m', '1000/h')
        """
        self.max_tokens, self.interval = self.parse_rate(rate_string)
        self.refill_rate = self.max_tokens / self.interval  # tokens per second
        self.tokens = float(self.max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    @staticmethod
    def parse_rate(rate_string: str) -> tuple[int, float]:
        """Parse a rate string into (max_tokens, interval_seconds).

        Args:
            rate_string: Rate string like '10/s', '100/m', '1000/h'

        Returns:
            Tuple of (max_tokens, interval_in_seconds)

        Raises:
            ValueError: If rate string is invalid
        """
        rate_string = rate_string.strip()

        parts = rate_string.split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid rate format: '{rate_string}'. "
                "Expected format: '<number>/<unit>' (e.g., '10/s', '100/m', '1000/h')"
            )

        try:
            count = int(parts[0])
        except ValueError:
            raise ValueError(f"Invalid rate count: '{parts[0]}'. Must be an integer.") from None

        unit = parts[1].strip().lower()
        intervals = {"s": 1.0, "m": 60.0, "h": 3600.0}

        if unit not in intervals:
            raise ValueError(
                f"Invalid rate unit: '{unit}'. Must be 's' (seconds), 'm' (minutes), or 'h' (hours)."
            )

        return count, intervals[unit]

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self.tokens = min(
            self.max_tokens,
            self.tokens + elapsed * self.refill_rate,
        )
        self._last_refill = now

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one.

        This method will block (async sleep) if no tokens are available.
        """
        async with self._lock:
            self._refill()

            if self.tokens < 1:
                # Calculate wait time for next token
                wait_time = (1 - self.tokens) / self.refill_rate
                await asyncio.sleep(wait_time)
                self._refill()

            self.tokens -= 1

    async def __aenter__(self) -> "RateLimiter":
        """Acquire a token on context entry."""
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        """No-op on context exit."""
        pass
