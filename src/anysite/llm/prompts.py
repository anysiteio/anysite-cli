"""Prompt templates and builder for LLM commands."""

from __future__ import annotations

import re
from typing import Any

from anysite.llm.errors import PromptError

BUILTIN_PROMPTS: dict[str, str] = {
    "summarize": (
        "Summarize the following record in {max_length} words or less. "
        "Focus on the most important information.\n\n"
        "Record:\n{record}"
    ),
    "classify": (
        "Classify each of the following records into one of these categories: {categories}\n\n"
        "For each record, provide the category and a confidence score (0.0-1.0).\n\n"
        "Records:\n{records}"
    ),
    "classify_auto_detect": (
        "Analyze the following sample records and suggest 3-7 meaningful categories "
        "that would best classify this data. Return just the category names.\n\n"
        "Records:\n{records}"
    ),
    "match": (
        "Given this {source_a_name} record:\n{source_a_record}\n\n"
        "Rank the following {source_b_name} records by relevance. "
        "For each match, provide a score (0.0-1.0) and a brief reason.\n\n"
        "{source_b_name} records:\n{source_b_records}"
    ),
    "deduplicate": (
        "Examine these records and identify semantic duplicates. "
        "Two records are duplicates if they refer to the same real-world entity, "
        "even if the text differs slightly.\n\n"
        "Records:\n{records}"
    ),
    "enrich": (
        "Analyze the following record and extract these attributes:\n"
        "{field_descriptions}\n\n"
        "Record:\n{record}"
    ),
    "describe_table": (
        "Describe the purpose of this database table in one sentence.\n\n"
        "Table: {table_name}\n"
        "Columns: {columns}\n"
        "Row count: {row_count}\n"
        "{sample_data}"
    ),
    "describe_columns": (
        "For each column in this table, write a brief description (one phrase) "
        "of what data it stores.\n\n"
        "Table: {table_name}\n"
        "Columns:\n{columns}\n\n"
        "Sample data:\n{sample_data}"
    ),
    "describe_database": (
        "Describe the purpose of this database in one or two sentences.\n\n"
        "Database: {connection_name} ({database_type})\n"
        "Tables:\n{tables}"
    ),
    "detect_relationships": (
        "Examine these database tables and detect implicit foreign key "
        "relationships based on column naming patterns (e.g., user_id likely "
        "refers to users.id). Only report relationships where you are fairly "
        "confident. Do NOT report relationships that are already declared as "
        "foreign keys.\n\n"
        "Tables:\n{tables}"
    ),
}


class PromptBuilder:
    """Build prompts from templates and record data."""

    def __init__(self, template: str | None = None, builtin_key: str | None = None) -> None:
        if template:
            self._template = template
        elif builtin_key and builtin_key in BUILTIN_PROMPTS:
            self._template = BUILTIN_PROMPTS[builtin_key]
        else:
            raise PromptError(
                f"No prompt template provided. "
                f"Available built-in prompts: {', '.join(BUILTIN_PROMPTS.keys())}"
            )

    @property
    def template(self) -> str:
        return self._template

    def build(self, record: dict[str, Any], variables: dict[str, Any] | None = None) -> str:
        """Build a prompt for a single record.

        Replaces {field_name} placeholders from record fields and variables.
        """
        context: dict[str, Any] = {}
        if variables:
            context.update(variables)
        # Add formatted record
        context["record"] = _format_record(record)
        # Add individual record fields for {field_name} substitution
        context.update(record)
        return _safe_format(self._template, context)

    def build_for_batch(
        self, records: list[dict[str, Any]], variables: dict[str, Any] | None = None
    ) -> str:
        """Build a prompt for a batch of records."""
        context: dict[str, Any] = {}
        if variables:
            context.update(variables)
        context["records"] = _format_records_batch(records)
        return _safe_format(self._template, context)


def _format_record(record: dict[str, Any]) -> str:
    """Format a single record as readable text."""
    lines = []
    for key, value in record.items():
        if key.startswith("_"):
            continue
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def _format_records_batch(records: list[dict[str, Any]]) -> str:
    """Format multiple records with indices."""
    parts = []
    for i, record in enumerate(records):
        parts.append(f"[{i}] {_format_record(record)}")
    return "\n\n".join(parts)


def _safe_format(template: str, context: dict[str, Any]) -> str:
    """Format template with context, leaving unknown placeholders as-is."""

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in context:
            return str(context[key])
        return match.group(0)

    return re.sub(r"\{(\w+)\}", replacer, template)


def filter_record_fields(record: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Filter record to only include specified fields."""
    result: dict[str, Any] = {}
    for field in fields:
        field = field.strip()
        if "." in field:
            # Dot-notation: extract nested value
            parts = field.split(".")
            value: Any = record
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            if value is not None:
                result[field] = value
        elif field in record:
            result[field] = record[field]
    return result
