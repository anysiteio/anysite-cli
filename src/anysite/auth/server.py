"""Local HTTP callback server for OAuth2 redirect."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

from anysite.auth.errors import OAuthCallbackError, OAuthTimeoutError

SUCCESS_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Anysite CLI</title></head>
<body style="font-family:system-ui;text-align:center;padding:60px">
  <h2>Authentication successful!</h2>
  <p>You can close this tab and return to the terminal.</p>
</body>
</html>"""

ERROR_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Anysite CLI</title></head>
<body style="font-family:system-ui;text-align:center;padding:60px">
  <h2>Authentication failed</h2>
  <p>{error}</p>
</body>
</html>"""


@dataclass
class CallbackResult:
    """Result from the OAuth callback."""

    code: str
    state: str
    error: str | None = None
    error_description: str | None = None


@dataclass
class CallbackServer:
    """Ephemeral HTTP server on localhost to receive OAuth2 callback.

    Listens on a random available port on 127.0.0.1.
    Serves a single request, extracts the authorization code,
    returns a success page to the browser, and shuts down.
    """

    timeout: int = 120
    _port: int = field(default=0, init=False)
    _server: HTTPServer | None = field(default=None, init=False)
    _thread: Thread | None = field(default=None, init=False)
    _result: CallbackResult | None = field(default=None, init=False)
    _error: str | None = field(default=None, init=False)
    _event: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False)

    @property
    def port(self) -> int:
        return self._port

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self._port}/callback"

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Start listening. Binds to 127.0.0.1 on a random port."""
        self._loop = loop or asyncio.get_event_loop()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)

                error = params.get("error", [None])[0]
                if error:
                    error_desc = params.get("error_description", [""])[0]
                    outer._error = f"{error}: {error_desc}"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(ERROR_HTML.format(error=error_desc or error).encode())
                else:
                    code_list = params.get("code", [])
                    state_list = params.get("state", [])
                    if code_list:
                        outer._result = CallbackResult(
                            code=code_list[0],
                            state=state_list[0] if state_list else "",
                        )
                    else:
                        outer._error = "No authorization code in callback"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(SUCCESS_HTML.encode())

                # Signal that we received the callback
                if outer._loop:
                    outer._loop.call_soon_threadsafe(outer._event.set)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass  # Suppress HTTP server logging

        server = HTTPServer(("127.0.0.1", 0), Handler)
        self._port = server.server_address[1]
        self._server = server

        self._thread = Thread(target=server.handle_request, daemon=True)
        self._thread.start()

    async def wait_for_callback(self) -> CallbackResult:
        """Wait for the OAuth callback redirect.

        Raises:
            OAuthTimeoutError: If no callback received within timeout.
            OAuthCallbackError: If callback contains an error.
        """
        try:
            await asyncio.wait_for(self._event.wait(), timeout=self.timeout)
        except TimeoutError:
            raise OAuthTimeoutError(
                f"Authentication timed out after {self.timeout} seconds. Please try again."
            ) from None

        if self._error:
            raise OAuthCallbackError(f"Authentication failed: {self._error}")

        if self._result is None:
            raise OAuthCallbackError("No authorization code received")

        return self._result

    def stop(self) -> None:
        """Stop the server and release the port."""
        if self._server:
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None
