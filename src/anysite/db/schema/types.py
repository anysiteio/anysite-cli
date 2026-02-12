"""SQL type mappings per database dialect."""

from __future__ import annotations

# Type mapping: Python-inferred type name -> SQL type per dialect
TYPE_MAP: dict[str, dict[str, str]] = {
    "integer": {
        "sqlite": "INTEGER",
        "postgres": "BIGINT",
        "mysql": "BIGINT",
        "clickhouse": "Int64",
    },
    "float": {
        "sqlite": "REAL",
        "postgres": "DOUBLE PRECISION",
        "mysql": "DOUBLE",
        "clickhouse": "Float64",
    },
    "boolean": {
        "sqlite": "INTEGER",
        "postgres": "BOOLEAN",
        "mysql": "BOOLEAN",
        "clickhouse": "Bool",
    },
    "text": {
        "sqlite": "TEXT",
        "postgres": "TEXT",
        "mysql": "TEXT",
        "clickhouse": "String",
    },
    "varchar": {
        "sqlite": "TEXT",
        "postgres": "VARCHAR(255)",
        "mysql": "VARCHAR(255)",
        "clickhouse": "String",
    },
    "json": {
        "sqlite": "TEXT",
        "postgres": "JSONB",
        "mysql": "JSON",
        "clickhouse": "String",
    },
    "date": {
        "sqlite": "TEXT",
        "postgres": "DATE",
        "mysql": "DATE",
        "clickhouse": "Date",
    },
    "datetime": {
        "sqlite": "TEXT",
        "postgres": "TIMESTAMPTZ",
        "mysql": "DATETIME",
        "clickhouse": "DateTime",
    },
    "url": {
        "sqlite": "TEXT",
        "postgres": "TEXT",
        "mysql": "TEXT",
        "clickhouse": "String",
    },
    "email": {
        "sqlite": "TEXT",
        "postgres": "TEXT",
        "mysql": "VARCHAR(320)",
        "clickhouse": "String",
    },
}


def get_sql_type(inferred_type: str, dialect: str) -> str:
    """Get the SQL type for a given inferred type and dialect.

    Args:
        inferred_type: The inferred Python type name.
        dialect: The database dialect ('sqlite', 'postgres', 'mysql', 'clickhouse').

    Returns:
        SQL type string for the dialect.
    """
    type_entry = TYPE_MAP.get(inferred_type, TYPE_MAP["text"])
    return type_entry.get(dialect, type_entry.get("sqlite", "TEXT"))
