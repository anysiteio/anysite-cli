"""Abstract base class for database adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from anysite.db.config import OnConflict


class DatabaseAdapter(ABC):
    """Abstract base class for all database adapters.

    Adapters are synchronous. Use as a context manager for
    automatic connect/disconnect:

        with SQLiteAdapter(config) as db:
            db.execute("CREATE TABLE ...")
    """

    @abstractmethod
    def connect(self) -> None:
        """Open a connection to the database."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the database connection."""

    @abstractmethod
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Execute a SQL statement.

        Args:
            sql: SQL statement with parameter placeholders.
            params: Parameter values for the statement.
        """

    @abstractmethod
    def fetch_one(self, sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        """Execute a query and return the first row.

        Args:
            sql: SQL query with parameter placeholders.
            params: Parameter values for the query.

        Returns:
            First row as a dictionary, or None if no results.
        """

    @abstractmethod
    def fetch_all(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        """Execute a query and return all rows.

        Args:
            sql: SQL query with parameter placeholders.
            params: Parameter values for the query.

        Returns:
            List of rows as dictionaries.
        """

    @abstractmethod
    def insert_batch(
        self,
        table: str,
        rows: list[dict[str, Any]],
        on_conflict: OnConflict = OnConflict.ERROR,
        conflict_columns: list[str] | None = None,
    ) -> int:
        """Insert multiple rows into a table.

        Args:
            table: Table name.
            rows: List of row dictionaries.
            on_conflict: Conflict resolution strategy.
            conflict_columns: Columns that define uniqueness for upsert.

        Returns:
            Number of rows inserted/affected.
        """

    @abstractmethod
    def table_exists(self, table: str) -> bool:
        """Check if a table exists.

        Args:
            table: Table name.

        Returns:
            True if the table exists.
        """

    @abstractmethod
    def get_table_schema(self, table: str) -> list[dict[str, str]]:
        """Get the schema of a table.

        Args:
            table: Table name.

        Returns:
            List of column info dicts with 'name', 'type', 'nullable', 'primary_key' keys.
        """

    @abstractmethod
    def create_table(self, table: str, columns: dict[str, str], primary_key: str | None = None) -> None:
        """Create a table.

        Args:
            table: Table name.
            columns: Mapping of column name to SQL type.
            primary_key: Optional column name to use as primary key.
        """

    @abstractmethod
    def get_server_info(self) -> dict[str, str]:
        """Get database server information.

        Returns:
            Dictionary with server info (version, type, etc.).
        """

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Context manager for transactions.

        Usage:
            with adapter.transaction():
                adapter.execute("INSERT ...")
                adapter.execute("UPDATE ...")
        """
        self._begin_transaction()
        try:
            yield
            self._commit_transaction()
        except Exception:
            self._rollback_transaction()
            raise

    @abstractmethod
    def _begin_transaction(self) -> None:
        """Begin a transaction."""

    @abstractmethod
    def _commit_transaction(self) -> None:
        """Commit the current transaction."""

    @abstractmethod
    def _rollback_transaction(self) -> None:
        """Roll back the current transaction."""

    def __enter__(self) -> DatabaseAdapter:
        self.connect()
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
        self.disconnect()
