"""SQL identifier sanitization utilities."""

from __future__ import annotations

import re

# Valid SQL identifier: starts with letter/underscore, then letters/digits/underscores
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Reserved SQL keywords that must be quoted
_RESERVED_WORDS = frozenset({
    "all", "alter", "analyze", "and", "as", "asc", "between", "by", "case",
    "check", "column", "constraint", "create", "cross", "current", "current_date",
    "current_time", "current_timestamp", "current_user", "database", "default",
    "delete", "desc", "distinct", "do", "drop", "else", "end", "exists", "false",
    "fetch", "for", "foreign", "from", "full", "grant", "group", "having", "if",
    "in", "index", "inner", "insert", "into", "is", "join", "key", "left", "like",
    "limit", "natural", "not", "null", "offset", "on", "or", "order", "outer",
    "primary", "references", "returning", "right", "row", "select", "session_user",
    "set", "some", "table", "then", "to", "true", "union", "unique", "update",
    "user", "using", "values", "view", "when", "where", "with",
})

# Maximum identifier length (conservative across databases)
_MAX_IDENTIFIER_LENGTH = 63


def sanitize_identifier(name: str) -> str:
    """Sanitize a SQL identifier (column or table name).

    Rules:
    - Must be non-empty
    - Must start with a letter or underscore
    - Only letters, digits, and underscores allowed
    - Reserved words are quoted with double quotes
    - Max length 63 characters (PostgreSQL limit)
    - Invalid characters are replaced with underscores

    Args:
        name: Raw identifier name.

    Returns:
        Sanitized identifier safe for use in SQL.

    Raises:
        ValueError: If name is empty or cannot be sanitized.
    """
    if not name or not name.strip():
        raise ValueError("Identifier cannot be empty")

    # Strip whitespace
    cleaned = name.strip()

    # Replace invalid characters with underscores
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", cleaned)

    # Ensure starts with letter or underscore
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"

    # Collapse multiple underscores
    cleaned = re.sub(r"__+", "_", cleaned)

    # Strip trailing underscores
    cleaned = cleaned.rstrip("_")

    if not cleaned:
        raise ValueError(f"Identifier '{name}' cannot be sanitized to a valid name")

    # Truncate to max length
    cleaned = cleaned[:_MAX_IDENTIFIER_LENGTH]

    # Quote reserved words
    if cleaned.lower() in _RESERVED_WORDS:
        return f'"{cleaned}"'

    return cleaned


def sanitize_table_name(name: str) -> str:
    """Sanitize a table name, supporting schema-qualified names.

    Handles 'schema.table' notation by sanitizing each part separately.

    Args:
        name: Raw table name, optionally schema-qualified.

    Returns:
        Sanitized table name.

    Raises:
        ValueError: If name is empty or cannot be sanitized.
    """
    if not name or not name.strip():
        raise ValueError("Table name cannot be empty")

    parts = name.split(".", maxsplit=1)
    sanitized_parts = [sanitize_identifier(part) for part in parts]
    return ".".join(sanitized_parts)
