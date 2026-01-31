"""Tests for SQL identifier sanitization."""

import pytest

from anysite.db.utils.sanitize import sanitize_identifier, sanitize_table_name


class TestSanitizeIdentifier:
    def test_simple_name(self):
        assert sanitize_identifier("users") == "users"

    def test_with_underscore(self):
        assert sanitize_identifier("user_name") == "user_name"

    def test_starts_with_underscore(self):
        assert sanitize_identifier("_private") == "_private"

    def test_starts_with_digit(self):
        assert sanitize_identifier("123abc") == "_123abc"

    def test_special_characters(self):
        assert sanitize_identifier("user-name") == "user_name"
        assert sanitize_identifier("user.name") == "user_name"
        assert sanitize_identifier("user@name") == "user_name"

    def test_spaces(self):
        assert sanitize_identifier("user name") == "user_name"

    def test_multiple_special_chars(self):
        result = sanitize_identifier("a--b..c")
        assert result == "a_b_c"

    def test_reserved_word(self):
        assert sanitize_identifier("select") == '"select"'
        assert sanitize_identifier("table") == '"table"'
        assert sanitize_identifier("from") == '"from"'
        assert sanitize_identifier("where") == '"where"'

    def test_reserved_word_case_insensitive(self):
        assert sanitize_identifier("SELECT") == '"SELECT"'
        assert sanitize_identifier("Table") == '"Table"'

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            sanitize_identifier("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            sanitize_identifier("   ")

    def test_strip_whitespace(self):
        assert sanitize_identifier("  name  ") == "name"

    def test_max_length(self):
        long_name = "a" * 100
        result = sanitize_identifier(long_name)
        assert len(result) <= 63

    def test_trailing_underscores_stripped(self):
        assert sanitize_identifier("name_") == "name"
        assert sanitize_identifier("name___") == "name"


class TestSanitizeTableName:
    def test_simple_table(self):
        assert sanitize_table_name("users") == "users"

    def test_schema_qualified(self):
        assert sanitize_table_name("public.users") == "public.users"

    def test_reserved_schema(self):
        assert sanitize_table_name("select.users") == '"select".users'

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            sanitize_table_name("")

    def test_special_chars(self):
        assert sanitize_table_name("my-table") == "my_table"
