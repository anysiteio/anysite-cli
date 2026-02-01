"""Webhook notifications for dataset collection events."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from anysite.dataset.models import NotificationsConfig

logger = logging.getLogger(__name__)


class WebhookNotifier:
    """Send webhook notifications on collection complete/failure."""

    def __init__(self, config: NotificationsConfig) -> None:
        self.config = config

    async def notify_complete(
        self,
        dataset_name: str,
        record_count: int,
        source_count: int,
        duration: float,
    ) -> None:
        """Send on_complete webhooks."""
        if not self.config.on_complete:
            return

        payload = _build_payload(
            event="complete",
            dataset_name=dataset_name,
            record_count=record_count,
            source_count=source_count,
            duration=duration,
        )

        for hook in self.config.on_complete:
            await self._send(hook.url, hook.headers, payload)

    async def notify_failure(
        self,
        dataset_name: str,
        error: str,
        duration: float,
    ) -> None:
        """Send on_failure webhooks."""
        if not self.config.on_failure:
            return

        payload = _build_payload(
            event="failure",
            dataset_name=dataset_name,
            error=error,
            duration=duration,
        )

        for hook in self.config.on_failure:
            await self._send(hook.url, hook.headers, payload)

    async def _send(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> None:
        """Send a single webhook POST."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            logger.info("Notification sent to %s", url)
        except Exception as e:
            logger.error("Notification to %s failed: %s", url, e)


def _build_payload(
    *,
    event: str,
    dataset_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a webhook notification payload."""
    return {
        "event": event,
        "dataset": dataset_name,
        "timestamp": datetime.now(UTC).isoformat(),
        **kwargs,
    }
