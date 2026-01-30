"""Tests for batch input parsing."""

import pytest

from anysite.batch.input import InputFormat, InputParser


class TestDetectFormat:
    def test_text_file(self, tmp_path):
        f = tmp_path / "input.txt"
        f.write_text("line1\nline2\n")
        assert InputParser.detect_format(f) == InputFormat.TEXT

    def test_jsonl_file(self, tmp_path):
        f = tmp_path / "input.jsonl"
        f.write_text('{"user": "a"}\n{"user": "b"}\n')
        assert InputParser.detect_format(f) == InputFormat.JSONL

    def test_ndjson_file(self, tmp_path):
        f = tmp_path / "input.ndjson"
        f.write_text('{"user": "a"}\n')
        assert InputParser.detect_format(f) == InputFormat.JSONL

    def test_csv_file(self, tmp_path):
        f = tmp_path / "input.csv"
        f.write_text("user,count\na,10\nb,20\n")
        assert InputParser.detect_format(f) == InputFormat.CSV


class TestParseText:
    def test_basic(self):
        result = InputParser.parse_text("line1\nline2\nline3")
        assert result == ["line1", "line2", "line3"]

    def test_strips_whitespace(self):
        result = InputParser.parse_text("  a  \n  b  \n")
        assert result == ["a", "b"]

    def test_skips_empty_lines(self):
        result = InputParser.parse_text("a\n\nb\n\n")
        assert result == ["a", "b"]


class TestParseJsonl:
    def test_basic(self):
        result = InputParser.parse_jsonl('{"user": "a"}\n{"user": "b"}')
        assert result == [{"user": "a"}, {"user": "b"}]

    def test_non_dict_wrapped(self):
        result = InputParser.parse_jsonl('"hello"\n"world"')
        assert result == [{"value": "hello"}, {"value": "world"}]

    def test_skips_empty_lines(self):
        result = InputParser.parse_jsonl('{"a": 1}\n\n{"b": 2}')
        assert len(result) == 2

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON on line"):
            InputParser.parse_jsonl("not json")


class TestParseCsv:
    def test_basic(self):
        result = InputParser.parse_csv("user,count\na,10\nb,20")
        assert len(result) == 2
        assert result[0]["user"] == "a"
        assert result[0]["count"] == "10"


class TestFromFile:
    def test_text_file(self, tmp_path):
        f = tmp_path / "input.txt"
        f.write_text("user1\nuser2\nuser3\n")
        result = InputParser.from_file(f)
        assert result == ["user1", "user2", "user3"]

    def test_jsonl_file(self, tmp_path):
        f = tmp_path / "input.jsonl"
        f.write_text('{"user": "a"}\n{"user": "b"}\n')
        result = InputParser.from_file(f)
        assert result == [{"user": "a"}, {"user": "b"}]

    def test_csv_file(self, tmp_path):
        f = tmp_path / "input.csv"
        f.write_text("user,count\na,10\nb,20\n")
        result = InputParser.from_file(f)
        assert len(result) == 2

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            InputParser.from_file(tmp_path / "missing.txt")

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        with pytest.raises(ValueError, match="empty"):
            InputParser.from_file(f)
