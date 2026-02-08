"""OAuth2 Authorization Code + PKCE flow orchestration."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import webbrowser
from typing import Any
from urllib.parse import urlencode

import httpx

from anysite.auth.client_registration import register_client
from anysite.auth.errors import OAuthFlowError, OAuthTokenError
from anysite.auth.server import CallbackServer
from anysite.auth.token_store import TokenData, TokenStore

DEFAULT_AUTH_SERVER = "https://api.anysite.io"
DEFAULT_SCOPE = "mcp:* openid profile"


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256).

    Returns:
        Tuple of (code_verifier, code_challenge).
    """
    verifier_bytes = secrets.token_bytes(64)
    code_verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode("ascii")

    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return code_verifier, code_challenge


def build_authorization_url(
    auth_server_url: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str = DEFAULT_SCOPE,
) -> str:
    """Build the authorization URL with all required parameters."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": scope,
    }
    base = auth_server_url.rstrip("/")
    return f"{base}/oauth/authorize?{urlencode(params)}"


async def exchange_code_for_token(
    auth_server_url: str,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    """Exchange authorization code for access token via POST /oauth/token.

    Returns:
        Token response dict with access_token, token_type, expires_in.

    Raises:
        OAuthTokenError: If token exchange fails.
    """
    url = f"{auth_server_url.rstrip('/')}/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as e:
        raise OAuthTokenError(f"Token exchange failed: {e}") from e

    if response.status_code != 200:
        detail = ""
        try:
            detail = response.json().get("error_description", response.text)
        except Exception:
            detail = response.text
        raise OAuthTokenError(f"Token exchange failed ({response.status_code}): {detail}")

    return response.json()


def extract_hdw_token(jwt_token: str) -> str:
    """Extract the hdw_access_token from the JWT payload.

    Decodes the JWT payload without signature verification
    (received over HTTPS, no need to verify client-side).

    Raises:
        OAuthTokenError: If JWT parsing fails or hdw_access_token is missing.
    """
    try:
        parts = jwt_token.split(".")
        if len(parts) < 2:
            raise ValueError("Invalid JWT format")

        # Base64url decode the payload (second segment)
        payload_b64 = parts[1]
        # Add padding if needed
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)

        hdw_token = payload.get("hdw_access_token")
        if not hdw_token:
            raise ValueError("Missing hdw_access_token in JWT payload")

        return hdw_token
    except (ValueError, json.JSONDecodeError, KeyError) as e:
        raise OAuthTokenError(f"Failed to extract API token from OAuth response: {e}") from e


async def run_oauth_flow(
    auth_server_url: str | None = None,
    *,
    callback_timeout: int = 120,
    token_store: TokenStore | None = None,
    no_browser: bool = False,
) -> TokenData:
    """Execute the full OAuth2 Authorization Code + PKCE flow.

    Args:
        auth_server_url: Auth server URL (default: production).
        callback_timeout: Seconds to wait for user to complete auth.
        token_store: Custom token store (for testing).
        no_browser: If True, print URL instead of opening browser.

    Returns:
        TokenData with the valid access token.

    Raises:
        OAuthFlowError: If any step of the flow fails.
    """
    from datetime import UTC, datetime, timedelta

    server_url = auth_server_url or DEFAULT_AUTH_SERVER
    store = token_store or TokenStore()

    # Start callback server to get the port
    callback_server = CallbackServer(timeout=callback_timeout)
    loop = asyncio.get_event_loop()
    callback_server.start(loop=loop)

    try:
        redirect_uri = callback_server.redirect_uri

        # Register client (or reuse cached client_id)
        cached_client_id = store.get_client_id()
        if cached_client_id:
            client_id = cached_client_id
        else:
            try:
                registration = await register_client(server_url, redirect_uri)
                client_id = registration.client_id
            except Exception as e:
                raise OAuthFlowError(f"Client registration failed: {e}") from e

        # Generate PKCE pair and state
        code_verifier, code_challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(32)

        # Build and open authorization URL
        auth_url = build_authorization_url(
            server_url, client_id, redirect_uri, state, code_challenge,
        )

        if no_browser:
            from rich.console import Console

            console = Console()
            console.print(f"\nOpen this URL in your browser:\n\n  {auth_url}\n")
        else:
            webbrowser.open(auth_url)

        # Wait for callback
        result = await callback_server.wait_for_callback()

        # Verify state
        if result.state != state:
            raise OAuthFlowError("State mismatch — possible CSRF attack. Please try again.")

        # Exchange code for token
        token_response = await exchange_code_for_token(
            server_url, result.code, client_id, redirect_uri, code_verifier,
        )

        access_token = token_response["access_token"]
        expires_in = token_response.get("expires_in", 2592000)

        # Extract hdw_access_token from JWT
        hdw_token = extract_hdw_token(access_token)

        # Save token
        token_data = TokenData(
            access_token=access_token,
            hdw_access_token=hdw_token,
            token_type=token_response.get("token_type", "Bearer"),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            client_id=client_id,
            auth_server_url=server_url,
        )
        store.save(token_data)

        return token_data

    finally:
        callback_server.stop()
