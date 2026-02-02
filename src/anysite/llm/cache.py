"""SQLite-based LLM response cache."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import orjson

from anysite.config.paths import ensure_config_dir


def _default_cache_path() -> Path:
    return ensure_config_dir() / "llm_cache.db"


class LLMCache:
    """Cache LLM responses in SQLite."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _default_cache_path()
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    cache_key TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    response TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            self._conn.commit()
        return self._conn

    @staticmethod
    def make_key(model: str, prompt: str, input_data: str) -> str:
        """Generate a cache key from model, prompt, and input."""
        raw = f"{model}:{prompt}:{input_data}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Look up a cached response."""
        conn = self._connect()
        row = conn.execute(
            "SELECT response, model, input_tokens, output_tokens FROM cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "content": orjson.loads(row[0]),
            "model": row[1],
            "input_tokens": row[2],
            "output_tokens": row[3],
        }

    def put(
        self,
        cache_key: str,
        model: str,
        response: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Store a response in the cache."""
        conn = self._connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO cache (cache_key, model, response, input_tokens, output_tokens)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cache_key, model, orjson.dumps(response).decode(), input_tokens, output_tokens),
        )
        conn.commit()

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        conn = self._connect()
        row = conn.execute(
            """
            SELECT
                COUNT(*) as entries,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens
            FROM cache
            """
        ).fetchone()
        return {
            "entries": row[0] if row else 0,
            "total_input_tokens": row[1] if row else 0,
            "total_output_tokens": row[2] if row else 0,
        }

    def clear(self) -> int:
        """Clear all cache entries. Returns number of entries deleted."""
        conn = self._connect()
        count = conn.execute("SELECT COUNT(*) FROM cache").fetchone()
        conn.execute("DELETE FROM cache")
        conn.commit()
        return count[0] if count else 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
