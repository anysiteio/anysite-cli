"""Dynamic OAuth2 client registration."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from anysite.auth.errors import OAuthRegistrationError

DEFAULT_CLIENT_NAME = "anysite-cli"


@dataclass
class ClientRegistration:
    """Result of dynamic client registration."""

    client_id: str
    client_name: str
    redirect_uris: list[str]


async def register_client(
    auth_server_url: str,
    redirect_uri: str,
    *,
    timeout: int = 30,
) -> ClientRegistration:
    """Register a public OAuth2 client via POST /oauth/register.

    Args:
        auth_server_url: Base URL of the auth server.
        redirect_uri: The redirect URI to register.
        timeout: HTTP timeout in seconds.

    Returns:
        ClientRegistration with the assigned client_id.

    Raises:
        OAuthRegistrationError: If registration fails.
    """
    url = f"{auth_server_url.rstrip('/')}/oauth/register"
    payload = {
        "client_name": DEFAULT_CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "mcp:* openid profile",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        raise OAuthRegistrationError(f"Failed to register OAuth client: {e}") from e

    if response.status_code not in (200, 201):
        detail = ""
        try:
            detail = response.json().get("error_description", response.text)
        except Exception:
            detail = response.text
        raise OAuthRegistrationError(f"Client registration failed ({response.status_code}): {detail}")

    data = response.json()
    return ClientRegistration(
        client_id=data["client_id"],
        client_name=data.get("client_name", DEFAULT_CLIENT_NAME),
        redirect_uris=data.get("redirect_uris", [redirect_uri]),
    )
