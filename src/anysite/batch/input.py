"""Batch input parser for reading inputs from files and stdin."""

import csv
import io
import sys
from enum import Enum
from pathlib import Path
from typing import Any

import orjson


class InputFormat(str, Enum):
    """Supported input file formats."""

    TEXT = "text"
    JSONL = "jsonl"
    CSV = "csv"


class InputParser:
    """Parse batch inputs from various sources."""

    @staticmethod
    def from_file(path: Path) -> "list[str | dict[str, Any]]":
        """Load inputs from a file, auto-detecting format.

        Args:
            path: Path to input file

        Returns:
            List of inputs (strings for text, dicts for JSONL/CSV)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file is empty or format is unsupported
        """
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Input file is empty: {path}")

        fmt = InputParser.detect_format(path)

        results: list[str | dict[str, Any]]
        if fmt == InputFormat.JSONL:
            results = InputParser.parse_jsonl(content)  # type: ignore[assignment]
        elif fmt == InputFormat.CSV:
            results = InputParser.parse_csv(content)  # type: ignore[assignment]
        else:
            results = InputParser.parse_text(content)  # type: ignore[assignment]
        return results

    @staticmethod
    def from_stdin() -> "list[str | dict[str, Any]]":
        """Read inputs from stdin.

        Returns:
            List of inputs (strings, one per line)

        Raises:
            ValueError: If stdin is empty or is a TTY
        """
        if sys.stdin.isatty():
            raise ValueError(
                "No input detected on stdin. "
                "Pipe data or use --from-file instead."
            )

        content = sys.stdin.read().strip()
        if not content:
            raise ValueError("No input received from stdin.")

        # Try to detect format
        first_line = content.split("\n")[0].strip()
        if first_line.startswith("{"):
            return InputParser.parse_jsonl(content)  # type: ignore[return-value]
        return InputParser.parse_text(content)  # type: ignore[return-value]

    @staticmethod
    def detect_format(path: Path) -> InputFormat:
        """Detect input file format from extension.

        Args:
            path: Path to input file

        Returns:
            Detected InputFormat
        """
        suffix = path.suffix.lower()

        if suffix in (".jsonl", ".ndjson"):
            return InputFormat.JSONL
        elif suffix == ".csv":
            return InputFormat.CSV
        elif suffix in (".json",):
            # Check if it's actually JSONL (one JSON per line)
            content = path.read_text(encoding="utf-8").strip()
            lines = content.split("\n")
            if len(lines) > 1 and lines[0].strip().startswith("{"):
                return InputFormat.JSONL
            return InputFormat.TEXT
        else:
            return InputFormat.TEXT

    @staticmethod
    def parse_text(content: str) -> list[str]:
        """Parse plain text input (one value per line).

        Args:
            content: Raw text content

        Returns:
            List of non-empty stripped lines
        """
        lines = content.strip().split("\n")
        return [line.strip() for line in lines if line.strip()]

    @staticmethod
    def parse_jsonl(content: str) -> list[dict[str, Any]]:
        """Parse JSON Lines input.

        Args:
            content: JSONL content

        Returns:
            List of parsed dictionaries

        Raises:
            ValueError: If a line contains invalid JSON
        """
        results: list[dict[str, Any]] = []
        for i, line in enumerate(content.strip().split("\n"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = orjson.loads(line)
                if isinstance(parsed, dict):
                    results.append(parsed)
                else:
                    results.append({"value": parsed})
            except orjson.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON on line {i}: {e}") from e
        return results

    @staticmethod
    def parse_csv(content: str) -> list[dict[str, Any]]:
        """Parse CSV input with headers.

        Args:
            content: CSV content with header row

        Returns:
            List of dictionaries (one per row)
        """
        reader = csv.DictReader(io.StringIO(content))
        return [dict(row) for row in reader]
