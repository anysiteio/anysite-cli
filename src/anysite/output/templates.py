"""Filename template resolution for batch output."""

from datetime import datetime
from typing import Any


class FilenameTemplate:
    """Resolve filename templates with variable substitution.

    Supported variables:
        {id}        - Record ID or input value
        {username}  - Username field from record
        {date}      - Current date (YYYY-MM-DD)
        {datetime}  - Current date and time (YYYY-MM-DD_HH-MM-SS)
        {timestamp} - Unix timestamp
        {index}     - Zero-padded index
    """

    def __init__(self, template: str, extension: str = ".json") -> None:
        """Initialize template.

        Args:
            template: Template string with {variable} placeholders
            extension: File extension to append
        """
        self.template = template
        self.extension = extension

    def resolve(
        self,
        record: dict[str, Any] | None = None,
        index: int = 0,
        input_value: str = "",
    ) -> str:
        """Resolve template variables to an actual filename.

        Args:
            record: Data record (for extracting fields)
            index: Item index in batch
            input_value: Original input value

        Returns:
            Resolved filename string with extension
        """
        now = datetime.now()
        record = record or {}

        variables = {
            "id": input_value or record.get("id", record.get("urn", str(index))),
            "username": record.get("username", record.get("user", input_value)),
            "date": now.strftime("%Y-%m-%d"),
            "datetime": now.strftime("%Y-%m-%d_%H-%M-%S"),
            "timestamp": str(int(now.timestamp())),
            "index": f"{index:04d}",
        }

        filename = self.template
        for key, value in variables.items():
            filename = filename.replace(f"{{{key}}}", str(value))

        # Sanitize filename
        filename = self._sanitize(filename)

        # Add extension if not present
        if not any(filename.endswith(ext) for ext in [".json", ".jsonl", ".csv"]):
            filename += self.extension

        return filename

    @staticmethod
    def _sanitize(filename: str) -> str:
        """Remove or replace unsafe characters from filename."""
        unsafe = '<>:"/\\|?*'
        for char in unsafe:
            filename = filename.replace(char, "_")
        return filename.strip(". ")
