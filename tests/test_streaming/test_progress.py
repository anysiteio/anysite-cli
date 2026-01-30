"""Tests for progress tracker."""

import time

import pytest

from anysite.streaming.progress import ProgressTracker


class TestProgressTracker:
    def test_quiet_mode_hides_progress(self):
        tracker = ProgressTracker(total=10, quiet=True)
        assert tracker._should_show is False

    def test_force_show(self):
        tracker = ProgressTracker(total=10, show=True)
        assert tracker._should_show is True

    def test_force_hide(self):
        tracker = ProgressTracker(total=10, show=False)
        assert tracker._should_show is False

    def test_update_increments_count(self):
        tracker = ProgressTracker(total=10, show=False)
        tracker.update(3)
        tracker.update(2)
        assert tracker._completed == 5

    def test_get_stats(self):
        tracker = ProgressTracker(total=10, show=False)
        tracker._start_time = time.monotonic() - 2.0  # simulate 2 seconds
        tracker.update(10)
        stats = tracker.get_stats()
        assert stats["total"] == 10
        assert stats["elapsed_seconds"] >= 1.9
        assert stats["records_per_second"] > 0

    def test_context_manager(self):
        with ProgressTracker(total=5, show=False) as tracker:
            tracker.update(5)
        assert tracker._completed == 5
        assert tracker._progress is None

    def test_set_status(self):
        tracker = ProgressTracker(total=10, show=False)
        tracker.set_status("New status")
        assert tracker.description == "New status"
