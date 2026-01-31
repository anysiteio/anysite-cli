"""Dataset subsystem for multi-source data collection and analysis."""

from typing import NoReturn


def check_data_deps() -> None:
    """Check that optional data dependencies are installed.

    Raises:
        SystemExit: If duckdb or pyarrow are not installed.
    """
    missing: list[str] = []

    try:
        import duckdb  # noqa: F401
    except ImportError:
        missing.append("duckdb")

    try:
        import pyarrow  # noqa: F401
    except ImportError:
        missing.append("pyarrow")

    if missing:
        _missing_deps_error(missing)


def _missing_deps_error(missing: list[str]) -> NoReturn:
    import typer

    names = ", ".join(missing)
    typer.echo(
        f"Error: Missing required packages: {names}\n"
        f"Install with: pip install anysite-cli[data]",
        err=True,
    )
    raise typer.Exit(1)
