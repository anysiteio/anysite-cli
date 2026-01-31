"""Database connection configuration."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from pydantic import BaseModel, model_validator


class DatabaseType(str, Enum):
    """Supported database types."""

    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    DUCKDB = "duckdb"


class ConnectionConfig(BaseModel):
    """Configuration for a database connection."""

    name: str
    type: DatabaseType
    host: str | None = None
    port: int | None = None
    database: str | None = None
    user: str | None = None
    password_env: str | None = None
    url_env: str | None = None
    path: str | None = None
    ssl: bool = False
    options: dict[str, Any] = {}

    @model_validator(mode="after")
    def validate_config(self) -> ConnectionConfig:
        """Validate that required fields are present for the database type."""
        if self.type in (DatabaseType.SQLITE, DatabaseType.DUCKDB) and not self.path:
            raise ValueError(f"{self.type.value} requires 'path'")
        if self.type in (DatabaseType.POSTGRES, DatabaseType.MYSQL) and not self.url_env and not self.host:
            raise ValueError(f"{self.type.value} requires 'host' or 'url_env'")
        return self

    def get_password(self) -> str | None:
        """Resolve password from environment variable."""
        if self.password_env:
            value = os.environ.get(self.password_env)
            if value is None:
                raise ValueError(
                    f"Environment variable '{self.password_env}' is not set"
                )
            return value
        return None

    def get_url(self) -> str | None:
        """Resolve connection URL from environment variable."""
        if self.url_env:
            value = os.environ.get(self.url_env)
            if value is None:
                raise ValueError(
                    f"Environment variable '{self.url_env}' is not set"
                )
            return value
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization, omitting None values."""
        data: dict[str, Any] = {"type": self.type.value}
        for field in ("host", "port", "database", "user", "password_env", "url_env", "path"):
            value = getattr(self, field)
            if value is not None:
                data[field] = value
        if self.ssl:
            data["ssl"] = True
        if self.options:
            data["options"] = self.options
        return data

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> ConnectionConfig:
        """Create a ConnectionConfig from a dictionary."""
        return cls(name=name, **data)


class OnConflict(str, Enum):
    """Conflict resolution strategy for inserts."""

    ERROR = "error"
    IGNORE = "ignore"
    REPLACE = "replace"
    UPDATE = "update"
