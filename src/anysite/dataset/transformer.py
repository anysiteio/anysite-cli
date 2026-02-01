"""Record transformer — filter, field selection, and column injection.

Applies per-source transforms to collected records before Parquet storage.
The filter parser is intentionally safe: no ``eval()``, only tokenize → parse.
"""

from __future__ import annotations

import re
from typing import Any

from anysite.dataset.models import TransformConfig


class FilterParseError(Exception):
    """Raised when a filter expression cannot be parsed."""


class RecordTransformer:
    """Apply transform pipeline: filter → select fields → add columns."""

    def __init__(self, config: TransformConfig) -> None:
        self.config = config
        self._filter_fn = _parse_filter(config.filter) if config.filter else None

    def apply(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = records

        # 1. Filter
        if self._filter_fn:
            result = [r for r in result if self._filter_fn(r)]

        # 2. Select fields
        if self.config.fields:
            result = [_select_fields(r, self.config.fields) for r in result]

        # 3. Add static columns
        if self.config.add_columns:
            for r in result:
                r.update(self.config.add_columns)

        return result


# ---------------------------------------------------------------------------
# Safe filter parser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<field>\.[a-zA-Z_][a-zA-Z0-9_.]*) |  # .field.path
        (?P<string>"[^"]*"|'[^']*')            |  # quoted string
        (?P<number>-?\d+(?:\.\d+)?)            |  # number
        (?P<op>==|!=|>=|<=|>|<)                |  # comparison
        (?P<logic>and|or)                      |  # logical
        (?P<null>null|none|None)                  # null literal
    )\s*
    """,
    re.VERBOSE,
)


def _tokenize(expr: str) -> list[tuple[str, str]]:
    """Tokenize a filter expression into (type, value) pairs."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise FilterParseError(f"Unexpected character at position {pos}: {expr[pos:]!r}")
        for name in ("field", "string", "number", "op", "logic", "null"):
            val = m.group(name)
            if val is not None:
                tokens.append((name, val))
                break
        pos = m.end()
    return tokens


def _parse_filter(expr: str) -> Any:
    """Parse a filter expression into a callable predicate.

    Supported syntax:
        .field > 10
        .name != ""
        .status == "active" and .count > 0
        .field != null
    """
    if not expr or not expr.strip():
        return None

    tokens = _tokenize(expr)
    if not tokens:
        raise FilterParseError(f"Empty filter expression: {expr!r}")

    # Parse into comparisons joined by and/or
    comparisons: list[tuple[str, str, Any]] = []  # (field, op, value)
    connectors: list[str] = []  # 'and' | 'or'

    i = 0
    while i < len(tokens):
        # Expect: field op value
        if i >= len(tokens) or tokens[i][0] != "field":
            raise FilterParseError(f"Expected field, got {tokens[i] if i < len(tokens) else 'end'}")
        field_path = tokens[i][1][1:]  # strip leading dot
        i += 1

        if i >= len(tokens) or tokens[i][0] != "op":
            raise FilterParseError(f"Expected operator after .{field_path}")
        op = tokens[i][1]
        i += 1

        if i >= len(tokens):
            raise FilterParseError(f"Expected value after .{field_path} {op}")

        tok_type, tok_val = tokens[i]
        if tok_type == "string":
            value: Any = tok_val[1:-1]  # strip quotes
        elif tok_type == "number":
            value = float(tok_val) if "." in tok_val else int(tok_val)
        elif tok_type == "null":
            value = None
        else:
            raise FilterParseError(f"Expected value, got {tokens[i]}")
        i += 1

        comparisons.append((field_path, op, value))

        # Check for connector
        if i < len(tokens):
            if tokens[i][0] == "logic":
                connectors.append(tokens[i][1])
                i += 1
            else:
                raise FilterParseError(f"Expected 'and'/'or', got {tokens[i]}")

    # Build callable
    def _eval_comparison(record: dict[str, Any], field: str, op: str, val: Any) -> bool:
        actual = _get_dot_value(record, field)
        if val is None:
            if op == "==":
                return actual is None
            if op == "!=":
                return actual is not None
            return False
        if actual is None:
            return False
        try:
            if op == "==":
                return actual == val
            if op == "!=":
                return actual != val
            if op == ">":
                return actual > val
            if op == "<":
                return actual < val
            if op == ">=":
                return actual >= val
            if op == "<=":
                return actual <= val
        except TypeError:
            return False
        return False

    def predicate(record: dict[str, Any]) -> bool:
        results = [_eval_comparison(record, f, o, v) for f, o, v in comparisons]
        if not connectors:
            return results[0]
        # Evaluate left to right: and binds tighter than or
        # Simple left-to-right evaluation
        result = results[0]
        for idx, conn in enumerate(connectors):
            if conn == "and":
                result = result and results[idx + 1]
            else:  # or
                result = result or results[idx + 1]
        return result

    return predicate


def _get_dot_value(record: dict[str, Any], path: str) -> Any:
    """Get a nested value using dot notation."""
    current: Any = record
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _select_fields(record: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Select specific fields from a record, supporting dot notation."""
    result: dict[str, Any] = {}
    for field in fields:
        # Support "path.to.field AS alias" syntax
        if " AS " in field:
            path, _, alias = field.partition(" AS ")
            path = path.strip()
            alias = alias.strip()
        elif " as " in field:
            path, _, alias = field.partition(" as ")
            path = path.strip()
            alias = alias.strip()
        else:
            path = field
            alias = field.replace(".", "_") if "." in field else field

        value = _get_dot_value(record, path)
        result[alias] = value
    return result
