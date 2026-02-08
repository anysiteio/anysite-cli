"""Tests for OAuth CLI commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from anysite.auth.cli import app
from anysite.auth.token_store import TokenData, TokenStore

runner = CliRunner()


def _make_token(
    *,
    expired: bool = False,
    client_id: str = "test-client",
) -> TokenData:
    if expired:
        expires_at = datetime.now(UTC) - timedelta(hours=1)
    else:
        expires_at = datetime.now(UTC) + timedelta(days=29)
    return TokenData(
        access_token="jwt-token",
        hdw_access_token="hdw-token",
        token_type="Bearer",
        expires_at=expires_at,
        client_id=client_id,
        auth_server_url="https://api.anysite.io",
    )


class TestLoginCommand:
    def test_login_help(self) -> None:
        result = runner.invoke(app, ["login", "--help"])
        assert result.exit_code == 0
        assert "OAuth2" in result.output


class TestLogoutCommand:
    def test_logout_no_token(self, tmp_path: object) -> None:
        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        with patch("anysite.auth.cli._get_token_store", return_value=store):
            result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0
        assert "Not logged in" in result.output

    def test_logout_with_force(self, tmp_path: object) -> None:
        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        store.save(_make_token())
        with patch("anysite.auth.cli._get_token_store", return_value=store):
            result = runner.invoke(app, ["logout", "--force"])
        assert result.exit_code == 0
        assert "Logged out" in result.output
        assert store.load() is None


class TestStatusCommand:
    def test_status_no_auth(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        monkeypatch.delenv("ANYSITE_API_KEY", raising=False)
        with (
            patch("anysite.auth.cli._get_token_store", return_value=store),
            patch("anysite.config.get_settings") as mock_settings,
        ):
            mock_settings.return_value.api_key = None
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.output

    def test_status_with_oauth(self, tmp_path: object) -> None:
        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        store.save(_make_token())
        with patch("anysite.auth.cli._get_token_store", return_value=store):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "OAuth2" in result.output
        assert "Active" in result.output

    def test_status_with_expired_oauth(self, tmp_path: object) -> None:
        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        store.save(_make_token(expired=True))
        with patch("anysite.auth.cli._get_token_store", return_value=store):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Expired" in result.output

    def test_status_json(self, tmp_path: object) -> None:
        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        store.save(_make_token())
        with patch("anysite.auth.cli._get_token_store", return_value=store):
            result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert data["method"] == "oauth2"
        assert data["status"] == "active"
