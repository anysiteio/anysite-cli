"""Tests for dataset webhook notifications."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from anysite.dataset.models import NotificationsConfig, WebhookNotification
from anysite.dataset.notifications import WebhookNotifier, _build_payload


class TestWebhookNotifier:
    @pytest.mark.asyncio
    async def test_notify_complete(self) -> None:
        config = NotificationsConfig(
            on_complete=[WebhookNotification(url="https://example.com/done")],
        )
        notifier = WebhookNotifier(config)

        with patch.object(notifier, "_send", new_callable=AsyncMock) as mock_send:
            await notifier.notify_complete("test-ds", 100, 5, 12.3)

            mock_send.assert_called_once()
            _, _, payload = mock_send.call_args[0]
            assert payload["event"] == "complete"
            assert payload["record_count"] == 100
            assert payload["dataset"] == "test-ds"

    @pytest.mark.asyncio
    async def test_notify_failure(self) -> None:
        config = NotificationsConfig(
            on_failure=[WebhookNotification(url="https://example.com/fail")],
        )
        notifier = WebhookNotifier(config)

        with patch.object(notifier, "_send", new_callable=AsyncMock) as mock_send:
            await notifier.notify_failure("test-ds", "Connection timeout", 5.0)

            mock_send.assert_called_once()
            _, _, payload = mock_send.call_args[0]
            assert payload["event"] == "failure"
            assert payload["error"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_empty_hooks_noop(self) -> None:
        config = NotificationsConfig()
        notifier = WebhookNotifier(config)

        with patch.object(notifier, "_send", new_callable=AsyncMock) as mock_send:
            await notifier.notify_complete("test-ds", 0, 0, 0.0)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_error_logged_not_raised(self) -> None:
        config = NotificationsConfig(
            on_complete=[WebhookNotification(url="https://example.com/done")],
        )
        notifier = WebhookNotifier(config)

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Network error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            # Should not raise
            await notifier.notify_complete("test-ds", 10, 2, 1.0)


class TestBuildPayload:
    def test_basic_payload(self) -> None:
        payload = _build_payload(event="test", dataset_name="ds1")
        assert payload["event"] == "test"
        assert payload["dataset"] == "ds1"
        assert "timestamp" in payload

    def test_extra_kwargs(self) -> None:
        payload = _build_payload(event="done", dataset_name="ds1", count=42, error="none")
        assert payload["count"] == 42
        assert payload["error"] == "none"
