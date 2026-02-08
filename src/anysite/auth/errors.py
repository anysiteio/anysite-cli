"""OAuth2 authentication error classes."""


class OAuthError(Exception):
    """Base exception for OAuth flow errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class OAuthFlowError(OAuthError):
    """Raised when the OAuth authorization flow fails."""


class OAuthTokenError(OAuthError):
    """Raised when token exchange or parsing fails."""


class OAuthCallbackError(OAuthError):
    """Raised when the localhost callback encounters an error."""


class OAuthRegistrationError(OAuthError):
    """Raised when dynamic client registration fails."""


class OAuthTimeoutError(OAuthError):
    """Raised when user does not complete auth within timeout."""
