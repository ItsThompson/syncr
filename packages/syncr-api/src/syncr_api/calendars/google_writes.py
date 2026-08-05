"""One authenticated mutating request against Google, and the seam the write path is tested at.

The read transport next door serves a ``GET`` with query parameters and no body, which is every
request a read makes. A write sends a JSON body on ``POST`` and ``PATCH`` and sends nothing at all
on ``DELETE``, so it is a second method rather than a widened first one: a read cannot be made to
carry a body by accident, and a test double for one cannot answer the other.

**The response is reduced to the same three values a read's is**, so the failure classification, the
rate-limit reading and the backoff schedule are the ones the read path already has rather than a
second set that could disagree about what a 403 means.

**A body is bounded on the way back like every other.** An event Google echoes is small, and the
bound exists for the same reason the read's does: a page larger than the bound is ``None`` rather
than a truncated body, because half a JSON document is not a smaller document.

**The access token is a per-call argument, not client state.** One client serves a whole worker tick
across several tenants, and a token held on it would be the previous tenant's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import httpx

from syncr_api.calendars.google_config import (
    MAX_PAGE_BYTES,
    WRITE_REQUEST_TIMEOUT_SECONDS,
)
from syncr_api.calendars.google_transport import GoogleResponse
from syncr_api.core.http_reads import read_bounded_body

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonObject


class GoogleWriteTransport(Protocol):
    """One authenticated mutating request. Raises only what the network raises."""

    async def send(
        self, method: str, url: str, *, token: str, body: JsonObject | None = None
    ) -> GoogleResponse:
        """Send ``method`` to ``url`` as the holder of ``token``, with ``body`` if there is one."""
        ...


@dataclass(frozen=True, slots=True)
class HttpxGoogleWriteTransport:
    """A :class:`GoogleWriteTransport` over httpx, streaming so every body is bounded."""

    client: httpx.AsyncClient

    async def send(
        self, method: str, url: str, *, token: str, body: JsonObject | None = None
    ) -> GoogleResponse:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        request = self.client.build_request(method, url, headers=headers, json=body)
        response = await self.client.send(request, stream=True)
        try:
            read = await read_bounded_body(response, max_bytes=MAX_PAGE_BYTES)
            return GoogleResponse(
                status=response.status_code, body=read, headers=dict(response.headers)
            )
        finally:
            await response.aclose()


def create_google_write_client() -> httpx.AsyncClient:
    """The client the projection's writes share, with a per-request timeout.

    Redirects are not followed, for the reason every Google client here does not follow them: the
    Calendar API answers none, and following one would send a bearer token to whatever it named. On
    a mutating request that would also mean re-sending the body.
    """
    return httpx.AsyncClient(timeout=WRITE_REQUEST_TIMEOUT_SECONDS, follow_redirects=False)
