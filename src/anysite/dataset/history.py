"""Dataset run history — SQLite-backed tracking and file-based logs."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from anysite.config.paths import get_config_dir

logger = logging.getLogger(__name__)

_DB_NAME = "dataset_history.db"
_LOG_DIR = "logs"


@dataclass
class RunRecord:
    """A single dataset collection run."""

    id: int | None = None
    dataset_name: str = ""
    status: str = "running"  # running | success | failed | partial
    started_at: str = ""
    finished_at: str | None = None
    record_count: int = 0
    source_count: int = 0
    error: str | None = None
    duration: float = 0.0


class HistoryStore:
    """SQLite-backed run history at ~/.anysite/dataset_history.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (get_config_dir() / _DB_NAME)
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    record_count INTEGER DEFAULT 0,
                    source_count INTEGER DEFAULT 0,
                    error TEXT,
                    duration REAL DEFAULT 0.0
                )
            """)

    def record_start(self, dataset_name: str) -> int:
        """Record start of a collection run. Returns run ID."""
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "INSERT INTO runs (dataset_name, status, started_at) VALUES (?, 'running', ?)",
                (dataset_name, now),
            )
            return cursor.lastrowid or 0

    def record_finish(
        self,
        run_id: int,
        *,
        status: str = "success",
        record_count: int = 0,
        source_count: int = 0,
        error: str | None = None,
        duration: float = 0.0,
    ) -> None:
        """Record completion of a collection run."""
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """UPDATE runs SET status=?, finished_at=?, record_count=?,
                   source_count=?, error=?, duration=? WHERE id=?""",
                (status, now, record_count, source_count, error, duration, run_id),
            )

    def get_history(self, dataset_name: str, limit: int = 20) -> list[RunRecord]:
        """Get recent runs for a dataset."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs WHERE dataset_name=? ORDER BY id DESC LIMIT ?",
                (dataset_name, limit),
            ).fetchall()
        return [
            RunRecord(
                id=r["id"],
                dataset_name=r["dataset_name"],
                status=r["status"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                record_count=r["record_count"],
                source_count=r["source_count"],
                error=r["error"],
                duration=r["duration"],
            )
            for r in rows
        ]

    def get_all_datasets(self) -> list[str]:
        """Get list of all dataset names with history."""
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT dataset_name FROM runs ORDER BY dataset_name"
            ).fetchall()
        return [r[0] for r in rows]


class LogManager:
    """File-based log storage at ~/.anysite/logs/."""

    def __init__(self, log_dir: Path | None = None) -> None:
        self.log_dir = log_dir or (get_config_dir() / _LOG_DIR)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def get_log_path(self, dataset_name: str, run_id: int) -> Path:
        """Get the log file path for a specific run."""
        return self.log_dir / f"{dataset_name}_{run_id}.log"

    def create_handler(self, dataset_name: str, run_id: int) -> logging.FileHandler:
        """Create a logging FileHandler for a run."""
        path = self.get_log_path(dataset_name, run_id)
        handler = logging.FileHandler(str(path))
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        return handler

    def read_log(self, dataset_name: str, run_id: int) -> str | None:
        """Read a run's log file content."""
        path = self.get_log_path(dataset_name, run_id)
        if path.exists():
            return path.read_text()
        return None

    def list_logs(self, dataset_name: str) -> list[tuple[int, Path]]:
        """List available log files for a dataset."""
        logs = []
        for path in sorted(self.log_dir.glob(f"{dataset_name}_*.log")):
            try:
                run_id = int(path.stem.split("_")[-1])
                logs.append((run_id, path))
            except ValueError:
                continue
        return logs
