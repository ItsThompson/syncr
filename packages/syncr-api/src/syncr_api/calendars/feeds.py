"""Fetching a feed body over HTTP, with a conditional request and hard bounds.

Three answers, and the caller has to handle all three, which is why they are a closed union
rather than a body plus an exception:

``FeedBody``        the feed was read, with the cursor to send next time.
``FeedUnchanged``   the publisher answered ``304``, so the last parse still stands.
``FeedUnreachable`` a 4xx, a 5xx, a timeout, or a body over the size bound.

The cursor carries whichever validator the publisher offered. An ``ETag`` is the strong one
and is sent back as ``If-None-Match``; ``Last-Modified`` is the fallback and is sent back as
``If-Modified-Since``. Which one it holds is written into the cursor, because sending an
``ETag`` as a date is how a conditional request silently stops being conditional and every
poll reparses a whole term's timetable.

**The body is read with a hard cap and a hard timeout.** A publisher that stalls must not
hold a worker tick open, and one that streams without end must not exhaust the process. Both
become a stated ``last_error`` with the anchors retained, which is what section 06's error
table requires.

**Decoding tolerates what the standard forbids.** RFC 5545 requires UTF-8; feeds arrive with
a byte-order mark and, from older exporters, in Latin-1. A decode failure would lose a whole
timetable over one accented room name, so the fallback is taken and the events are kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol

import httpx

from syncr_api.calendars.config import FETCH_TIMEOUT_SECONDS, MAX_FEED_BYTES

if TYPE_CHECKING:
    from collections.abc import Mapping

_ETAG_PREFIX: Final = "etag:"
_MODIFIED_PREFIX: Final = "modified:"

_ETAG_HEADER: Final = "ETag"
_MODIFIED_HEADER: Final = "Last-Modified"
_IF_NONE_MATCH: Final = "If-None-Match"
_IF_MODIFIED_SINCE: Final = "If-Modified-Since"

# Publishers that vary their answer by user agent exist, and an unnamed client is the one
# most likely to be refused.
USER_AGENT: Final = "syncr/1.0 (+calendar-ingest)"

_PRIMARY_ENCODING: Final = "utf-8-sig"
_FALLBACK_ENCODING: Final = "latin-1"


@dataclass(frozen=True, slots=True)
class FeedBody:
    """The feed as text, and the cursor to send on the next poll."""

    body: str
    cursor: str | None


@dataclass(frozen=True, slots=True)
class FeedUnchanged:
    """The publisher's validator matched, so nothing was re-sent and nothing is reparsed."""

    cursor: str | None


@dataclass(frozen=True, slots=True)
class FeedUnreachable:
    """The feed could not be read, and why, in words a panel can render."""

    reason: str


type FeedAnswer = FeedBody | FeedUnchanged | FeedUnreachable


class FeedFetcher(Protocol):
    """One conditional read of one feed. The seam a test substitutes a recorded feed at."""

    async def get(self, url: str, *, cursor: str | None) -> FeedAnswer:
        """Read ``url``, sending ``cursor`` as a conditional validator when there is one."""
        ...


class HttpFeedFetcher:
    """A :class:`FeedFetcher` over httpx, bounded in time and in size.

    The client is injected rather than created per call, so connections are reused across a
    worker tick that polls several feeds, and so a test can hand in a transport.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get(self, url: str, *, cursor: str | None) -> FeedAnswer:
        try:
            return await self._read(url, cursor)
        except httpx.TimeoutException:
            return FeedUnreachable(f"the feed did not answer within {FETCH_TIMEOUT_SECONDS:.0f}s")
        except httpx.HTTPError as error:
            return FeedUnreachable(f"the feed could not be reached: {type(error).__name__}")

    async def _read(self, url: str, cursor: str | None) -> FeedAnswer:
        headers = {"User-Agent": USER_AGENT, **conditional_headers(cursor)}
        async with self._client.stream("GET", url, headers=headers) as response:
            if response.status_code == HTTPStatus.NOT_MODIFIED:
                # The publisher's validator matched. Its own headers are absent on a 304, so
                # the cursor that produced the match is the cursor to keep.
                return FeedUnchanged(cursor)
            if response.is_error:
                return FeedUnreachable(
                    f"the feed answered {response.status_code} {response.reason_phrase}"
                )
            body = await _bounded_body(response)
            if body is None:
                return FeedUnreachable(
                    f"the feed is larger than {MAX_FEED_BYTES // (1024 * 1024)}MB"
                )
        return FeedBody(body=body, cursor=cursor_from(response.headers))


def create_feed_client() -> httpx.AsyncClient:
    """The client the worker and the request path share.

    Redirects are followed because a university portal answers a feed URL with one, and a
    fetch that stopped at the 302 would report a working feed as unreadable.
    """
    return httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True)


def conditional_headers(cursor: str | None) -> dict[str, str]:
    """The conditional-request header ``cursor`` names, or none at all."""
    if cursor is None:
        return {}
    if cursor.startswith(_ETAG_PREFIX):
        return {_IF_NONE_MATCH: cursor.removeprefix(_ETAG_PREFIX)}
    if cursor.startswith(_MODIFIED_PREFIX):
        return {_IF_MODIFIED_SINCE: cursor.removeprefix(_MODIFIED_PREFIX)}
    # A cursor written by another provider's adapter. Sending it as either validator would be
    # a guess, so the read is unconditional and correct rather than conditional and wrong.
    return {}


def cursor_from(headers: Mapping[str, str]) -> str | None:
    """The cursor to store from a successful answer's validators.

    ``ETag`` is preferred: it is exact, while ``Last-Modified`` has one-second resolution and
    a feed edited twice in one second would answer ``304`` for a change it had made.
    """
    etag = headers.get(_ETAG_HEADER)
    if etag:
        return f"{_ETAG_PREFIX}{etag}"
    modified = headers.get(_MODIFIED_HEADER)
    if modified:
        return f"{_MODIFIED_PREFIX}{modified}"
    return None


async def _bounded_body(response: httpx.Response) -> str | None:
    """The response body as text, or ``None`` when it exceeds the size bound."""
    chunks: list[bytes] = []
    read = 0
    async for chunk in response.aiter_bytes():
        read += len(chunk)
        if read > MAX_FEED_BYTES:
            return None
        chunks.append(chunk)
    return _decoded(b"".join(chunks))


def _decoded(raw: bytes) -> str:
    try:
        return raw.decode(_PRIMARY_ENCODING)
    except UnicodeDecodeError:
        return raw.decode(_FALLBACK_ENCODING)
