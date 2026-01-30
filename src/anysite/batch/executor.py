"""Batch executor for running commands across multiple inputs."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from anysite.batch.rate_limiter import RateLimiter
from anysite.cli.options import ErrorHandling
from anysite.output.console import print_warning


class BatchResult:
    """Result of a batch execution."""

    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.total: int = 0
        self.succeeded: int = 0
        self.failed: int = 0
        self.skipped: int = 0
        self.start_time: float = 0
        self.end_time: float = 0

    @property
    def elapsed(self) -> float:
        """Elapsed time in seconds."""
        return self.end_time - self.start_time

    @property
    def rate(self) -> float:
        """Records per second."""
        if self.elapsed > 0:
            return self.succeeded / self.elapsed
        return 0


class BatchExecutor:
    """Execute a command function across multiple inputs.

    Supports sequential and parallel execution with rate limiting,
    delay between requests, and configurable error handling.
    """

    def __init__(
        self,
        func: Callable[[str | dict[str, Any]], Awaitable[Any]],
        parallel: int = 1,
        delay: float = 0.0,
        on_error: ErrorHandling = ErrorHandling.STOP,
        rate_limiter: RateLimiter | None = None,
        progress_callback: Callable[[int], None] | None = None,
    ) -> None:
        """Initialize batch executor.

        Args:
            func: Async function to call for each input
            parallel: Number of concurrent requests
            delay: Delay between sequential requests (seconds)
            on_error: Error handling mode
            rate_limiter: Optional rate limiter
            progress_callback: Optional callback for progress updates
        """
        self.func = func
        self.parallel = max(1, parallel)
        self.delay = delay
        self.on_error = on_error
        self.rate_limiter = rate_limiter
        self.progress_callback = progress_callback

    async def execute(self, inputs: list[str | dict[str, Any]]) -> BatchResult:
        """Execute the function for all inputs.

        Args:
            inputs: List of inputs to process

        Returns:
            BatchResult with results and statistics
        """
        result = BatchResult()
        result.total = len(inputs)
        result.start_time = time.monotonic()

        if self.parallel > 1:
            await self._execute_parallel(inputs, result)
        else:
            await self._execute_sequential(inputs, result)

        result.end_time = time.monotonic()
        return result

    async def _execute_sequential(
        self,
        inputs: list[str | dict[str, Any]],
        result: BatchResult,
    ) -> None:
        """Execute inputs one at a time."""
        for i, inp in enumerate(inputs):
            try:
                if self.rate_limiter:
                    await self.rate_limiter.acquire()

                data = await self.func(inp)
                result.results.append(data if isinstance(data, dict) else {"data": data})
                result.succeeded += 1

                if self.progress_callback:
                    self.progress_callback(1)

                if self.delay > 0 and i < len(inputs) - 1:
                    await asyncio.sleep(self.delay)

            except Exception as e:
                result.failed += 1
                error_info = {"input": str(inp), "error": str(e)}
                result.errors.append(error_info)

                if self.on_error == ErrorHandling.STOP:
                    raise
                elif self.on_error == ErrorHandling.SKIP:
                    print_warning(f"Skipping '{inp}': {e}")
                    result.skipped += 1
                    if self.progress_callback:
                        self.progress_callback(1)

    async def _execute_parallel(
        self,
        inputs: list[str | dict[str, Any]],
        result: BatchResult,
    ) -> None:
        """Execute inputs with limited concurrency."""
        semaphore = asyncio.Semaphore(self.parallel)

        async def _process(inp: str | dict[str, Any]) -> None:
            async with semaphore:
                try:
                    if self.rate_limiter:
                        await self.rate_limiter.acquire()

                    data = await self.func(inp)
                    result.results.append(
                        data if isinstance(data, dict) else {"data": data}
                    )
                    result.succeeded += 1

                    if self.progress_callback:
                        self.progress_callback(1)

                except Exception as e:
                    result.failed += 1
                    error_info = {"input": str(inp), "error": str(e)}
                    result.errors.append(error_info)

                    if self.on_error == ErrorHandling.STOP:
                        raise
                    elif self.on_error == ErrorHandling.SKIP:
                        print_warning(f"Skipping '{inp}': {e}")
                        result.skipped += 1
                        if self.progress_callback:
                            self.progress_callback(1)

        tasks = [asyncio.create_task(_process(inp)) for inp in inputs]

        if self.on_error == ErrorHandling.STOP:
            # If any task fails, cancel the rest
            try:
                await asyncio.gather(*tasks)
            except Exception:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                raise
        else:
            # Let all tasks complete even if some fail
            await asyncio.gather(*tasks, return_exceptions=True)
