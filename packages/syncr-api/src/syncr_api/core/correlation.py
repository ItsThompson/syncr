"""Per-request correlation.

A pure-ASGI middleware that, once per HTTP request, clears any contextvars left
over from a reused worker context, binds the correlation id, and echoes it on the
response. ``merge_contextvars`` is first in the logging chain, so every subsequent
line: the handler's, the service layer's, and the catch-all fault log: carries the
same id with no per-call-site effort.

It must NOT be a ``BaseHTTPMiddleware``: that runs the handler in a separate
contextvars context, so bindings made here would be invisible to the handler and to
the fault log. Being pure-ASGI, the bindings live in the request's own context and
survive out to the outermost error handler.

An inbound ``X-Correlation-Id`` is honored so one user action shares an id across
the browser, the api, and the worker job it triggers. It is a correlation
convenience and never a trust boundary, so it is length- and charset-bounded before
use; a value outside that shape is dropped and a fresh id is minted.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from syncr_common.logging import (
    bind_correlation_id,
    clear_context,
    new_correlation_id,
)

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_ID_HEADER = "X-Correlation-Id"

# A hostile client must not inject newlines, control characters, or unbounded
# length into a log field or a response header.
MAX_CORRELATION_ID_LENGTH = 128
_CORRELATION_ID_RE = re.compile(rf"[A-Za-z0-9._-]{{1,{MAX_CORRELATION_ID_LENGTH}}}")

# ASGI header names arrive lower-cased as latin-1 bytes.
_HEADER_KEY = CORRELATION_ID_HEADER.lower().encode("latin-1")


def _inbound_correlation_id(scope: Scope) -> str | None:
    """A valid inbound correlation id from the scope, or ``None``."""
    for name, value in scope["headers"]:
        if name == _HEADER_KEY:
            candidate = value.decode("latin-1", "replace").strip()
            return candidate if _CORRELATION_ID_RE.fullmatch(candidate) else None
    return None


class CorrelationMiddleware:
    """Bind the correlation id into contextvars and echo it on the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Clear first: a worker's context is reused across requests, so a prior
        # request's bindings must not leak into this one.
        clear_context()
        correlation_id = _inbound_correlation_id(scope) or new_correlation_id()
        bind_correlation_id(correlation_id)

        await self.app(scope, receive, _echoing(send, correlation_id))


def _echoing(send: Send, correlation_id: str) -> Send:
    """Wrap ``send`` so the response start carries the correlation id header."""
    header = (_HEADER_KEY, correlation_id.encode("latin-1"))

    async def send_with_header(message: Message) -> None:
        if message["type"] == "http.response.start":
            message = {**message, "headers": [*message.get("headers", []), header]}
        await send(message)

    return send_with_header
