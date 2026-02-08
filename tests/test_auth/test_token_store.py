"""Tests for OAuth token store."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta

import pytest

from anysite.auth.token_store import TokenData, TokenStore


def _make_token(
    *,
    expires_at: datetime | None = None,
    client_id: str = "test-client-id",
) -> TokenData:
    return TokenData(
        access_token="eyJhbGciOiJSUzI1NiJ9.test",
        hdw_access_token="eyJhbGciOiJIUzI1NiJ9.hdw",
        token_type="Bearer",
        expires_at=expires_at or (datetime.now(UTC) + timedelta(days=30)),
        client_id=client_id,
        auth_server_url="https://api.anysite.io",
    )


class TestTokenData:
    def test_to_dict_and_from_dict(self) -> None:
        token = _make_token()
        data = token.to_dict()
        restored = TokenData.from_dict(data)
        assert restored.access_token == token.access_token
        assert restored.hdw_access_token == token.hdw_access_token
        assert restored.token_type == token.token_type
        assert restored.client_id == token.client_id
        assert restored.auth_server_url == token.auth_server_url
        assert restored.expires_at == token.expires_at

    def test_is_expired_false(self) -> None:
        token = _make_token(expires_at=datetime.now(UTC) + timedelta(hours=1))
        assert not token.is_expired

    def test_is_expired_true(self) -> None:
        token = _make_token(expires_at=datetime.now(UTC) - timedelta(hours=1))
        assert token.is_expired

    def test_is_expired_within_buffer(self) -> None:
        # 3 minutes left — within the 5-minute buffer → considered expired
        token = _make_token(expires_at=datetime.now(UTC) + timedelta(minutes=3))
        assert token.is_expired

    def test_is_expired_just_outside_buffer(self) -> None:
        # 6 minutes left — outside 5-minute buffer → not expired
        token = _make_token(expires_at=datetime.now(UTC) + timedelta(minutes=6))
        assert not token.is_expired


class TestTokenStore:
    def test_save_and_load(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        token = _make_token()
        store.save(token)
        loaded = store.load()
        assert loaded is not None
        assert loaded.hdw_access_token == token.hdw_access_token
        assert loaded.client_id == token.client_id

    def test_load_nonexistent(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        assert store.load() is None

    def test_delete(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        store.save(_make_token())
        assert store.delete() is True
        assert not path.exists()  # type: ignore[union-attr]

    def test_delete_nonexistent(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        assert store.delete() is False

    def test_get_valid_token_not_expired(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        store.save(_make_token(expires_at=datetime.now(UTC) + timedelta(days=1)))
        assert store.get_valid_token() is not None

    def test_get_valid_token_expired(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        store.save(_make_token(expires_at=datetime.now(UTC) - timedelta(hours=1)))
        assert store.get_valid_token() is None

    def test_get_client_id(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        store.save(_make_token(client_id="cached-id"))
        assert store.get_client_id() == "cached-id"

    def test_get_client_id_no_token(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        assert store.get_client_id() is None

    @pytest.mark.skipif(os.name == "nt", reason="Unix file permissions")
    def test_file_permissions(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        store = TokenStore(path=path)
        store.save(_make_token())
        mode = stat.S_IMODE(path.stat().st_mode)  # type: ignore[union-attr]
        assert mode == 0o600

    def test_corrupt_file(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        path.write_text("not json{{{")  # type: ignore[union-attr]
        store = TokenStore(path=path)
        assert store.load() is None

    def test_missing_fields_in_file(self, tmp_path: object) -> None:
        path = tmp_path / "auth.json"  # type: ignore[operator]
        path.write_text(json.dumps({"access_token": "x"}))  # type: ignore[union-attr]
        store = TokenStore(path=path)
        assert store.load() is None
