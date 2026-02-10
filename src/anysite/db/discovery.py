"""Database discovery — introspect schema, sample data, and build a catalog."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from anysite.db.adapters.base import DatabaseAdapter

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    default: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.primary_key:
            d["primary_key"] = True
        if not self.nullable:
            d["nullable"] = False
        if self.default is not None:
            d["default"] = self.default
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColumnInfo:
        return cls(
            name=data["name"],
            type=data["type"],
            nullable=data.get("nullable", True),
            primary_key=data.get("primary_key", False),
            default=data.get("default"),
            description=data.get("description"),
        )


@dataclass
class IndexInfo:
    name: str
    columns: list[str]
    unique: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "columns": self.columns}
        if self.unique:
            d["unique"] = True
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexInfo:
        return cls(
            name=data["name"],
            columns=data["columns"],
            unique=data.get("unique", False),
        )


@dataclass
class ForeignKeyInfo:
    constrained_columns: list[str]
    referred_table: str
    referred_columns: list[str]
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "constrained_columns": self.constrained_columns,
            "referred_table": self.referred_table,
            "referred_columns": self.referred_columns,
        }
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForeignKeyInfo:
        return cls(
            constrained_columns=data["constrained_columns"],
            referred_table=data["referred_table"],
            referred_columns=data["referred_columns"],
            name=data.get("name"),
        )


@dataclass
class ImplicitRelationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_table": self.from_table,
            "from_column": self.from_column,
            "to_table": self.to_table,
            "to_column": self.to_column,
            "confidence": self.confidence,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImplicitRelationship:
        return cls(
            from_table=data["from_table"],
            from_column=data["from_column"],
            to_table=data["to_table"],
            to_column=data["to_column"],
            confidence=data.get("confidence", 0.0),
            reason=data.get("reason", ""),
        )


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    row_count: int | None = None
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "columns": [c.to_dict() for c in self.columns],
        }
        if self.row_count is not None:
            d["row_count"] = self.row_count
        if self.indexes:
            d["indexes"] = [i.to_dict() for i in self.indexes]
        if self.foreign_keys:
            d["foreign_keys"] = [fk.to_dict() for fk in self.foreign_keys]
        if self.sample_rows:
            d["sample_rows"] = self.sample_rows
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableInfo:
        return cls(
            name=data["name"],
            columns=[ColumnInfo.from_dict(c) for c in data.get("columns", [])],
            row_count=data.get("row_count"),
            sample_rows=data.get("sample_rows", []),
            indexes=[IndexInfo.from_dict(i) for i in data.get("indexes", [])],
            foreign_keys=[ForeignKeyInfo.from_dict(fk) for fk in data.get("foreign_keys", [])],
            description=data.get("description"),
        )


@dataclass
class DatabaseCatalog:
    connection_name: str
    database_type: str
    server_info: dict[str, str]
    tables: list[TableInfo]
    discovered_at: str
    description: str | None = None
    llm_enriched: bool = False
    read_only: bool | None = None
    implicit_relationships: list[ImplicitRelationship] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "connection_name": self.connection_name,
            "database_type": self.database_type,
            "discovered_at": self.discovered_at,
            "server_info": self.server_info,
            "llm_enriched": self.llm_enriched,
            "tables": [t.to_dict() for t in self.tables],
        }
        if self.read_only is not None:
            d["read_only"] = self.read_only
        if self.description:
            d["description"] = self.description
        if self.implicit_relationships:
            d["implicit_relationships"] = [r.to_dict() for r in self.implicit_relationships]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseCatalog:
        return cls(
            connection_name=data["connection_name"],
            database_type=data["database_type"],
            server_info=data.get("server_info", {}),
            tables=[TableInfo.from_dict(t) for t in data.get("tables", [])],
            discovered_at=data.get("discovered_at", ""),
            description=data.get("description"),
            llm_enriched=data.get("llm_enriched", False),
            read_only=data.get("read_only"),
            implicit_relationships=[
                ImplicitRelationship.from_dict(r)
                for r in data.get("implicit_relationships", [])
            ],
        )

    def get_table(self, name: str) -> TableInfo | None:
        for t in self.tables:
            if t.name == name:
                return t
        return None

    def to_context_string(self) -> str:
        """Compact text representation for agent/LLM context injection."""
        lines = [f"Database: {self.connection_name} ({self.database_type})"]
        if self.read_only is not None:
            lines.append(f"Access: {'read-only' if self.read_only else 'read-write'}")
        if self.description:
            lines.append(f"Description: {self.description}")
        lines.append("")
        for t in self.tables:
            header = f"Table: {t.name}"
            if t.row_count is not None:
                header += f" ({t.row_count:,} rows)"
            if t.description:
                header += f" — {t.description}"
            lines.append(header)
            for col in t.columns:
                parts = [f"  - {col.name}: {col.type}"]
                if col.primary_key:
                    parts.append("PK")
                if not col.nullable:
                    parts.append("NOT NULL")
                if col.description:
                    parts.append(f"— {col.description}")
                lines.append(" ".join(parts))
            if t.foreign_keys:
                for fk in t.foreign_keys:
                    lines.append(
                        f"  FK: {', '.join(fk.constrained_columns)} → "
                        f"{fk.referred_table}({', '.join(fk.referred_columns)})"
                    )
            lines.append("")
        if self.implicit_relationships:
            lines.append("Implicit relationships:")
            for r in self.implicit_relationships:
                lines.append(
                    f"  {r.from_table}.{r.from_column} → "
                    f"{r.to_table}.{r.to_column} ({r.reason})"
                )
        return "\n".join(lines)


# ── Discovery engine ──────────────────────────────────────────────────


class DatabaseDiscoverer:
    """Introspects a database and builds a DatabaseCatalog."""

    def __init__(
        self,
        adapter: DatabaseAdapter,
        db_type: str,
        connection_name: str,
    ) -> None:
        self._adapter = adapter
        self._db_type = db_type
        self._connection_name = connection_name

    def discover(
        self,
        *,
        sample_rows: int = 1,
        include_tables: list[str] | None = None,
        exclude_tables: list[str] | None = None,
        force_read_only: bool = False,
    ) -> DatabaseCatalog:
        """Discover the database schema and build a catalog.

        Args:
            sample_rows: Number of sample rows per table (0 to skip).
            include_tables: Only discover these tables.
            exclude_tables: Skip these tables.
            force_read_only: Force read-only flag (from connection config).
        """
        server_info = self._adapter.get_server_info()
        table_names = self._list_tables()

        if include_tables:
            table_names = [t for t in table_names if t in include_tables]
        if exclude_tables:
            table_names = [t for t in table_names if t not in exclude_tables]

        tables: list[TableInfo] = []
        for name in table_names:
            logger.debug("Discovering table: %s", name)
            table = self._discover_table(name, sample_rows=sample_rows)
            tables.append(table)

        read_only = True if force_read_only else self._probe_write_access()

        return DatabaseCatalog(
            connection_name=self._connection_name,
            database_type=self._db_type,
            server_info=server_info,
            tables=tables,
            discovered_at=datetime.now(UTC).isoformat(timespec="seconds"),
            read_only=read_only,
        )

    def _list_tables(self) -> list[str]:
        if self._db_type == "sqlite":
            rows = self._adapter.fetch_all(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
            return [r["name"] for r in rows]
        elif self._db_type == "postgres":
            rows = self._adapter.fetch_all(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
            return [r["tablename"] for r in rows]
        elif self._db_type == "clickhouse":
            rows = self._adapter.fetch_all(
                "SELECT name FROM system.tables "
                "WHERE database = currentDatabase() "
                "AND engine NOT IN ('View', 'MaterializedView') "
                "ORDER BY name"
            )
            return [r["name"] for r in rows]
        return []

    def _probe_write_access(self) -> bool | None:
        """Check if the connection has write access without writing anything.

        Uses metadata queries (PostgreSQL/ClickHouse) or filesystem checks (SQLite).

        Returns:
            True if read-only, False if writable, None if unable to determine.
        """
        if self._db_type == "postgres":
            try:
                row = self._adapter.fetch_one(
                    "SELECT "
                    "  has_schema_privilege(current_user, 'public', 'CREATE') AS can_create, "
                    "  pg_is_in_recovery() AS is_replica, "
                    "  current_setting('default_transaction_read_only') AS txn_ro"
                )
                if row:
                    if row["is_replica"] or row["txn_ro"] == "on":
                        return True
                    return not row["can_create"]
            except Exception:
                logger.debug("Failed to probe write access", exc_info=True)
        elif self._db_type == "clickhouse":
            try:
                # Check session-level readonly setting
                row = self._adapter.fetch_one(
                    "SELECT value FROM system.settings WHERE name = 'readonly'"
                )
                if row and str(row["value"]) != "0":
                    return True
            except Exception:
                logger.debug("Failed to check readonly setting", exc_info=True)
            try:
                # Check user grants for write access
                write_rows = self._adapter.fetch_all(
                    "SELECT access_type FROM system.grants "
                    "WHERE user_name = currentUser() "
                    "AND access_type IN ("
                    "'INSERT', 'CREATE TABLE', 'ALTER TABLE', "
                    "'DROP TABLE', 'CREATE', 'ALL')"
                )
                if not write_rows:
                    return True
                return False
            except Exception:
                logger.debug("Failed to check grants", exc_info=True)
            # Fallback: try a harmless EXPLAIN to probe write access
            try:
                self._adapter.fetch_all(
                    "EXPLAIN CREATE TEMPORARY TABLE __anysite_probe (x Int8) ENGINE = Memory"
                )
                return False
            except Exception:
                return True
        elif self._db_type == "sqlite":
            import os

            path = getattr(self._adapter, 'db_path', None)
            if path and path != ":memory:":
                return not os.access(path, os.W_OK)
            # In-memory DBs are always writable
            return False
        return None

    def _discover_table(self, table_name: str, *, sample_rows: int) -> TableInfo:
        columns = self._get_columns(table_name)
        row_count = self._get_row_count(table_name)
        samples = self._get_sample_rows(table_name, sample_rows) if sample_rows > 0 else []
        indexes = self._get_indexes(table_name)
        foreign_keys = self._get_foreign_keys(table_name)

        return TableInfo(
            name=table_name,
            columns=columns,
            row_count=row_count,
            sample_rows=samples,
            indexes=indexes,
            foreign_keys=foreign_keys,
        )

    def _get_columns(self, table_name: str) -> list[ColumnInfo]:
        if self._db_type == "sqlite":
            return self._get_columns_sqlite(table_name)
        elif self._db_type == "postgres":
            return self._get_columns_postgres(table_name)
        elif self._db_type == "clickhouse":
            return self._get_columns_clickhouse(table_name)
        return []

    def _get_columns_sqlite(self, table_name: str) -> list[ColumnInfo]:
        rows = self._adapter.fetch_all(f"PRAGMA table_info('{table_name}')")
        columns = []
        for r in rows:
            columns.append(
                ColumnInfo(
                    name=r["name"],
                    type=r["type"] or "TEXT",
                    nullable=not bool(r["notnull"]),
                    primary_key=bool(r["pk"]),
                    default=str(r["dflt_value"]) if r["dflt_value"] is not None else None,
                )
            )
        return columns

    def _get_columns_postgres(self, table_name: str) -> list[ColumnInfo]:
        rows = self._adapter.fetch_all(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (table_name,),
        )
        # Get primary key columns
        pk_rows = self._adapter.fetch_all(
            "SELECT a.attname "
            "FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "JOIN pg_class c ON c.oid = i.indrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = %s AND n.nspname = 'public' AND i.indisprimary",
            (table_name,),
        )
        pk_columns = {r["attname"] for r in pk_rows}

        columns = []
        for r in rows:
            columns.append(
                ColumnInfo(
                    name=r["column_name"],
                    type=r["data_type"].upper(),
                    nullable=r["is_nullable"] == "YES",
                    primary_key=r["column_name"] in pk_columns,
                    default=r["column_default"],
                )
            )
        return columns

    def _get_columns_clickhouse(self, table_name: str) -> list[ColumnInfo]:
        rows = self._adapter.fetch_all(
            "SELECT name, type, default_kind, is_in_primary_key "
            "FROM system.columns "
            "WHERE database = currentDatabase() AND table = %s "
            "ORDER BY position",
            (table_name,),
        )
        columns = []
        for r in rows:
            col_type = r["type"]
            nullable = col_type.startswith("Nullable(")
            columns.append(
                ColumnInfo(
                    name=r["name"],
                    type=col_type,
                    nullable=nullable,
                    primary_key=bool(r["is_in_primary_key"]),
                    default=r["default_kind"] if r["default_kind"] else None,
                )
            )
        return columns

    def _get_row_count(self, table_name: str) -> int | None:
        try:
            if self._db_type == "postgres":
                # Use pg_class estimate for large tables
                row = self._adapter.fetch_one(
                    "SELECT reltuples::bigint AS estimate "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relname = %s AND n.nspname = 'public'",
                    (table_name,),
                )
                if row and row["estimate"] >= 0:
                    estimate = int(row["estimate"])
                    # For small tables or stale stats, do exact count
                    if estimate < 10000:
                        exact = self._adapter.fetch_one(
                            f'SELECT COUNT(*) AS cnt FROM "{table_name}"'
                        )
                        return exact["cnt"] if exact else 0
                    return estimate
            elif self._db_type == "clickhouse":
                row = self._adapter.fetch_one(
                    "SELECT sum(rows) AS estimate FROM system.parts "
                    "WHERE database = currentDatabase() "
                    "AND table = %s AND active",
                    (table_name,),
                )
                if row and row["estimate"] is not None:
                    return int(row["estimate"])
                return 0
            # SQLite or fallback: exact count
            row = self._adapter.fetch_one(
                f'SELECT COUNT(*) AS cnt FROM "{table_name}"'
            )
            return row["cnt"] if row else 0
        except Exception:
            logger.debug("Failed to get row count for %s", table_name, exc_info=True)
            return None

    def _get_sample_rows(self, table_name: str, limit: int) -> list[dict[str, Any]]:
        try:
            rows = self._adapter.fetch_all(
                f'SELECT * FROM "{table_name}" LIMIT {limit}'
            )
            # Serialize to YAML-safe primitives (str, int, float, bool, None)
            clean_rows: list[dict[str, Any]] = []
            for row in rows:
                clean: dict[str, Any] = {}
                for k, v in row.items():
                    if v is None or isinstance(v, str | int | float | bool):
                        clean[k] = v
                    elif isinstance(v, dict | list):
                        clean[k] = json.dumps(v)
                    elif isinstance(v, bytes):
                        clean[k] = f"<{len(v)} bytes>"
                    else:
                        # UUID, datetime, Decimal, etc. → string
                        clean[k] = str(v)
                clean_rows.append(clean)
            return clean_rows
        except Exception:
            logger.debug("Failed to get sample rows for %s", table_name, exc_info=True)
            return []

    def _get_indexes(self, table_name: str) -> list[IndexInfo]:
        if self._db_type == "sqlite":
            return self._get_indexes_sqlite(table_name)
        elif self._db_type == "postgres":
            return self._get_indexes_postgres(table_name)
        elif self._db_type == "clickhouse":
            return self._get_indexes_clickhouse(table_name)
        return []

    def _get_indexes_sqlite(self, table_name: str) -> list[IndexInfo]:
        indexes: list[IndexInfo] = []
        rows = self._adapter.fetch_all(f"PRAGMA index_list('{table_name}')")
        for r in rows:
            idx_name = r["name"]
            is_unique = bool(r["unique"])
            cols_rows = self._adapter.fetch_all(f"PRAGMA index_info('{idx_name}')")
            cols = [cr["name"] for cr in cols_rows]
            indexes.append(IndexInfo(name=idx_name, columns=cols, unique=is_unique))
        return indexes

    def _get_indexes_postgres(self, table_name: str) -> list[IndexInfo]:
        rows = self._adapter.fetch_all(
            "SELECT i.relname AS index_name, ix.indisunique AS is_unique, "
            "array_agg(a.attname ORDER BY k.n) AS columns "
            "FROM pg_index ix "
            "JOIN pg_class t ON t.oid = ix.indrelid "
            "JOIN pg_class i ON i.oid = ix.indexrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS k(attnum, n) ON TRUE "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
            "WHERE t.relname = %s AND n.nspname = 'public' "
            "GROUP BY i.relname, ix.indisunique "
            "ORDER BY i.relname",
            (table_name,),
        )
        return [
            IndexInfo(
                name=r["index_name"],
                columns=r["columns"],
                unique=bool(r["is_unique"]),
            )
            for r in rows
        ]

    def _get_indexes_clickhouse(self, table_name: str) -> list[IndexInfo]:
        indexes: list[IndexInfo] = []
        # Get sorting key (ORDER BY) as primary index
        try:
            row = self._adapter.fetch_one(
                "SELECT sorting_key FROM system.tables "
                "WHERE database = currentDatabase() "
                "AND name = %s",
                (table_name,),
            )
            if row and row["sorting_key"]:
                pk_cols = [c.strip() for c in row["sorting_key"].split(",")]
                indexes.append(IndexInfo(
                    name="PRIMARY_KEY (ORDER BY)",
                    columns=pk_cols,
                    unique=False,
                ))
        except Exception:
            logger.debug("Failed to get sorting key for %s", table_name, exc_info=True)

        # Get data skipping indexes
        try:
            rows = self._adapter.fetch_all(
                "SELECT name, expr, type "
                "FROM system.data_skipping_indices "
                "WHERE database = currentDatabase() "
                "AND table = %s",
                (table_name,),
            )
            for r in rows:
                indexes.append(IndexInfo(
                    name=r["name"],
                    columns=[r["expr"]],
                    unique=False,
                ))
        except Exception:
            logger.debug("Failed to get indexes for %s", table_name, exc_info=True)

        return indexes

    def _get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        if self._db_type == "sqlite":
            return self._get_foreign_keys_sqlite(table_name)
        elif self._db_type == "postgres":
            return self._get_foreign_keys_postgres(table_name)
        elif self._db_type == "clickhouse":
            return []  # ClickHouse does not support foreign keys
        return []

    def _get_foreign_keys_sqlite(self, table_name: str) -> list[ForeignKeyInfo]:
        rows = self._adapter.fetch_all(f"PRAGMA foreign_key_list('{table_name}')")
        # Group by id (each FK can span multiple columns)
        fk_groups: dict[int, dict[str, Any]] = {}
        for r in rows:
            fk_id = r["id"]
            if fk_id not in fk_groups:
                fk_groups[fk_id] = {
                    "table": r["table"],
                    "from": [],
                    "to": [],
                }
            fk_groups[fk_id]["from"].append(r["from"])
            fk_groups[fk_id]["to"].append(r["to"])

        return [
            ForeignKeyInfo(
                constrained_columns=g["from"],
                referred_table=g["table"],
                referred_columns=g["to"],
            )
            for g in fk_groups.values()
        ]

    def _get_foreign_keys_postgres(self, table_name: str) -> list[ForeignKeyInfo]:
        rows = self._adapter.fetch_all(
            "SELECT "
            "  tc.constraint_name, "
            "  array_agg(DISTINCT kcu.column_name) AS constrained_columns, "
            "  ccu.table_name AS referred_table, "
            "  array_agg(DISTINCT ccu.column_name) AS referred_columns "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name "
            "  AND tc.table_schema = ccu.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' "
            "  AND tc.table_schema = 'public' "
            "  AND tc.table_name = %s "
            "GROUP BY tc.constraint_name, ccu.table_name "
            "ORDER BY tc.constraint_name",
            (table_name,),
        )
        return [
            ForeignKeyInfo(
                constrained_columns=r["constrained_columns"],
                referred_table=r["referred_table"],
                referred_columns=r["referred_columns"],
                name=r["constraint_name"],
            )
            for r in rows
        ]
