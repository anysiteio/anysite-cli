"""Connection manager for database connections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from anysite.config.paths import ensure_config_dir, get_config_dir
from anysite.db.adapters.base import DatabaseAdapter
from anysite.db.config import ConnectionConfig, DatabaseType


def get_connections_path() -> Path:
    """Get the path to the connections YAML file."""
    return get_config_dir() / "connections.yaml"


class ConnectionManager:
    """Manages named database connections stored in YAML."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_connections_path()
        self._connections: dict[str, ConnectionConfig] | None = None

    def _load(self) -> dict[str, ConnectionConfig]:
        """Load connections from YAML file."""
        if self._connections is not None:
            return self._connections

        connections: dict[str, ConnectionConfig] = {}
        if self.path.exists():
            with open(self.path) as f:
                data = yaml.safe_load(f) or {}
            raw = data.get("connections", {})
            for name, config_data in raw.items():
                connections[name] = ConnectionConfig.from_dict(name, config_data)

        self._connections = connections
        return connections

    def _save(self) -> None:
        """Save connections to YAML file."""
        connections = self._load()
        data: dict[str, Any] = {
            "connections": {
                name: config.to_dict()
                for name, config in connections.items()
            }
        }
        ensure_config_dir()
        with open(self.path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def add(self, config: ConnectionConfig) -> None:
        """Add or update a connection.

        Args:
            config: Connection configuration.
        """
        connections = self._load()
        connections[config.name] = config
        self._save()

    def remove(self, name: str) -> bool:
        """Remove a connection by name.

        Args:
            name: Connection name.

        Returns:
            True if the connection was removed, False if not found.
        """
        connections = self._load()
        if name not in connections:
            return False
        del connections[name]
        self._save()
        return True

    def get(self, name: str) -> ConnectionConfig | None:
        """Get a connection config by name.

        Args:
            name: Connection name.

        Returns:
            ConnectionConfig or None if not found.
        """
        connections = self._load()
        return connections.get(name)

    def list(self) -> list[ConnectionConfig]:
        """List all connections.

        Returns:
            List of connection configs.
        """
        connections = self._load()
        return list(connections.values())

    def test(self, name: str) -> dict[str, str]:
        """Test a connection by connecting and getting server info.

        Args:
            name: Connection name.

        Returns:
            Server info dictionary.

        Raises:
            ValueError: If connection not found.
            Exception: If connection fails.
        """
        config = self.get(name)
        if config is None:
            raise ValueError(f"Connection '{name}' not found")

        adapter = self.get_adapter(config)
        with adapter:
            return adapter.get_server_info()

    def get_adapter(self, config: ConnectionConfig) -> DatabaseAdapter:
        """Get a database adapter for the given config.

        Args:
            config: Connection configuration.

        Returns:
            Appropriate DatabaseAdapter instance.

        Raises:
            ValueError: If database type is not supported.
        """
        if config.type == DatabaseType.SQLITE:
            from anysite.db.adapters.sqlite import SQLiteAdapter

            return SQLiteAdapter(config)

        elif config.type == DatabaseType.POSTGRES:
            from anysite.db import check_db_deps
            from anysite.db.adapters.postgres import PostgresAdapter

            check_db_deps("postgres")
            return PostgresAdapter(config)

        else:
            raise ValueError(f"Unsupported database type: {config.type.value}")

    def get_adapter_by_name(self, name: str) -> DatabaseAdapter:
        """Get a database adapter by connection name.

        Args:
            name: Connection name.

        Returns:
            Appropriate DatabaseAdapter instance.

        Raises:
            ValueError: If connection not found or type unsupported.
        """
        config = self.get(name)
        if config is None:
            raise ValueError(f"Connection '{name}' not found")
        return self.get_adapter(config)
