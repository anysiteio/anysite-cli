"""Database integration subsystem for storing API data in SQL databases."""

from typing import NoReturn


def check_db_deps(db_type: str | None = None) -> None:
    """Check that optional database dependencies are installed.

    Args:
        db_type: Specific database type to check ('postgres', 'mysql').
                 If None, only checks that the db module itself is usable.

    Raises:
        SystemExit: If required packages are not installed.
    """
    if db_type == "postgres":
        try:
            import psycopg  # noqa: F401
        except ImportError:
            _missing_deps_error(["psycopg"], extra="postgres")

    elif db_type == "mysql":
        try:
            import pymysql  # noqa: F401
        except ImportError:
            _missing_deps_error(["pymysql"], extra="mysql")


def _missing_deps_error(missing: list[str], extra: str = "db") -> NoReturn:
    import typer

    names = ", ".join(missing)
    typer.echo(
        f"Error: Missing required packages: {names}\n"
        f"Install with: pip install anysite-cli[{extra}]",
        err=True,
    )
    raise typer.Exit(1)
