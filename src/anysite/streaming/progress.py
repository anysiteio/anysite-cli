"""Progress tracking with Rich progress bars."""

import sys
import time

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


class ProgressTracker:
    """Rich progress bar wrapper for tracking long operations.

    Automatically shows/hides based on terminal detection and quiet mode.
    """

    def __init__(
        self,
        total: int | None = None,
        description: str = "Processing...",
        show: bool | None = None,
        quiet: bool = False,
    ) -> None:
        """Initialize progress tracker.

        Args:
            total: Total number of items (None for indeterminate)
            description: Description text
            show: Force show/hide (None = auto-detect)
            quiet: Suppress all output
        """
        self.total = total
        self.description = description
        self.quiet = quiet
        self._completed = 0
        self._start_time = time.monotonic()
        self._progress: Progress | None = None

        # Determine if we should show progress
        if quiet:
            self._should_show = False
        elif show is not None:
            self._should_show = show
        else:
            # Auto: show if stdout is a terminal
            self._should_show = sys.stderr.isatty()

    def start(self) -> None:
        """Start the progress bar."""
        if not self._should_show:
            return

        columns = [
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        ]

        self._progress = Progress(*columns, transient=True)
        self._progress.start()
        self._task_id = self._progress.add_task(
            self.description,
            total=self.total,
        )

    def update(self, n: int = 1) -> None:
        """Update progress by n items.

        Args:
            n: Number of items completed
        """
        self._completed += n
        if self._progress is not None:
            self._progress.update(self._task_id, advance=n)

    def set_status(self, text: str) -> None:
        """Update the description text.

        Args:
            text: New description
        """
        self.description = text
        if self._progress is not None:
            self._progress.update(self._task_id, description=text)

    def finish(self) -> None:
        """Complete the progress bar."""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None

    def get_stats(self) -> dict[str, float | int]:
        """Get execution statistics.

        Returns:
            Dictionary with timing and throughput stats
        """
        elapsed = time.monotonic() - self._start_time
        rate = self._completed / elapsed if elapsed > 0 else 0

        return {
            "total": self._completed,
            "elapsed_seconds": round(elapsed, 2),
            "records_per_second": round(rate, 1),
        }

    def __enter__(self) -> "ProgressTracker":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.finish()
