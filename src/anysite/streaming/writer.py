"""Streaming record writer for outputting records one at a time."""

import sys
from pathlib import Path
from typing import IO, Any

import orjson

from anysite.output.formatters import OutputFormat
from anysite.utils.fields import exclude_fields, filter_fields


class StreamingWriter:
    """Write records one at a time to stdout or a file.

    Supports JSONL (primary) and CSV streaming output.
    """

    def __init__(
        self,
        output: Path | None = None,
        format: OutputFormat = OutputFormat.JSONL,
        fields: list[str] | None = None,
        exclude: list[str] | None = None,
        compact: bool = False,
        append: bool = False,
    ) -> None:
        """Initialize streaming writer.

        Args:
            output: Output file path (None = stdout)
            format: Output format (JSONL or CSV)
            fields: Fields to include
            exclude: Fields to exclude
            compact: Compact JSON output
            append: Append to existing file
        """
        self.output = output
        self.format = format
        self.fields = fields
        self.exclude = exclude
        self.compact = compact
        self.append = append
        self._file: IO[str] | None = None
        self._csv_headers_written = False
        self._count = 0

    def _get_writer(self) -> IO[str]:
        """Get or create the output writer."""
        if self._file is not None:
            return self._file

        if self.output:
            mode = "a" if self.append else "w"
            self._file = open(self.output, mode, encoding="utf-8")  # noqa: SIM115
            return self._file
        else:
            return sys.stdout

    def _process_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Apply field filtering to a record."""
        if self.fields:
            record = filter_fields(record, self.fields)
        if self.exclude:
            record = exclude_fields(record, self.exclude)
        return record

    def write(self, record: dict[str, Any]) -> None:
        """Write a single record.

        Args:
            record: Dictionary to write
        """
        record = self._process_record(record)
        writer = self._get_writer()

        if self.format == OutputFormat.JSONL:
            line = orjson.dumps(record).decode("utf-8")
            writer.write(line + "\n")
            writer.flush()

        elif self.format == OutputFormat.CSV:
            import csv
            import io

            if not self._csv_headers_written:
                # Flatten and write header
                from anysite.output.formatters import flatten_for_csv
                flat = flatten_for_csv(record)
                self._csv_fieldnames = list(flat.keys())
                output = io.StringIO()
                csv_writer = csv.DictWriter(output, fieldnames=self._csv_fieldnames, extrasaction="ignore")
                csv_writer.writeheader()
                csv_writer.writerow(flat)
                writer.write(output.getvalue())
                self._csv_headers_written = True
            else:
                from anysite.output.formatters import flatten_for_csv
                flat = flatten_for_csv(record)
                output = io.StringIO()
                csv_writer = csv.DictWriter(output, fieldnames=self._csv_fieldnames, extrasaction="ignore")
                csv_writer.writerow(flat)
                writer.write(output.getvalue())

            writer.flush()

        else:
            # Default to JSONL for streaming
            line = orjson.dumps(record).decode("utf-8")
            writer.write(line + "\n")
            writer.flush()

        self._count += 1

    def close(self) -> None:
        """Close the output file if opened."""
        if self._file is not None:
            self._file.close()
            self._file = None

    @property
    def count(self) -> int:
        """Number of records written."""
        return self._count

    def __enter__(self) -> "StreamingWriter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
