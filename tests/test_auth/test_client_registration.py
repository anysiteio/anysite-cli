"""Tests for OAuth dynamic client registration."""

from __future__ import annotations

import httpx
import pytest
import respx

from anysite.auth.client_registration import register_client
from anysite.auth.errors import OAuthRegistrationError


class TestRegisterClient:
    @respx.mock
    async def test_register_client_success(self) -> None:
        respx.post("https://api.anysite.io/oauth/register").mock(
            return_value=httpx.Response(
                201,
                json={
                    "client_id": "mcp-client-abc123",
                    "client_name": "anysite-cli",
                    "redirect_uris": ["http://127.0.0.1:8585/callback"],
                },
            )
        )

        result = await register_client(
            "https://api.anysite.io",
            "http://127.0.0.1:8585/callback",
        )
        assert result.client_id == "mcp-client-abc123"
        assert result.client_name == "anysite-cli"

    @respx.mock
    async def test_register_client_failure(self) -> None:
        respx.post("https://api.anysite.io/oauth/register").mock(
            return_value=httpx.Response(
                500,
                json={"error": "server_error", "error_description": "Registration failed"},
            )
        )

        with pytest.raises(OAuthRegistrationError, match="500"):
            await register_client(
                "https://api.anysite.io",
                "http://127.0.0.1:8585/callback",
            )

    @respx.mock
    async def test_register_client_network_error(self) -> None:
        respx.post("https://api.anysite.io/oauth/register").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(OAuthRegistrationError, match="Failed to register"):
            await register_client(
                "https://api.anysite.io",
                "http://127.0.0.1:8585/callback",
            )
