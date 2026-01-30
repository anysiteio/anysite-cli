"""Application settings using Pydantic Settings."""

from functools import lru_cache
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from anysite.config.paths import get_config_path


def load_yaml_config() -> dict[str, Any]:
    """Load configuration from YAML file."""
    config_path = get_config_path()
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


class Settings(BaseSettings):
    """Application settings.

    Priority (highest to lowest):
    1. CLI arguments (handled separately)
    2. Environment variables (ANYSITE_*)
    3. Config file (~/.anysite/config.yaml)
    4. Default values
    """

    model_config = SettingsConfigDict(
        env_prefix="ANYSITE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API settings
    api_key: str | None = Field(
        default=None,
        description="Anysite API key",
    )
    base_url: str = Field(
        default="https://api.anysite.io",
        description="Anysite API base URL",
    )
    timeout: int = Field(
        default=300,
        ge=20,
        le=1500,
        description="API request timeout in seconds",
    )

    # CLI defaults
    default_format: str = Field(
        default="json",
        description="Default output format (json, jsonl, csv, table)",
    )
    default_count: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Default count for search results",
    )

    # Phase 2: Batch defaults
    default_parallel: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Default parallel concurrency for batch operations",
    )
    default_rate_limit: str | None = Field(
        default=None,
        description="Default rate limit (e.g., '10/s', '60/m')",
    )
    auto_stream_threshold: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Auto-enable streaming when count exceeds this threshold",
    )

    # Debug
    debug: bool = Field(
        default=False,
        description="Enable debug mode",
    )

    def __init__(self, **kwargs: Any) -> None:
        # Load YAML config first
        yaml_config = load_yaml_config()

        # Handle nested 'defaults' key from YAML
        if "defaults" in yaml_config:
            defaults = yaml_config.pop("defaults")
            if "format" in defaults:
                yaml_config.setdefault("default_format", defaults["format"])
            if "count" in defaults:
                yaml_config.setdefault("default_count", defaults["count"])
            if "timeout" in defaults:
                yaml_config.setdefault("timeout", defaults["timeout"])
            if "parallel" in defaults:
                yaml_config.setdefault("default_parallel", defaults["parallel"])
            if "rate_limit" in defaults:
                yaml_config.setdefault("default_rate_limit", defaults["rate_limit"])
            if "auto_stream_threshold" in defaults:
                yaml_config.setdefault("auto_stream_threshold", defaults["auto_stream_threshold"])

        # Merge: kwargs (CLI) > env > yaml > defaults
        merged = {**yaml_config, **kwargs}
        super().__init__(**merged)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def save_config(key: str, value: Any) -> None:
    """Save a configuration value to the YAML config file.

    Args:
        key: Configuration key (e.g., 'api_key', 'defaults.format')
        value: Value to save
    """
    from anysite.config.paths import ensure_config_dir, get_config_path

    ensure_config_dir()
    config_path = get_config_path()

    # Load existing config
    config: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    # Handle nested keys (e.g., 'defaults.format')
    if "." in key:
        parts = key.split(".")
        current = config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    else:
        config[key] = value

    # Save config
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    # Clear settings cache
    get_settings.cache_clear()


def get_config_value(key: str) -> Any:
    """Get a configuration value from the YAML config file.

    Args:
        key: Configuration key (e.g., 'api_key', 'defaults.format')

    Returns:
        The configuration value or None if not found.
    """
    config = load_yaml_config()

    # Handle nested keys
    if "." in key:
        parts = key.split(".")
        current: Any = config
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    return config.get(key)


def list_config() -> dict[str, Any]:
    """List all configuration values."""
    return load_yaml_config()
