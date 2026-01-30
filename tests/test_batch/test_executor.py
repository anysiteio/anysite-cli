"""Tests for batch executor."""

import asyncio

import pytest

from anysite.batch.executor import BatchExecutor, BatchResult
from anysite.cli.options import ErrorHandling


class TestBatchResult:
    def test_initial_state(self):
        result = BatchResult()
        assert result.total == 0
        assert result.succeeded == 0
        assert result.failed == 0
        assert result.skipped == 0

    def test_elapsed(self):
        result = BatchResult()
        result.start_time = 10.0
        result.end_time = 15.5
        assert result.elapsed == 5.5

    def test_rate(self):
        result = BatchResult()
        result.start_time = 0.0
        result.end_time = 2.0
        result.succeeded = 10
        assert result.rate == 5.0


class TestBatchExecutor:
    @pytest.mark.asyncio
    async def test_sequential_success(self):
        results = []

        async def func(inp):
            results.append(inp)
            return {"data": inp}

        executor = BatchExecutor(func=func, parallel=1)
        result = await executor.execute(["a", "b", "c"])
        assert result.succeeded == 3
        assert result.failed == 0
        assert len(result.results) == 3

    @pytest.mark.asyncio
    async def test_parallel_success(self):
        async def func(inp):
            await asyncio.sleep(0.01)
            return {"data": inp}

        executor = BatchExecutor(func=func, parallel=3)
        result = await executor.execute(["a", "b", "c", "d", "e"])
        assert result.succeeded == 5
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_error_stop(self):
        call_count = 0

        async def func(inp):
            nonlocal call_count
            call_count += 1
            if inp == "fail":
                raise ValueError("boom")
            return {"data": inp}

        executor = BatchExecutor(
            func=func, parallel=1, on_error=ErrorHandling.STOP
        )
        with pytest.raises(ValueError, match="boom"):
            await executor.execute(["a", "fail", "c"])

    @pytest.mark.asyncio
    async def test_error_skip(self):
        async def func(inp):
            if inp == "fail":
                raise ValueError("boom")
            return {"data": inp}

        executor = BatchExecutor(
            func=func, parallel=1, on_error=ErrorHandling.SKIP
        )
        result = await executor.execute(["a", "fail", "c"])
        assert result.succeeded == 2
        assert result.failed == 1
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_delay_between_requests(self):
        import time

        times = []

        async def func(inp):
            times.append(time.monotonic())
            return {"data": inp}

        executor = BatchExecutor(func=func, parallel=1, delay=0.05)
        await executor.execute(["a", "b", "c"])
        assert len(times) == 3
        # Check that there's a delay between calls
        for i in range(1, len(times)):
            assert times[i] - times[i - 1] >= 0.04  # allow small tolerance

    @pytest.mark.asyncio
    async def test_progress_callback(self):
        progress_calls = []

        async def func(inp):
            return {"data": inp}

        executor = BatchExecutor(
            func=func, parallel=1, progress_callback=lambda n: progress_calls.append(n)
        )
        await executor.execute(["a", "b"])
        assert progress_calls == [1, 1]

    @pytest.mark.asyncio
    async def test_non_dict_result_wrapped(self):
        async def func(inp):
            return [1, 2, 3]

        executor = BatchExecutor(func=func, parallel=1)
        result = await executor.execute(["a"])
        assert result.results[0] == {"data": [1, 2, 3]}
