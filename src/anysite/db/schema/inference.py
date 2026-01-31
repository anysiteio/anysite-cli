"""Type inference for JSON data to SQL schemas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from anysite.db.schema.types import get_sql_type

# Patterns for string subtype detection
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Threshold for using TEXT vs VARCHAR
_VARCHAR_MAX_LENGTH = 255


@dataclass
class ColumnSchema:
    """Schema for a single column."""

    name: str
    inferred_type: str
    nullable: bool = True
    sample_values: list[Any] = field(default_factory=list)


@dataclass
class TableSchema:
    """Schema for a table inferred from JSON data."""

    table_name: str
    columns: list[ColumnSchema] = field(default_factory=list)

    def to_sql_types(self, dialect: str) -> dict[str, str]:
        """Convert inferred types to SQL types for a given dialect.

        Args:
            dialect: Database dialect ('sqlite', 'postgres', 'mysql').

        Returns:
            Mapping of column name to SQL type string.
        """
        return {
            col.name: get_sql_type(col.inferred_type, dialect)
            for col in self.columns
        }


def infer_sql_type(value: Any) -> str:
    """Infer the SQL-compatible type for a Python value.

    Args:
        value: A Python value from JSON.

    Returns:
        Inferred type name ('integer', 'float', 'boolean', 'text', etc.).
    """
    if value is None:
        return "text"

    if isinstance(value, bool):
        return "boolean"

    if isinstance(value, int):
        return "integer"

    if isinstance(value, float):
        return "float"

    if isinstance(value, (dict, list)):
        return "json"

    if isinstance(value, str):
        return _infer_string_subtype(value)

    return "text"


def _infer_string_subtype(value: str) -> str:
    """Infer a more specific type for string values.

    Args:
        value: String value to analyze.

    Returns:
        Inferred type name.
    """
    if not value:
        return "text"

    if _DATETIME_RE.match(value):
        return "datetime"

    if _DATE_RE.match(value):
        return "date"

    if _URL_RE.match(value):
        return "url"

    if _EMAIL_RE.match(value):
        return "email"

    if len(value) <= _VARCHAR_MAX_LENGTH:
        return "varchar"

    return "text"


def _merge_types(type_a: str, type_b: str) -> str:
    """Merge two inferred types into a compatible type.

    When different rows have different types for the same column,
    this picks the more general type.
    """
    if type_a == type_b:
        return type_a

    # Null/text absorbs anything
    if type_a == "text" or type_b == "text":
        return "text"

    # Numeric promotion
    if {type_a, type_b} == {"integer", "float"}:
        return "float"

    # String subtypes fall back to varchar or text
    string_types = {"varchar", "url", "email", "date", "datetime"}
    if type_a in string_types and type_b in string_types:
        return "varchar"

    # JSON stays as json
    if type_a == "json" or type_b == "json":
        return "json"

    return "text"


def infer_table_schema(
    table_name: str,
    rows: list[dict[str, Any]],
    max_sample: int = 100,
) -> TableSchema:
    """Infer a table schema from a list of JSON rows.

    Examines up to max_sample rows to determine column types.

    Args:
        table_name: Name for the inferred table.
        rows: List of row dictionaries.
        max_sample: Maximum number of rows to sample for inference.

    Returns:
        Inferred TableSchema.
    """
    if not rows:
        return TableSchema(table_name=table_name)

    sample = rows[:max_sample]

    # Track column types and nullability
    column_types: dict[str, str] = {}
    column_nullable: dict[str, bool] = {}
    column_samples: dict[str, list[Any]] = {}
    # Preserve column order across all rows
    column_order: list[str] = []
    seen_columns: set[str] = set()

    for row in sample:
        for col_name, value in row.items():
            if col_name not in seen_columns:
                seen_columns.add(col_name)
                column_order.append(col_name)

            inferred = infer_sql_type(value)

            if value is None:
                column_nullable[col_name] = True
            else:
                if col_name in column_types:
                    column_types[col_name] = _merge_types(column_types[col_name], inferred)
                else:
                    column_types[col_name] = inferred

                if col_name not in column_nullable:
                    column_nullable[col_name] = False

                # Store sample values (up to 3)
                samples = column_samples.setdefault(col_name, [])
                if len(samples) < 3:
                    samples.append(value)

        # Mark missing columns as nullable
        for col_name in seen_columns:
            if col_name not in row:
                column_nullable[col_name] = True

    columns = [
        ColumnSchema(
            name=col_name,
            inferred_type=column_types.get(col_name, "text"),
            nullable=column_nullable.get(col_name, True),
            sample_values=column_samples.get(col_name, []),
        )
        for col_name in column_order
    ]

    return TableSchema(table_name=table_name, columns=columns)
