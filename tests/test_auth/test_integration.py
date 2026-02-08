"""Tests for OAuth integration with main.py get_api_key()."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from anysite.auth.token_store import TokenData, TokenStore


def _make_token(*, hdw: str = "oauth-hdw-token") -> TokenData:
    return TokenData(
        access_token="jwt",
        hdw_access_token=hdw,
        token_type="Bearer",
        expires_at=datetime.now(UTC) + timedelta(days=29),
        client_id="test-client",
        auth_server_url="https://api.anysite.io",
    )


class TestGetApiKeyPriority:
    def test_cli_flag_wins(self) -> None:
        from anysite.main import get_api_key, state

        original = state["api_key"]
        try:
            state["api_key"] = "cli-key"
            assert get_api_key() == "cli-key"
        finally:
            state["api_key"] = original

    def test_env_var_over_oauth(self) -> None:
        from anysite.main import get_api_key, state

        original = state["api_key"]
        try:
            state["api_key"] = None
            with patch.dict("os.environ", {"ANYSITE_API_KEY": "env-key"}):
                assert get_api_key() == "env-key"
        finally:
            state["api_key"] = original

    def test_oauth_over_config(self, tmp_path: object) -> None:
        from anysite.main import get_api_key, state

        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        store.save(_make_token(hdw="oauth-token-value"))

        original = state["api_key"]
        try:
            state["api_key"] = None
            with (
                patch.dict("os.environ", {}, clear=False),
                patch("anysite.auth.get_oauth_token", return_value="oauth-token-value"),
            ):
                # Remove ANYSITE_API_KEY if present
                import os
                os.environ.pop("ANYSITE_API_KEY", None)
                result = get_api_key()
                assert result == "oauth-token-value"
        finally:
            state["api_key"] = original

    def test_falls_back_to_config(self, tmp_path: object) -> None:
        from anysite.main import get_api_key, state

        original = state["api_key"]
        try:
            state["api_key"] = None
            with (
                patch.dict("os.environ", {}, clear=False),
                patch("anysite.auth.get_oauth_token", return_value=None),
                patch("anysite.config.get_settings") as mock_settings,
            ):
                import os
                os.environ.pop("ANYSITE_API_KEY", None)
                mock_settings.return_value.api_key = "config-key"
                assert get_api_key() == "config-key"
        finally:
            state["api_key"] = original
