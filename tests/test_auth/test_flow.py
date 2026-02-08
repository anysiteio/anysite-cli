"""Tests for OAuth2 PKCE flow."""

from __future__ import annotations

import base64
import hashlib
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from anysite.auth.errors import OAuthFlowError, OAuthTokenError
from anysite.auth.flow import (
    build_authorization_url,
    exchange_code_for_token,
    extract_hdw_token,
    generate_pkce_pair,
    run_oauth_flow,
)
from anysite.auth.server import CallbackResult
from anysite.auth.token_store import TokenStore


class TestGeneratePkcePair:
    def test_verifier_length(self) -> None:
        verifier, _ = generate_pkce_pair()
        assert 43 <= len(verifier) <= 128

    def test_challenge_is_sha256_of_verifier(self) -> None:
        verifier, challenge = generate_pkce_pair()
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        assert challenge == expected_challenge

    def test_unique_pairs(self) -> None:
        pair1 = generate_pkce_pair()
        pair2 = generate_pkce_pair()
        assert pair1[0] != pair2[0]


class TestBuildAuthorizationUrl:
    def test_url_contains_all_params(self) -> None:
        url = build_authorization_url(
            "https://api.anysite.io",
            "client-123",
            "http://127.0.0.1:8585/callback",
            "state-abc",
            "challenge-xyz",
        )
        assert "client_id=client-123" in url
        assert "redirect_uri=" in url
        assert "state=state-abc" in url
        assert "code_challenge=challenge-xyz" in url
        assert "code_challenge_method=S256" in url
        assert "response_type=code" in url
        assert url.startswith("https://api.anysite.io/oauth/authorize?")


class TestExtractHdwToken:
    def _make_jwt(self, payload: dict) -> str:
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        signature = base64.urlsafe_b64encode(b"fake-sig").rstrip(b"=").decode()
        return f"{header}.{body}.{signature}"

    def test_extract_valid(self) -> None:
        jwt_token = self._make_jwt({"hdw_access_token": "the-api-token", "id": "user-1"})
        assert extract_hdw_token(jwt_token) == "the-api-token"

    def test_extract_missing_field(self) -> None:
        jwt_token = self._make_jwt({"id": "user-1"})
        with pytest.raises(OAuthTokenError, match="Missing hdw_access_token"):
            extract_hdw_token(jwt_token)

    def test_extract_invalid_jwt(self) -> None:
        with pytest.raises(OAuthTokenError):
            extract_hdw_token("not-a-jwt")


class TestExchangeCodeForToken:
    @respx.mock
    async def test_success(self) -> None:
        respx.post("https://api.anysite.io/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "jwt-token",
                    "token_type": "Bearer",
                    "expires_in": 2592000,
                },
            )
        )

        result = await exchange_code_for_token(
            "https://api.anysite.io",
            "code-123",
            "client-456",
            "http://127.0.0.1:8585/callback",
            "verifier-789",
        )
        assert result["access_token"] == "jwt-token"

    @respx.mock
    async def test_failure(self) -> None:
        respx.post("https://api.anysite.io/oauth/token").mock(
            return_value=httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "Invalid code"},
            )
        )

        with pytest.raises(OAuthTokenError, match="400"):
            await exchange_code_for_token(
                "https://api.anysite.io",
                "bad-code",
                "client-456",
                "http://127.0.0.1:8585/callback",
                "verifier-789",
            )


class TestRunOAuthFlow:
    def _make_jwt(self, payload: dict) -> str:
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        signature = base64.urlsafe_b64encode(b"fake-sig").rstrip(b"=").decode()
        return f"{header}.{body}.{signature}"

    async def test_full_flow_success(self, tmp_path: object) -> None:
        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        jwt_token = self._make_jwt({"hdw_access_token": "api-key-from-oauth", "id": "u1"})

        fixed_state = "fixed-state-value"
        mock_callback = CallbackResult(code="auth-code-123", state=fixed_state)

        with (
            patch("anysite.auth.flow.register_client", new_callable=AsyncMock) as mock_reg,
            patch("anysite.auth.flow.CallbackServer") as mock_server_cls,
            patch("anysite.auth.flow.exchange_code_for_token", new_callable=AsyncMock) as mock_exchange,
            patch("anysite.auth.flow.webbrowser") as mock_browser,
            patch("anysite.auth.flow.secrets.token_urlsafe", return_value=fixed_state),
        ):
            mock_reg.return_value.client_id = "mcp-client-xyz"

            mock_server = mock_server_cls.return_value
            mock_server.redirect_uri = "http://127.0.0.1:9999/callback"
            mock_server.wait_for_callback = AsyncMock(return_value=mock_callback)
            mock_server.stop = lambda: None

            mock_exchange.return_value = {
                "access_token": jwt_token,
                "token_type": "Bearer",
                "expires_in": 2592000,
            }

            token_data = await run_oauth_flow(
                auth_server_url="https://api.anysite.io",
                token_store=store,
            )

        assert token_data.hdw_access_token == "api-key-from-oauth"
        assert token_data.client_id == "mcp-client-xyz"
        mock_browser.open.assert_called_once()

        # Verify token was saved
        loaded = store.load()
        assert loaded is not None
        assert loaded.hdw_access_token == "api-key-from-oauth"

    async def test_flow_uses_cached_client_id(self, tmp_path: object) -> None:
        store = TokenStore(path=tmp_path / "auth.json")  # type: ignore[operator]
        jwt_token = self._make_jwt({"hdw_access_token": "api-key", "id": "u1"})

        # Pre-save a token to cache client_id
        from datetime import UTC, datetime, timedelta

        from anysite.auth.token_store import TokenData

        old_token = TokenData(
            access_token="old",
            hdw_access_token="old-hdw",
            token_type="Bearer",
            expires_at=datetime.now(UTC) - timedelta(days=1),  # expired
            client_id="cached-client-id",
            auth_server_url="https://api.anysite.io",
        )
        store.save(old_token)

        fixed_state = "fixed-state"
        mock_callback = CallbackResult(code="code", state=fixed_state)

        with (
            patch("anysite.auth.flow.register_client", new_callable=AsyncMock) as mock_reg,
            patch("anysite.auth.flow.CallbackServer") as mock_server_cls,
            patch("anysite.auth.flow.exchange_code_for_token", new_callable=AsyncMock) as mock_exchange,
            patch("anysite.auth.flow.webbrowser"),
            patch("anysite.auth.flow.secrets.token_urlsafe", return_value=fixed_state),
        ):
            mock_server = mock_server_cls.return_value
            mock_server.redirect_uri = "http://127.0.0.1:9999/callback"
            mock_server.wait_for_callback = AsyncMock(return_value=mock_callback)
            mock_server.stop = lambda: None

            mock_exchange.return_value = {
                "access_token": jwt_token,
                "token_type": "Bearer",
                "expires_in": 2592000,
            }

            await run_oauth_flow(
                auth_server_url="https://api.anysite.io",
                token_store=store,
            )

        # Registration should NOT have been called — cached client_id used
        mock_reg.assert_not_called()
