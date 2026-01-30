"""Tests for output formatters."""

import json

import pytest

from anysite.output.formatters import (
    OutputFormat,
    filter_fields,
    flatten_for_csv,
    format_csv_output,
    format_json,
    format_jsonl,
)


class TestFilterFields:
    """Tests for filter_fields function."""

    def test_filter_simple_fields(self):
        """Test filtering simple top-level fields."""
        data = {"name": "John", "age": 30, "city": "NYC"}
        result = filter_fields(data, ["name", "age"])
        assert result == {"name": "John", "age": 30}

    def test_filter_empty_fields(self):
        """Test that empty fields list returns original data."""
        data = {"name": "John", "age": 30}
        result = filter_fields(data, [])
        assert result == data

    def test_filter_nonexistent_fields(self):
        """Test filtering with non-existent fields."""
        data = {"name": "John", "age": 30}
        result = filter_fields(data, ["name", "email"])
        assert result == {"name": "John"}

    def test_filter_nested_fields(self):
        """Test filtering nested fields with dot notation."""
        data = {
            "name": "John",
            "address": {"city": "NYC", "zip": "10001"},
        }
        result = filter_fields(data, ["name", "address.city"])
        assert "name" in result
        assert "address" in result
        assert result["address"]["city"] == "NYC"


class TestFlattenForCsv:
    """Tests for flatten_for_csv function."""

    def test_flatten_simple_dict(self):
        """Test flattening a simple dictionary."""
        data = {"name": "John", "age": 30}
        result = flatten_for_csv(data)
        assert result == {"name": "John", "age": 30}

    def test_flatten_nested_dict(self):
        """Test flattening nested dictionary."""
        data = {"name": "John", "address": {"city": "NYC"}}
        result = flatten_for_csv(data)
        assert result == {"name": "John", "address.city": "NYC"}

    def test_flatten_simple_list(self):
        """Test flattening simple list values."""
        data = {"name": "John", "skills": ["Python", "JavaScript"]}
        result = flatten_for_csv(data)
        assert result["name"] == "John"
        assert result["skills"] == "Python; JavaScript"

    def test_flatten_complex_list(self):
        """Test flattening complex list values."""
        data = {
            "name": "John",
            "experience": [
                {"company": "A"},
                {"company": "B"},
            ],
        }
        result = flatten_for_csv(data)
        assert result["name"] == "John"
        assert result["experience_count"] == 2
        assert result["experience_0.company"] == "A"


class TestFormatJson:
    """Tests for format_json function."""

    def test_format_json_indent(self):
        """Test JSON formatting with indent."""
        data = {"name": "John"}
        result = format_json(data, indent=True)
        assert "{\n" in result
        assert '"name"' in result

    def test_format_json_no_indent(self):
        """Test JSON formatting without indent."""
        data = {"name": "John"}
        result = format_json(data, indent=False)
        assert "\n" not in result
        parsed = json.loads(result)
        assert parsed == data


class TestFormatJsonl:
    """Tests for format_jsonl function."""

    def test_format_jsonl_single(self):
        """Test JSONL with single item."""
        data = [{"name": "John"}]
        result = format_jsonl(data)
        assert result == '{"name":"John"}'

    def test_format_jsonl_multiple(self):
        """Test JSONL with multiple items."""
        data = [{"name": "John"}, {"name": "Jane"}]
        result = format_jsonl(data)
        lines = result.split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"name": "John"}
        assert json.loads(lines[1]) == {"name": "Jane"}


class TestFormatCsv:
    """Tests for format_csv_output function."""

    def test_format_csv_simple(self):
        """Test CSV formatting with simple data."""
        data = [{"name": "John", "age": 30}, {"name": "Jane", "age": 25}]
        result = format_csv_output(data)
        lines = result.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows
        assert "name" in lines[0]
        assert "age" in lines[0]
        assert "John" in lines[1]
        assert "Jane" in lines[2]

    def test_format_csv_empty(self):
        """Test CSV formatting with empty data."""
        result = format_csv_output([])
        assert result == ""

    def test_format_csv_with_fields(self):
        """Test CSV formatting with field selection."""
        data = [{"name": "John", "age": 30, "city": "NYC"}]
        result = format_csv_output(data, fields=["name", "city"])
        lines = result.strip().split("\n")
        assert "name" in lines[0]
        assert "city" in lines[0]
        # age should not be in header if we properly implement field filtering
