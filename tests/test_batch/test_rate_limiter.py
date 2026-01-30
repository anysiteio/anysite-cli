"""Tests for rate limiter."""

import asyncio
import time

import pytest

from anysite.batch.rate_limiter import RateLimiter


class TestParseRate:
    def test_per_second(self):
        tokens, interval = RateLimiter.parse_rate("10/s")
        assert tokens == 10
        assert interval == 1.0

    def test_per_minute(self):
        tokens, interval = RateLimiter.parse_rate("60/m")
        assert tokens == 60
        assert interval == 60.0

    def test_per_hour(self):
        tokens, interval = RateLimiter.parse_rate("100/h")
        assert tokens == 100
        assert interval == 3600.0

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            RateLimiter.parse_rate("invalid")

    def test_invalid_suffix(self):
        with pytest.raises(ValueError):
            RateLimiter.parse_rate("10/x")


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        limiter = RateLimiter("10/s")
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should be fast since we're within the burst limit
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_acquire_exceeds_limit(self):
        limiter = RateLimiter("2/s")
        start = time.monotonic()
        for _ in range(4):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should have waited at least once
        assert elapsed >= 0.5

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with RateLimiter("10/s") as limiter:
            await limiter.acquire()
