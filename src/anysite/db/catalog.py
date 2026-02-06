"""Catalog store — YAML persistence for database catalogs."""

from __future__ import annotations

from pathlib import Path

import yaml

from anysite.config.paths import ensure_config_dir, get_config_dir
from anysite.db.discovery import DatabaseCatalog


def _get_catalogs_dir() -> Path:
    return get_config_dir() / "catalogs"


def _ensure_catalogs_dir() -> Path:
    ensure_config_dir()
    d = _get_catalogs_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


class CatalogStore:
    """Persists DatabaseCatalog objects as YAML files."""

    def __init__(self, catalogs_dir: Path | None = None) -> None:
        self._dir = catalogs_dir or _get_catalogs_dir()

    def save(self, catalog: DatabaseCatalog) -> Path:
        """Save a catalog to YAML.

        Returns:
            Path to the saved YAML file.
        """
        if self._dir == _get_catalogs_dir():
            _ensure_catalogs_dir()
        else:
            self._dir.mkdir(parents=True, exist_ok=True)

        path = self._dir / f"{catalog.connection_name}.yaml"
        data = catalog.to_dict()
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return path

    def load(self, connection_name: str) -> DatabaseCatalog | None:
        """Load a catalog by connection name.

        Returns:
            DatabaseCatalog or None if not found.
        """
        path = self._dir / f"{connection_name}.yaml"
        if not path.exists():
            return None
        with open(path) as f:
            data = yaml.safe_load(f)
        if not data:
            return None
        return DatabaseCatalog.from_dict(data)

    def list(self) -> list[dict[str, str]]:
        """List all saved catalogs.

        Returns:
            List of dicts with name, database_type, discovered_at, table_count.
        """
        if not self._dir.exists():
            return []

        results: list[dict[str, str]] = []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
                results.append(
                    {
                        "name": data.get("connection_name", path.stem),
                        "database_type": data.get("database_type", "unknown"),
                        "discovered_at": data.get("discovered_at", ""),
                        "table_count": str(len(data.get("tables", []))),
                        "llm_enriched": str(data.get("llm_enriched", False)),
                    }
                )
            except Exception:
                continue
        return results

    def remove(self, connection_name: str) -> bool:
        """Remove a catalog by connection name.

        Returns:
            True if removed, False if not found.
        """
        path = self._dir / f"{connection_name}.yaml"
        if path.exists():
            path.unlink()
            return True
        return False
