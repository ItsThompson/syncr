"""The loopback listener the browser redirects back to.

**An ephemeral port, bound to 127.0.0.1.** RFC 8252 requires the Authorization Server to accept
any port on a loopback redirect, and a fresh port per run is what stops two concurrent logins
from colliding. Bound to the loopback interface only: a listener on every interface would let
another machine deliver the code.

**One request is answered and the rest are refused.** A browser asks for a favicon and a
well-meaning extension asks for other things, so a request to any other path is answered 404 and
the wait continues. The code arrives once, on the callback path, and the listener stops.

The server's own rejections arrive here too. An unregistered scope or a malformed PKCE parameter
is delivered as ``error`` on this redirect, which is what lets a waiting CLI fail immediately
rather than sitting until its timeout.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Final, Self
from urllib.parse import parse_qs, urlparse

from syncr_cli.errors import Failure, UsageError

CALLBACK_PATH: Final = "/callback"
LOOPBACK_HOST: Final = "127.0.0.1"

# How long the flow waits for a person to sign in and press a button. Five minutes, which is long
# enough to find a password and short enough that a forgotten terminal does not hold a listener
# open all day. Not the operation-wait timeout: that bounds a poll loop against the API and is a
# figure an agent tunes, and this bounds a human.
CONSENT_TIMEOUT_SECONDS: Final = 300

# What the browser shows when the code has been delivered. Plain by design: no color, no font, no
# ornament. Every visual decision in this product belongs to the token layer, and a page styled
# here would be a second source for one of them.
_PAGE = (
    "<!doctype html><meta charset=utf-8><title>syncr</title>"
    "<pre>syncr: authorized. You can close this window and return to the terminal.</pre>"
)
_REFUSAL_PAGE = (
    "<!doctype html><meta charset=utf-8><title>syncr</title>"
    "<pre>syncr: this window is not the one the CLI is waiting for.</pre>"
)


@dataclass(frozen=True, slots=True)
class Redirected:
    """What the Authorization Server sent back to the listener.

    The code is kept out of the repr for the same reason the tokens are: it is a single-use
    credential, and a default repr is a write waiting for its first caller.
    """

    code: str | None = field(repr=False)
    state: str | None
    error: str | None
    error_description: str | None


class LoopbackReceiver:
    """A one-shot HTTP listener on an ephemeral loopback port."""

    def __init__(self) -> None:
        self._server = HTTPServer((LOOPBACK_HOST, 0), _Handler)
        self._server.received = None  # type: ignore[attr-defined]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self._server.server_close()

    @property
    def redirect_uri(self) -> str:
        """The redirect this run registers, port and all."""
        return f"http://{LOOPBACK_HOST}:{self._server.server_address[1]}{CALLBACK_PATH}"

    def wait(self, *, timeout_seconds: int = CONSENT_TIMEOUT_SECONDS) -> Redirected:
        """The redirect's parameters, or a refusal when nobody arrives in time."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Failure(
                    f"no answer arrived on {self.redirect_uri} within {timeout_seconds}s, so "
                    "nothing was authorized. Run 'syncr auth login' again, and approve the "
                    "consent screen the browser opens."
                )
            self._server.timeout = remaining
            self._server.handle_request()
            received: Redirected | None = self._server.received  # type: ignore[attr-defined]
            if received is not None:
                return received


def require_expected_state(received: Redirected, expected: str) -> None:
    """Refuse a redirect that does not carry the state this run sent.

    The state is this client's own nonce. A redirect carrying someone else's proves the browser
    completed a different flow, and exchanging its code would be exchanging a code this run did
    not ask for.
    """
    if received.state != expected:
        raise UsageError(
            "the browser came back with a state this run did not send, so nothing was "
            "authorized. Run 'syncr auth login' again in a single browser window."
        )


class _Handler(BaseHTTPRequestHandler):
    """Captures the callback's query and answers the browser."""

    # BaseHTTPRequestHandler logs every request to stderr. stderr carries this CLI's notices, so
    # an access log there would be output the product did not choose to write.
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self._answer(HTTPStatus.NOT_FOUND, _REFUSAL_PAGE)
            return
        query = parse_qs(parsed.query)
        self.server.received = Redirected(  # type: ignore[attr-defined]
            code=_one(query, "code"),
            state=_one(query, "state"),
            error=_one(query, "error"),
            error_description=_one(query, "error_description"),
        )
        self._answer(HTTPStatus.OK, _PAGE)

    def _answer(self, status: HTTPStatus, page: str) -> None:
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # The URL of this very request carries the authorization code, so nothing about it may be
        # cached or referred onward.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)


def _one(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[0] if values else None
