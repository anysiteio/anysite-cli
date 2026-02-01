"""Tests for dataset history store and log manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from anysite.dataset.history import HistoryStore, LogManager, RunRecord


class TestHistoryStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> HistoryStore:
        return HistoryStore(db_path=tmp_path / "test_history.db")

    def test_record_start_returns_id(self, store: HistoryStore) -> None:
        run_id = store.record_start("test-ds")
        assert run_id > 0

    def test_record_finish_updates(self, store: HistoryStore) -> None:
        run_id = store.record_start("test-ds")
        store.record_finish(run_id, status="success", record_count=42, source_count=3, duration=1.5)

        runs = store.get_history("test-ds")
        assert len(runs) == 1
        assert runs[0].status == "success"
        assert runs[0].record_count == 42
        assert runs[0].source_count == 3
        assert runs[0].duration == 1.5

    def test_history_ordering(self, store: HistoryStore) -> None:
        id1 = store.record_start("test-ds")
        store.record_finish(id1, status="success", record_count=10)
        id2 = store.record_start("test-ds")
        store.record_finish(id2, status="failed", error="boom")

        runs = store.get_history("test-ds")
        assert len(runs) == 2
        # Most recent first
        assert runs[0].status == "failed"
        assert runs[1].status == "success"

    def test_history_limit(self, store: HistoryStore) -> None:
        for i in range(5):
            rid = store.record_start("test-ds")
            store.record_finish(rid, status="success", record_count=i)

        runs = store.get_history("test-ds", limit=3)
        assert len(runs) == 3

    def test_get_all_datasets(self, store: HistoryStore) -> None:
        store.record_start("ds-a")
        store.record_start("ds-b")
        store.record_start("ds-a")

        datasets = store.get_all_datasets()
        assert sorted(datasets) == ["ds-a", "ds-b"]

    def test_failed_run_with_error(self, store: HistoryStore) -> None:
        run_id = store.record_start("test-ds")
        store.record_finish(run_id, status="failed", error="Connection timeout")

        runs = store.get_history("test-ds")
        assert runs[0].error == "Connection timeout"


class TestLogManager:
    @pytest.fixture
    def log_mgr(self, tmp_path: Path) -> LogManager:
        return LogManager(log_dir=tmp_path / "logs")

    def test_log_path(self, log_mgr: LogManager) -> None:
        path = log_mgr.get_log_path("test-ds", 42)
        assert path.name == "test-ds_42.log"

    def test_create_and_read_handler(self, log_mgr: LogManager) -> None:
        import logging

        handler = log_mgr.create_handler("test-ds", 1)
        logger = logging.getLogger("test.history")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.info("Test log message")
        handler.close()
        logger.removeHandler(handler)

        content = log_mgr.read_log("test-ds", 1)
        assert content is not None
        assert "Test log message" in content

    def test_read_missing_log(self, log_mgr: LogManager) -> None:
        assert log_mgr.read_log("no-ds", 999) is None

    def test_list_logs(self, log_mgr: LogManager) -> None:
        # Create some log files
        for rid in [1, 2, 5]:
            path = log_mgr.get_log_path("test-ds", rid)
            path.write_text(f"log {rid}")

        logs = log_mgr.list_logs("test-ds")
        assert len(logs) == 3
        assert logs[0][0] == 1
        assert logs[2][0] == 5
