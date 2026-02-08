"""OAuth token persistence."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass
class TokenData:
    """Stored OAuth token data."""

    access_token: str
    hdw_access_token: str
    token_type: str
    expires_at: datetime
    client_id: str
    auth_server_url: str

    @property
    def is_expired(self) -> bool:
        """Check if the token has expired (with 5-minute buffer)."""
        return datetime.now(UTC) >= self.expires_at - timedelta(minutes=5)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "access_token": self.access_token,
            "hdw_access_token": self.hdw_access_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at.isoformat(),
            "client_id": self.client_id,
            "auth_server_url": self.auth_server_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenData:
        """Deserialize from dict."""
        return cls(
            access_token=data["access_token"],
            hdw_access_token=data["hdw_access_token"],
            token_type=data["token_type"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            client_id=data["client_id"],
            auth_server_url=data["auth_server_url"],
        )


class TokenStore:
    """Manages OAuth token persistence at ~/.anysite/auth.json.

    File permissions are restricted to owner-only (0o600) for security.
    """

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from anysite.config.paths import get_auth_token_path

            path = get_auth_token_path()
        self._path = path

    def save(self, token_data: TokenData) -> None:
        """Save token data to disk with restricted permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(token_data.to_dict(), indent=2))
        if os.name != "nt":
            self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def load(self) -> TokenData | None:
        """Load token data from disk, or None if not present/corrupt."""
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            return TokenData.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return None

    def delete(self) -> bool:
        """Delete stored token. Returns True if a token was deleted."""
        if self._path.exists():
            self._path.unlink()
            return True
        return False

    def get_valid_token(self) -> TokenData | None:
        """Load token and return only if not expired."""
        token = self.load()
        if token is not None and not token.is_expired:
            return token
        return None

    def get_client_id(self) -> str | None:
        """Get cached client_id from stored token data."""
        token = self.load()
        return token.client_id if token else None
