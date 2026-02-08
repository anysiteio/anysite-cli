"""Configuration file paths."""

import os
from pathlib import Path


def get_config_dir() -> Path:
    """Get the configuration directory path.

    Returns:
        Path from ANYSITE_CONFIG_DIR env var if set,
        otherwise ~/.anysite/ on Unix or %APPDATA%/anysite/ on Windows.
    """
    # Allow override via environment variable (useful for multi-tenant setups)
    if custom_dir := os.environ.get("ANYSITE_CONFIG_DIR"):
        return Path(custom_dir)

    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        return base / "anysite"
    else:  # Unix-like (Linux, macOS)
        return Path.home() / ".anysite"


def get_config_path() -> Path:
    """Get the configuration file path.

    Returns:
        Path to config.yaml in the config directory.
    """
    return get_config_dir() / "config.yaml"


def get_schema_cache_path() -> Path:
    """Get the schema cache file path.

    Returns:
        Path to schema.json in the config directory.
    """
    return get_config_dir() / "schema.json"


def get_auth_token_path() -> Path:
    """Get the OAuth token file path.

    Returns:
        Path to auth.json in the config directory.
    """
    return get_config_dir() / "auth.json"


def ensure_config_dir() -> Path:
    """Ensure the configuration directory exists.

    Returns:
        Path to the config directory.
    """
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir
