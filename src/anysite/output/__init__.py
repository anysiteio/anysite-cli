"""Output formatting module."""

from anysite.output.console import console, error_console
from anysite.output.formatters import OutputFormat, format_output

__all__ = [
    "OutputFormat",
    "format_output",
    "console",
    "error_console",
]
