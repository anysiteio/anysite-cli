"""Tests for streaming writer."""

import pytest

from anysite.output.formatters import OutputFormat
from anysite.streaming.writer import StreamingWriter


class TestStreamingWriter:
    def test_write_jsonl_to_file(self, tmp_path):
        output = tmp_path / "output.jsonl"
        writer = StreamingWriter(output=output, format=OutputFormat.JSONL)
        with writer:
            writer.write({"name": "Alice", "age": 30})
            writer.write({"name": "Bob", "age": 25})

        lines = output.read_text().strip().split("\n")
        assert len(lines) == 2
        assert writer.count == 2

    def test_write_jsonl_to_stdout(self, capsys):
        writer = StreamingWriter(output=None, format=OutputFormat.JSONL)
        with writer:
            writer.write({"name": "Test"})

        captured = capsys.readouterr()
        assert "Test" in captured.out

    def test_write_with_field_selection(self, tmp_path):
        output = tmp_path / "output.jsonl"
        writer = StreamingWriter(
            output=output,
            format=OutputFormat.JSONL,
            fields=["name"],
        )
        with writer:
            writer.write({"name": "Alice", "age": 30, "email": "a@b.com"})

        content = output.read_text().strip()
        assert "name" in content
        assert "email" not in content

    def test_write_with_exclude(self, tmp_path):
        output = tmp_path / "output.jsonl"
        writer = StreamingWriter(
            output=output,
            format=OutputFormat.JSONL,
            exclude=["age"],
        )
        with writer:
            writer.write({"name": "Alice", "age": 30})

        content = output.read_text().strip()
        assert "name" in content
        assert "age" not in content

    def test_append_mode(self, tmp_path):
        output = tmp_path / "output.jsonl"
        output.write_text('{"existing": true}\n')

        writer = StreamingWriter(
            output=output,
            format=OutputFormat.JSONL,
            append=True,
        )
        with writer:
            writer.write({"new": True})

        lines = output.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_csv_streaming(self, tmp_path):
        output = tmp_path / "output.csv"
        writer = StreamingWriter(output=output, format=OutputFormat.CSV)
        with writer:
            writer.write({"name": "Alice", "age": "30"})
            writer.write({"name": "Bob", "age": "25"})

        content = output.read_text()
        assert "name" in content  # header
        assert "Alice" in content
        assert "Bob" in content

    def test_count_tracking(self, tmp_path):
        output = tmp_path / "output.jsonl"
        writer = StreamingWriter(output=output, format=OutputFormat.JSONL)
        with writer:
            for i in range(5):
                writer.write({"i": i})
        assert writer.count == 5
