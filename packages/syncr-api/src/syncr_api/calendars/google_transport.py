"""One authenticated GET against Google, with the body read under a hard bound.

The seam the read client is tested at, and the only module in the Google read path that knows
httpx exists. A response reduced to a status, its headers, and at most ``MAX_PAGE_BYTES`` of body
is everything the client reads, so a test substitutes recorded answers rather than a transport
double that has to behave like a streaming HTTP library.

**The body is bounded while it arrives.** A page larger than the bound is ``None`` rather than a
truncated body: half a JSON document is not a smaller document, and reporting the bound is the
honest answer.

**The access token is a per-call argument, not client state.** One client serves a whole worker
tick across several tenants, and a token held on it would be the previous tenant's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import httpx

from syncr_api.calendars.google_config import MAX_PAGE_BYTES, REQUEST_TIMEOUT_SECONDS
from syncr_api.core.http_reads import read_bounded_body

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class GoogleResponse:
    """What one call to Google produced, reduced to what the read client reads."""

    status: int
    body: bytes | None
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        """Whether Google answered with a status that carries no page."""
        return self.status >= httpx.codes.BAD_REQUEST


class GoogleTransport(Protocol):
    """One authenticated GET. Raises only what the network raises."""

    async def get(self, url: str, *, params: Mapping[str, str], token: str) -> GoogleResponse:
        """Read ``url`` as the holder of ``token``."""
        ...


@dataclass(frozen=True, slots=True)
class HttpxGoogleTransport:
    """A :class:`GoogleTransport` over httpx, streaming so every body is bounded."""

    client: httpx.AsyncClient

    async def get(self, url: str, *, params: Mapping[str, str], token: str) -> GoogleResponse:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with self.client.stream("GET", url, params=dict(params), headers=headers) as response:
            body = await read_bounded_body(response, max_bytes=MAX_PAGE_BYTES)
            return GoogleResponse(
                status=response.status_code, body=body, headers=dict(response.headers)
            )


def create_google_read_client() -> httpx.AsyncClient:
    """The client the Google reads share, with a per-request timeout.

    Redirects are not followed. The Calendar API answers no redirect, and following one would send
    a bearer token to whatever it named.
    """
    return httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False)
