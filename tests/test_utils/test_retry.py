"""Tests for retry logic."""

import asyncio

import pytest

from anysite.utils.retry import RetryConfig, calculate_delay, retry_async, should_retry


class TestRetryConfig:
    def test_default_config(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert config.jitter is True

    def test_custom_config(self):
        config = RetryConfig(max_attempts=5, initial_delay=0.5)
        assert config.max_attempts == 5
        assert config.initial_delay == 0.5


class TestCalculateDelay:
    def test_first_attempt(self):
        config = RetryConfig(initial_delay=1.0, jitter=False)
        delay = calculate_delay(0, config)
        assert delay == 1.0

    def test_second_attempt(self):
        config = RetryConfig(initial_delay=1.0, exponential_base=2.0, jitter=False)
        delay = calculate_delay(1, config)
        assert delay == 2.0

    def test_max_delay_cap(self):
        config = RetryConfig(initial_delay=1.0, max_delay=5.0, jitter=False)
        delay = calculate_delay(10, config)
        assert delay == 5.0

    def test_jitter_range(self):
        config = RetryConfig(initial_delay=1.0, jitter=True)
        delays = [calculate_delay(0, config) for _ in range(20)]
        # With jitter, delays should vary
        assert len(set(delays)) > 1
        # All should be within [0, initial_delay * 2]
        for d in delays:
            assert 0 <= d <= 2.0


class TestShouldRetry:
    def test_default_does_not_retry_generic_exception(self):
        config = RetryConfig()
        # Default retry_on only covers specific API errors
        assert should_retry(Exception("test"), config) is False

    def test_custom_retry_on(self):
        config = RetryConfig(retry_on=(ValueError,))
        assert should_retry(ValueError("test"), config) is True
        assert should_retry(TypeError("test"), config) is False


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(func, RetryConfig())
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        config = RetryConfig(
            max_attempts=3, initial_delay=0.01, jitter=False, retry_on=(ValueError,)
        )
        result = await retry_async(func, config)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded(self):
        async def func():
            raise ValueError("always fails")

        config = RetryConfig(max_attempts=2, initial_delay=0.01, jitter=False)
        with pytest.raises(ValueError, match="always fails"):
            await retry_async(func, config)
