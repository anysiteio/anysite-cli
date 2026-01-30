"""Configuration module."""

from anysite.config.paths import get_config_dir, get_config_path
from anysite.config.settings import Settings, get_settings

__all__ = [
    "Settings",
    "get_settings",
    "get_config_dir",
    "get_config_path",
]
