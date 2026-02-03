"""Tests for config paths module."""

import os
from pathlib import Path
from unittest.mock import patch

from anysite.config.paths import (
    ensure_config_dir,
    get_config_dir,
    get_config_path,
    get_schema_cache_path,
)


class TestGetConfigDir:
    """Tests for get_config_dir()."""

    def test_default_unix(self):
        """Returns ~/.anysite on Unix when no env var set."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove ANYSITE_CONFIG_DIR if present
            os.environ.pop("ANYSITE_CONFIG_DIR", None)
            result = get_config_dir()
            assert result == Path.home() / ".anysite"

    def test_custom_dir_from_env(self, tmp_path: Path):
        """Returns custom path when ANYSITE_CONFIG_DIR is set."""
        custom_dir = tmp_path / "custom_anysite"
        with patch.dict(os.environ, {"ANYSITE_CONFIG_DIR": str(custom_dir)}):
            result = get_config_dir()
            assert result == custom_dir

    def test_custom_dir_propagates_to_config_path(self, tmp_path: Path):
        """ANYSITE_CONFIG_DIR affects get_config_path()."""
        custom_dir = tmp_path / "user_123"
        with patch.dict(os.environ, {"ANYSITE_CONFIG_DIR": str(custom_dir)}):
            assert get_config_path() == custom_dir / "config.yaml"

    def test_custom_dir_propagates_to_schema_cache(self, tmp_path: Path):
        """ANYSITE_CONFIG_DIR affects get_schema_cache_path()."""
        custom_dir = tmp_path / "user_456"
        with patch.dict(os.environ, {"ANYSITE_CONFIG_DIR": str(custom_dir)}):
            assert get_schema_cache_path() == custom_dir / "schema.json"

    def test_ensure_config_dir_creates_custom_dir(self, tmp_path: Path):
        """ensure_config_dir() creates custom directory."""
        custom_dir = tmp_path / "new_user" / ".anysite"
        assert not custom_dir.exists()

        with patch.dict(os.environ, {"ANYSITE_CONFIG_DIR": str(custom_dir)}):
            result = ensure_config_dir()
            assert result == custom_dir
            assert custom_dir.exists()
            assert custom_dir.is_dir()

    def test_empty_env_var_uses_default(self):
        """Empty ANYSITE_CONFIG_DIR falls back to default."""
        with patch.dict(os.environ, {"ANYSITE_CONFIG_DIR": ""}):
            result = get_config_dir()
            # Empty string is falsy, so should use default
            assert result == Path.home() / ".anysite"
