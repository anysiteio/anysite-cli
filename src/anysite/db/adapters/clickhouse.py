"""ClickHouse database adapter using clickhouse-connect."""

from __future__ import annotations

import json
import logging
from typing import Any

from anysite.db.adapters.base import DatabaseAdapter
from anysite.db.config import ConnectionConfig, OnConflict
from anysite.db.utils.sanitize import sanitize_identifier, sanitize_table_name

logger = logging.getLogger(__name__)


class ClickHouseAdapter(DatabaseAdapter):
    """ClickHouse adapter using clickhouse-connect (HTTP protocol)."""

    def __init__(self, config: ConnectionConfig) -> None:
        self.config = config
        self._client: Any = None  # clickhouse_connect.driver.Client

    def connect(self) -> None:
        if self._client is not None:
            return

        import clickhouse_connect

        password = self.config.get_password()
        port = self.config.port or 8123
        secure = self.config.ssl or port == 8443

        connect_kwargs: dict[str, Any] = {
            "host": self.config.host or "localhost",
            "port": port,
            "secure": secure,
        }
        if self.config.database:
            connect_kwargs["database"] = self.config.database
        if self.config.user:
            connect_kwargs["username"] = self.config.user
        if password:
            connect_kwargs["password"] = password

        self._client = clickhouse_connect.get_client(**connect_kwargs)

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first or use as context manager.")
        return self._client

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        if params:
            self.client.command(sql, parameters=params)
        else:
            self.client.command(sql)

    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        result = self.client.query(sql, parameters=params or ())
        if not result.result_rows:
            return None
        return dict(zip(result.column_names, result.result_rows[0], strict=False))

    def fetch_all(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        result = self.client.query(sql, parameters=params or ())
        return [
            dict(zip(result.column_names, row, strict=False))
            for row in result.result_rows
        ]

    def insert_batch(
        self,
        table: str,
        rows: list[dict[str, Any]],
        on_conflict: OnConflict = OnConflict.ERROR,  # noqa: ARG002
        conflict_columns: list[str] | None = None,  # noqa: ARG002
    ) -> int:
        if not rows:
            return 0

        safe_table = sanitize_table_name(table)

        # Collect all column names across all rows
        all_columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for col in row:
                if col not in seen:
                    seen.add(col)
                    all_columns.append(col)

        # Prepare row data, serializing complex types to JSON strings
        data: list[list[Any]] = []
        for row in rows:
            row_values: list[Any] = []
            for col in all_columns:
                val = row.get(col)
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                row_values.append(val)
            data.append(row_values)

        self.client.insert(safe_table, data, column_names=all_columns)
        return len(rows)

    def table_exists(self, table: str) -> bool:
        row = self.fetch_one(
            "SELECT count() AS cnt FROM system.tables "
            "WHERE database = currentDatabase() AND name = %s",
            (table,),
        )
        return bool(row and row["cnt"] > 0)

    def get_table_schema(self, table: str) -> list[dict[str, str]]:
        rows = self.fetch_all(
            "SELECT name, type, default_kind, is_in_primary_key "
            "FROM system.columns "
            "WHERE database = currentDatabase() AND table = %s "
            "ORDER BY position",
            (table,),
        )
        result: list[dict[str, str]] = []
        for r in rows:
            col_type = r["type"]
            nullable = "YES" if col_type.startswith("Nullable") else "NO"
            result.append({
                "name": r["name"],
                "type": col_type,
                "nullable": nullable,
                "primary_key": "YES" if r["is_in_primary_key"] else "NO",
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
            col_defs.append(f"{safe_col} {col_type}")

        cols_sql = ", ".join(col_defs)
        order_by = sanitize_identifier(primary_key) if primary_key else "tuple()"
        engine = self.config.options.get("engine", "MergeTree()")

        sql = (
            f"CREATE TABLE IF NOT EXISTS {safe_table} ({cols_sql}) "
            f"ENGINE = {engine} ORDER BY {order_by}"
        )
        self.execute(sql)

    def get_server_info(self) -> dict[str, str]:
        row = self.fetch_one("SELECT version() AS ver")
        version = row["ver"] if row else "unknown"
        return {
            "type": "clickhouse",
            "version": version,
            "host": self.config.host or "localhost",
            "database": self.config.database or "default",
        }

    def _begin_transaction(self) -> None:
        logger.debug("ClickHouse: BEGIN is a no-op (limited transaction support)")

    def _commit_transaction(self) -> None:
        logger.debug("ClickHouse: COMMIT is a no-op (limited transaction support)")

    def _rollback_transaction(self) -> None:
        logger.debug("ClickHouse: ROLLBACK is a no-op (limited transaction support)")
