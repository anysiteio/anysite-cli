"""Tests for filename templates."""

from anysite.output.templates import FilenameTemplate


class TestFilenameTemplate:
    def test_id_from_input_value(self):
        template = FilenameTemplate("{id}", extension=".json")
        result = template.resolve(
            record={"id": "12345"},
            index=0,
            input_value="test",
        )
        # input_value takes priority for {id}
        assert result == "test.json"

    def test_id_from_record_fallback(self):
        template = FilenameTemplate("{id}", extension=".json")
        result = template.resolve(
            record={"id": "12345"},
            index=0,
            input_value="",
        )
        assert result == "12345.json"

    def test_username_variable(self):
        template = FilenameTemplate("{username}", extension=".json")
        result = template.resolve(
            record={"username": "testuser"},
            index=0,
            input_value="testuser",
        )
        assert result == "testuser.json"

    def test_index_variable(self):
        template = FilenameTemplate("{index}", extension=".json")
        result = template.resolve(
            record={},
            index=5,
            input_value="test",
        )
        assert result == "0005.json"

    def test_combined_variables(self):
        template = FilenameTemplate("{username}_{index}", extension=".json")
        result = template.resolve(
            record={"username": "alice"},
            index=3,
            input_value="alice",
        )
        assert result == "alice_0003.json"

    def test_missing_id_uses_index(self):
        template = FilenameTemplate("{id}", extension=".json")
        result = template.resolve(
            record={},
            index=7,
            input_value="",
        )
        assert result == "7.json"

    def test_sanitizes_filename(self):
        template = FilenameTemplate("{id}", extension=".json")
        result = template.resolve(
            record={},
            index=0,
            input_value="test/user:name",
        )
        assert "/" not in result
        assert ":" not in result
