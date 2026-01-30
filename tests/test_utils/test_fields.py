"""Tests for enhanced field selection."""

from anysite.utils.fields import (
    exclude_fields,
    filter_fields,
    parse_field_path,
    resolve_fields_preset,
)


class TestParseFieldPath:
    def test_simple_key(self):
        result = parse_field_path("name")
        assert len(result) == 1
        assert result[0].type == "key"
        assert result[0].value == "name"

    def test_nested_dot_path(self):
        result = parse_field_path("experience.company")
        assert len(result) == 2
        assert result[0].value == "experience"
        assert result[1].value == "company"

    def test_array_index(self):
        result = parse_field_path("experience[0]")
        assert len(result) == 2
        assert result[0].type == "key"
        assert result[0].value == "experience"
        assert result[1].type == "index"
        assert result[1].value == 0

    def test_wildcard(self):
        result = parse_field_path("experience[*].company")
        assert len(result) == 3
        assert result[1].type == "wildcard"

    def test_complex_path(self):
        result = parse_field_path("experience[0].company.name")
        assert len(result) == 4


class TestFilterFields:
    def test_simple_filter(self):
        data = {"name": "Test", "age": 30, "email": "test@test.com"}
        result = filter_fields(data, ["name", "email"])
        assert result == {"name": "Test", "email": "test@test.com"}

    def test_filter_nested_path(self):
        data = {
            "name": "Test",
            "company": {"name": "Acme", "size": 100},
        }
        result = filter_fields(data, ["name", "company.name"])
        assert "name" in result
        assert "company" in result

    def test_filter_empty_fields(self):
        data = {"name": "Test", "age": 30}
        result = filter_fields(data, [])
        assert result == data

    def test_nonexistent_fields(self):
        data = {"name": "Test"}
        result = filter_fields(data, ["missing"])
        assert result == {}


class TestExcludeFields:
    def test_simple_exclude(self):
        data = {"name": "Test", "age": 30, "email": "test@test.com"}
        result = exclude_fields(data, ["age"])
        assert result == {"name": "Test", "email": "test@test.com"}

    def test_exclude_multiple(self):
        data = {"a": 1, "b": 2, "c": 3, "d": 4}
        result = exclude_fields(data, ["b", "d"])
        assert result == {"a": 1, "c": 3}

    def test_exclude_nonexistent(self):
        data = {"name": "Test"}
        result = exclude_fields(data, ["missing"])
        assert result == {"name": "Test"}

    def test_exclude_empty_list(self):
        data = {"name": "Test"}
        result = exclude_fields(data, [])
        assert result == data


class TestResolveFieldsPreset:
    def test_minimal_preset(self):
        fields = resolve_fields_preset("minimal")
        assert fields is not None
        assert "name" in fields

    def test_contact_preset(self):
        fields = resolve_fields_preset("contact")
        assert fields is not None
        assert "email" in fields

    def test_unknown_preset(self):
        fields = resolve_fields_preset("nonexistent")
        assert fields is None
