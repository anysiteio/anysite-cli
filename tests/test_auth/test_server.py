"""Tests for OAuth callback server."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from anysite.auth.errors import OAuthCallbackError, OAuthTimeoutError
from anysite.auth.server import CallbackServer


class TestCallbackServer:
    def test_server_starts_and_assigns_port(self) -> None:
        loop = asyncio.new_event_loop()
        server = CallbackServer(timeout=5)
        server.start(loop=loop)
        try:
            assert server.port > 0
            assert "127.0.0.1" in server.redirect_uri
            assert "/callback" in server.redirect_uri
        finally:
            server.stop()
            loop.close()

    async def test_callback_success(self) -> None:
        server = CallbackServer(timeout=10)
        loop = asyncio.get_event_loop()
        server.start(loop=loop)
        try:
            # Send callback request in background
            async def send_callback() -> None:
                await asyncio.sleep(0.1)
                async with httpx.AsyncClient() as client:
                    await client.get(
                        f"http://127.0.0.1:{server.port}/callback",
                        params={"code": "test-code-123", "state": "test-state-456"},
                    )

            send_task = asyncio.create_task(send_callback())
            result = await server.wait_for_callback()
            await send_task

            assert result.code == "test-code-123"
            assert result.state == "test-state-456"
        finally:
            server.stop()

    async def test_callback_with_error(self) -> None:
        server = CallbackServer(timeout=10)
        loop = asyncio.get_event_loop()
        server.start(loop=loop)
        try:
            async def send_error_callback() -> None:
                await asyncio.sleep(0.1)
                async with httpx.AsyncClient() as client:
                    await client.get(
                        f"http://127.0.0.1:{server.port}/callback",
                        params={"error": "access_denied", "error_description": "User denied"},
                    )

            send_task = asyncio.create_task(send_error_callback())
            with pytest.raises(OAuthCallbackError, match="User denied"):
                await server.wait_for_callback()
            await send_task
        finally:
            server.stop()

    async def test_callback_timeout(self) -> None:
        server = CallbackServer(timeout=1)
        loop = asyncio.get_event_loop()
        server.start(loop=loop)
        try:
            with pytest.raises(OAuthTimeoutError, match="timed out"):
                await server.wait_for_callback()
        finally:
            server.stop()
