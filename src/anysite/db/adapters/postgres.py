"""PostgreSQL database adapter using psycopg v3."""

from __future__ import annotations

import json
from typing import Any

from anysite.db.adapters.base import DatabaseAdapter
from anysite.db.config import ConnectionConfig, OnConflict
from anysite.db.utils.sanitize import sanitize_identifier, sanitize_table_name


class PostgresAdapter(DatabaseAdapter):
    """PostgreSQL adapter using psycopg v3 (sync mode)."""

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config
        self._conn: Any = None  # psycopg.Connection

    def connect(self) -> None:
        if self._conn is not None:
            return

        import psycopg
        from psycopg.rows import dict_row

        url = self.config.get_url()
        if url:
            self._conn = psycopg.connect(url, row_factory=dict_row)
        else:
            password = self.config.get_password()
            connect_kwargs: dict[str, Any] = {
                "host": self.config.host,
                "dbname": self.config.database,
                "row_factory": dict_row,
            }
            if self.config.user:
                connect_kwargs["user"] = self.config.user
            if password:
                connect_kwargs["password"] = password
            if self.config.port:
                connect_kwargs["port"] = self.config.port

            self._conn = psycopg.connect(**connect_kwargs)

        # Set autocommit for non-transactional operations
        self._conn.autocommit = True

    def disconnect(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> Any:
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first or use as context manager.")
        return self._conn

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.conn.execute(sql, params)

    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        cursor = self.conn.execute(sql, params)
        return cursor.fetchone()

    def fetch_all(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        cursor = self.conn.execute(sql, params)
        return cursor.fetchall()

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

        # Collect all column names
        all_columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for col in row:
                if col not in seen:
                    seen.add(col)
                    all_columns.append(col)

        safe_columns = [sanitize_identifier(col) for col in all_columns]
        placeholders = ", ".join(f"%({col})s" for col in all_columns)
        col_list = ", ".join(safe_columns)

        # Build the INSERT statement
        if on_conflict == OnConflict.IGNORE and conflict_columns:
            safe_conflict = [sanitize_identifier(c) for c in conflict_columns]
            conflict_list = ", ".join(safe_conflict)
            sql = (
                f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_list}) DO NOTHING"
            )
        elif on_conflict in (OnConflict.UPDATE, OnConflict.REPLACE) and conflict_columns:
            safe_conflict = [sanitize_identifier(c) for c in conflict_columns]
            conflict_list = ", ".join(safe_conflict)
            update_cols = [c for c in safe_columns if c not in safe_conflict]
            update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
            sql = (
                f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_list}) DO UPDATE SET {update_clause}"
            )
        else:
            sql = f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders})"

        # Prepare rows, serializing complex types to JSON
        prepared_rows: list[dict[str, Any]] = []
        for row in rows:
            prepared: dict[str, Any] = {}
            for col in all_columns:
                val = row.get(col)
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                prepared[col] = val
            prepared_rows.append(prepared)

        # Use executemany for batch insert
        with self.conn.transaction():
            cursor = self.conn.cursor()
            cursor.executemany(sql, prepared_rows)
            return len(prepared_rows)

    def table_exists(self, table: str) -> bool:
        row = self.fetch_one(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s AND table_schema = 'public')",
            (table,),
        )
        return bool(row and row.get("exists"))

    def get_table_schema(self, table: str) -> list[dict[str, str]]:
        rows = self.fetch_all(
            """
            SELECT c.column_name, c.data_type, c.is_nullable,
                   CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN 'YES' ELSE 'NO' END as primary_key
            FROM information_schema.columns c
            LEFT JOIN information_schema.key_column_usage kcu
                ON c.table_name = kcu.table_name AND c.column_name = kcu.column_name
            LEFT JOIN information_schema.table_constraints tc
                ON kcu.constraint_name = tc.constraint_name AND tc.constraint_type = 'PRIMARY KEY'
            WHERE c.table_name = %s AND c.table_schema = 'public'
            ORDER BY c.ordinal_position
            """,
            (table,),
        )
        return [
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"],
                "primary_key": r["primary_key"],
            }
            for r in rows
        ]

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
        row = self.fetch_one("SELECT version()")
        version = row["version"] if row else "unknown"
        return {
            "type": "postgres",
            "version": version,
            "host": self.config.host or "unknown",
            "database": self.config.database or "unknown",
        }

    def _begin_transaction(self) -> None:
        self.conn.autocommit = False

    def _commit_transaction(self) -> None:
        self.conn.commit()
        self.conn.autocommit = True

    def _rollback_transaction(self) -> None:
        self.conn.rollback()
        self.conn.autocommit = True
