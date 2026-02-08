"""OAuth2 authentication subsystem for anysite CLI."""

from __future__ import annotations


def get_oauth_token() -> str | None:
    """Get a valid OAuth access token (hdw_access_token) from the token store.

    Returns:
        The hdw_access_token string if a valid (non-expired) token exists,
        or None otherwise.
    """
    from anysite.auth.token_store import TokenStore

    store = TokenStore()
    token = store.get_valid_token()
    return token.hdw_access_token if token else None
