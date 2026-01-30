"""Output formatters for different formats."""

import csv
import io
from enum import Enum
from pathlib import Path
from typing import Any

import orjson
from rich.table import Table

from anysite.output.console import console


class OutputFormat(str, Enum):
    """Supported output formats."""

    JSON = "json"
    JSONL = "jsonl"
    CSV = "csv"
    TABLE = "table"


def filter_fields(data: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Filter dictionary to only include specified fields.

    Supports nested fields with dot notation (e.g., 'experience.company').

    Args:
        data: Source dictionary
        fields: List of field names to include

    Returns:
        Filtered dictionary
    """
    if not fields:
        return data

    result: dict[str, Any] = {}
    for field in fields:
        if "." in field:
            # Handle nested fields
            parts = field.split(".")
            value = data
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                elif isinstance(value, list) and part.isdigit():
                    idx = int(part)
                    value = value[idx] if idx < len(value) else None
                else:
                    value = None
                    break
            if value is not None:
                # Store in nested structure
                current = result
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[parts[-1]] = value
        elif field in data:
            result[field] = data[field]

    return result


def flatten_for_csv(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dictionary for CSV output.

    Args:
        data: Nested dictionary
        prefix: Prefix for nested keys

    Returns:
        Flattened dictionary with dot-notation keys
    """
    result: dict[str, Any] = {}

    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            result.update(flatten_for_csv(value, full_key))
        elif isinstance(value, list):
            if all(isinstance(item, (str, int, float, bool, type(None))) for item in value):
                # Simple list - join as string
                result[full_key] = "; ".join(str(v) for v in value if v is not None)
            else:
                # Complex list - take length or first few items
                result[f"{full_key}_count"] = len(value)
                for i, item in enumerate(value[:3]):  # Max 3 items
                    if isinstance(item, dict):
                        result.update(flatten_for_csv(item, f"{full_key}_{i}"))
                    else:
                        result[f"{full_key}_{i}"] = item
        else:
            result[full_key] = value

    return result


def format_json(data: Any, indent: bool = True) -> str:
    """Format data as JSON.

    Args:
        data: Data to format
        indent: Whether to indent (pretty print)

    Returns:
        JSON string
    """
    option = orjson.OPT_INDENT_2 if indent else 0
    return orjson.dumps(data, option=option).decode("utf-8")


def format_jsonl(data: list[dict[str, Any]]) -> str:
    """Format data as newline-delimited JSON (JSONL).

    Args:
        data: List of dictionaries

    Returns:
        JSONL string with one JSON object per line
    """
    lines = [orjson.dumps(item).decode("utf-8") for item in data]
    return "\n".join(lines)


def format_csv_output(data: list[dict[str, Any]], fields: list[str] | None = None) -> str:
    """Format data as CSV.

    Args:
        data: List of dictionaries
        fields: Optional list of fields to include

    Returns:
        CSV string with headers
    """
    if not data:
        return ""

    # Flatten all records
    flattened = [flatten_for_csv(item) for item in data]

    # Get all unique keys for headers
    if fields:
        headers = fields
    else:
        headers = list(dict.fromkeys(key for item in flattened for key in item.keys()))

    # Write CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(flattened)
    return output.getvalue()


def format_table_output(data: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    """Format data as a Rich table and print to console.

    Args:
        data: List of dictionaries
        fields: Optional list of fields to include
    """
    if not data:
        console.print("[dim]No results[/dim]")
        return

    # For single item, display vertically
    if len(data) == 1:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Field", style="cyan")
        table.add_column("Value")

        item = data[0]
        if fields:
            item = filter_fields(item, fields)

        for key, value in item.items():
            if isinstance(value, (dict, list)):
                value = format_json(value, indent=False)
            table.add_row(key, str(value) if value is not None else "[dim]null[/dim]")

        console.print(table)
        return

    # For multiple items, display as grid
    # Flatten for tabular display
    flattened = [flatten_for_csv(item) for item in data]

    if fields:
        headers = fields
    else:
        # Select most important fields (limit columns for readability)
        all_keys = list(dict.fromkeys(key for item in flattened for key in item.keys()))
        # Prioritize common fields
        priority_fields = ["name", "full_name", "headline", "title", "company", "url", "followers"]
        headers = [f for f in priority_fields if f in all_keys]
        headers.extend([f for f in all_keys if f not in headers][:10 - len(headers)])

    # Create table
    table = Table(show_header=True, header_style="bold")
    for header in headers:
        table.add_column(header)

    for item in flattened:
        row = []
        for header in headers:
            value = item.get(header, "")
            if isinstance(value, (dict, list)):
                value = "..."
            row.append(str(value) if value is not None else "")
        table.add_row(*row)

    console.print(table)


def format_output(
    data: Any,
    output_format: OutputFormat,
    fields: list[str] | None = None,
    output_file: Path | None = None,
    quiet: bool = False,
    exclude: list[str] | None = None,
    compact: bool = False,
    append: bool = False,
) -> None:
    """Format and output data in the specified format.

    Args:
        data: Data to format (usually list of dicts from API)
        output_format: Output format (json, jsonl, csv, table)
        fields: Optional list of fields to include
        output_file: Optional file path to write output
        quiet: Suppress non-data output
        exclude: Optional list of fields to exclude
        compact: Use compact output (no indentation)
        append: Append to existing file
    """
    # Ensure data is a list
    if not isinstance(data, list):
        data = [data]

    # Filter fields if specified
    if fields:
        data = [filter_fields(item, fields) for item in data]

    # Exclude fields if specified
    if exclude:
        from anysite.utils.fields import exclude_fields
        data = [exclude_fields(item, exclude) for item in data]

    # Format based on type
    if output_format == OutputFormat.TABLE:
        if output_file:
            # Table can't be written to file, fall back to JSON
            formatted = format_json(data, indent=not compact)
            _write_output(formatted, output_file, quiet, append=append)
        else:
            format_table_output(data, fields)
        return

    if output_format == OutputFormat.JSON:
        formatted = format_json(data, indent=not compact)
    elif output_format == OutputFormat.JSONL:
        formatted = format_jsonl(data)
    elif output_format == OutputFormat.CSV:
        formatted = format_csv_output(data, fields)
    else:
        formatted = format_json(data, indent=not compact)

    _write_output(formatted, output_file, quiet, append=append)


def _write_output(
    content: str,
    output_file: Path | None,
    quiet: bool,
    append: bool = False,
) -> None:
    """Write content to file or stdout.

    Args:
        content: Content to write
        output_file: Optional file path
        quiet: Suppress messages
        append: Append to existing file
    """
    if output_file:
        mode = "a" if append else "w"
        with open(output_file, mode, encoding="utf-8") as f:
            f.write(content)
        if not quiet:
            from anysite.output.console import print_success

            action = "appended to" if append else "saved to"
            print_success(f"Output {action} {output_file}")
    else:
        print(content)
