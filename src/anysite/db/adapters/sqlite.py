"""SQLite database adapter using stdlib sqlite3."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from anysite.db.adapters.base import DatabaseAdapter
from anysite.db.config import ConnectionConfig, OnConflict
from anysite.db.utils.sanitize import sanitize_identifier, sanitize_table_name


class SQLiteAdapter(DatabaseAdapter):
    """SQLite adapter using the stdlib sqlite3 module."""

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config
        self.db_path = config.path or ":memory:"
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        if self._conn is not None:
            return

        # Ensure parent directory exists for file-based databases
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrent access
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")

        # Enable foreign keys
        self._conn.execute("PRAGMA foreign_keys=ON")

    def disconnect(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first or use as context manager.")
        return self._conn

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.conn.execute(sql, params or ())
        self.conn.commit()

    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        cursor = self.conn.execute(sql, params or ())
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetch_all(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        cursor = self.conn.execute(sql, params or ())
        return [dict(row) for row in cursor.fetchall()]

    def insert_batch(
        self,
        table: str,
        rows: list[dict[str, Any]],
        on_conflict: OnConflict = OnConflict.ERROR,
        conflict_columns: list[str] | None = None,
    ) -> int:
        if not rows:
            return 0

        safe_table = sanitize_table_name(table)

        # Collect all column names from all rows
        all_columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for col in row:
                if col not in seen:
                    seen.add(col)
                    all_columns.append(col)

        safe_columns = [sanitize_identifier(col) for col in all_columns]
        placeholders = ", ".join("?" for _ in all_columns)
        col_list = ", ".join(safe_columns)

        # Build the INSERT statement based on conflict strategy
        if on_conflict == OnConflict.IGNORE:
            sql = f"INSERT OR IGNORE INTO {safe_table} ({col_list}) VALUES ({placeholders})"
        elif on_conflict == OnConflict.REPLACE:
            sql = f"INSERT OR REPLACE INTO {safe_table} ({col_list}) VALUES ({placeholders})"
        elif on_conflict == OnConflict.UPDATE and conflict_columns:
            safe_conflict = [sanitize_identifier(c) for c in conflict_columns]
            conflict_list = ", ".join(safe_conflict)
            update_cols = [c for c in safe_columns if c not in safe_conflict]
            update_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
            sql = (
                f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_list}) DO UPDATE SET {update_clause}"
            )
        else:
            sql = f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders})"

        # Prepare parameter rows, serializing complex types
        param_rows: list[tuple[Any, ...]] = []
        for row in rows:
            values: list[Any] = []
            for col in all_columns:
                val = row.get(col)
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                values.append(val)
            param_rows.append(tuple(values))

        cursor = self.conn.cursor()
        cursor.executemany(sql, param_rows)
        self.conn.commit()
        return cursor.rowcount

    def table_exists(self, table: str) -> bool:
        row = self.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return row is not None

    def get_table_schema(self, table: str) -> list[dict[str, str]]:
        safe_table = sanitize_table_name(table)
        rows = self.fetch_all(f"PRAGMA table_info({safe_table})")
        result: list[dict[str, str]] = []
        for row in rows:
            result.append({
                "name": row["name"],
                "type": row["type"],
                "nullable": "NO" if row["notnull"] else "YES",
                "primary_key": "YES" if row["pk"] else "NO",
            })
        return result

    def create_table(
        self,
        table: str,
        columns: dict[str, str],
        primary_key: str | None = None,
    ) -> None:
        safe_table = sanitize_table_name(table)
        col_defs: list[str] = []
        for col_name, col_type in columns.items():
            safe_col = sanitize_identifier(col_name)
            pk_suffix = " PRIMARY KEY" if col_name == primary_key else ""
            col_defs.append(f"{safe_col} {col_type}{pk_suffix}")

        cols_sql = ", ".join(col_defs)
        sql = f"CREATE TABLE IF NOT EXISTS {safe_table} ({cols_sql})"
        self.execute(sql)

    def get_server_info(self) -> dict[str, str]:
        return {
            "type": "sqlite",
            "version": sqlite3.sqlite_version,
            "path": self.db_path,
            "journal_mode": self._get_pragma("journal_mode"),
        }

    def _get_pragma(self, name: str) -> str:
        row = self.fetch_one(f"PRAGMA {name}")
        if row:
            return str(list(row.values())[0])
        return "unknown"

    def _begin_transaction(self) -> None:
        self.conn.execute("BEGIN")

    def _commit_transaction(self) -> None:
        self.conn.commit()

    def _rollback_transaction(self) -> None:
        self.conn.rollback()
