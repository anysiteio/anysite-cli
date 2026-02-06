"""Rich console configuration."""

import sys

from rich.console import Console

# Main console — auto-disable Rich markup when stdout is not a terminal (piped).
# This ensures clean output for agents and scripts.
console = Console(force_terminal=sys.stdout.isatty())

# Error console for stderr
error_console = Console(stderr=True, style="bold red")


def print_error(message: str) -> None:
    """Print an error message to stderr.

    Args:
        message: Error message to print
    """
    error_console.print(f"[red]✗[/red] {message}")


def print_success(message: str) -> None:
    """Print a success message.

    Args:
        message: Success message to print
    """
    console.print(f"[green]✓[/green] {message}")


def print_warning(message: str) -> None:
    """Print a warning message.

    Args:
        message: Warning message to print
    """
    console.print(f"[yellow]![/yellow] {message}")


def print_info(message: str) -> None:
    """Print an info message.

    Args:
        message: Info message to print
    """
    console.print(f"[blue]ℹ[/blue] {message}")
