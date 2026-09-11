"""The HTTP transport and URL normalization: the two places a real publisher is met.

The client is exercised through ``httpx.MockTransport``, so the code under test is the real
``HttpFeedFetcher`` and the real ``httpx.AsyncClient``: the conditional header is built,
sent, and read back by the same machinery that will talk to a university portal. A hand-rolled
fake client would prove nothing about whether the header reaches the wire under the name a
server checks.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import pytest

from syncr_api.calendars import feeds

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
from syncr_api.calendars.config import (
    CURSOR_MAX_LENGTH,
    FETCH_TIMEOUT_SECONDS,
    MAX_FEED_BYTES,
)
from syncr_api.calendars.feeds import (
    USER_AGENT,
    FeedBody,
    FeedUnchanged,
    FeedUnreachable,
    HttpFeedFetcher,
    conditional_headers,
    cursor_from,
)
from syncr_api.calendars.urls import normalize_feed_url
from syncr_api.core.errors import ValidationFailed
from tests.hostile_ics import UNIVERSITY_TIMETABLE

FEED_URL = "https://example.ac.uk/timetable.ics"
ETAG_VALUE = 'W/"abc123"'
ETAG_CURSOR = f"etag:{ETAG_VALUE}"
MODIFIED_VALUE = "Wed, 04 Feb 2026 09:15:00 GMT"

# An address carrying userinfo. Not a credential: the shape of one, so the test can prove the
# normalizer drops it rather than storing it back onto the Settings panel.
CREDENTIALED_URL = "https://user:secret@example.ac.uk/t.ics"  # pragma: allowlist secret
MODIFIED_CURSOR = f"modified:{MODIFIED_VALUE}"


def fetcher(handler: httpx.MockTransport) -> tuple[HttpFeedFetcher, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=handler, timeout=FETCH_TIMEOUT_SECONDS)
    return HttpFeedFetcher(client), client


def responding(
    status: int = 200,
    *,
    body: bytes = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
    headers: dict[str, str] | None = None,
    seen: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=body, headers=headers or {})

    return httpx.MockTransport(handle)


# --------------------------------------------------------------------------------
# The cursor: which validator it holds, and how it is sent back
# --------------------------------------------------------------------------------


def test_an_etag_is_preferred_over_a_last_modified_date() -> None:
    # Last-Modified has one-second resolution, so a feed edited twice in one second would
    # answer 304 for a change it had made.
    both = {"ETag": ETAG_VALUE, "Last-Modified": MODIFIED_VALUE}

    assert cursor_from(both) == ETAG_CURSOR
    assert cursor_from({"Last-Modified": MODIFIED_VALUE}) == MODIFIED_CURSOR
    assert cursor_from({}) is None


def test_the_cursor_decides_which_conditional_header_is_sent() -> None:
    # Sending an ETag as a date is how a conditional request silently stops being conditional
    # and every poll reparses a whole term's timetable.
    assert conditional_headers(ETAG_CURSOR) == {"If-None-Match": ETAG_VALUE}
    assert conditional_headers(MODIFIED_CURSOR) == {"If-Modified-Since": MODIFIED_VALUE}
    assert conditional_headers(None) == {}
    # A cursor another provider's adapter wrote: reading it as either validator would be a
    # guess, so the read is unconditional and correct rather than conditional and wrong.
    assert conditional_headers("CAESDA0KDQoNCg0K") == {}


async def test_a_stored_etag_reaches_the_wire_as_if_none_match() -> None:
    seen: list[httpx.Request] = []
    reader, client = fetcher(responding(headers={"ETag": ETAG_VALUE}, seen=seen))

    async with client:
        answer = await reader.get(FEED_URL, cursor=ETAG_CURSOR)

    assert seen[0].headers["If-None-Match"] == ETAG_VALUE
    assert seen[0].headers["User-Agent"] == USER_AGENT
    assert isinstance(answer, FeedBody)
    assert answer.cursor == ETAG_CURSOR


async def test_a_304_is_an_unchanged_answer_carrying_the_cursor_that_matched() -> None:
    # A 304 carries no ETag of its own, so the cursor that produced the match is the one to
    # keep. Storing None would make the next poll unconditional and reparse the whole feed.
    reader, client = fetcher(responding(304, body=b""))

    async with client:
        answer = await reader.get(FEED_URL, cursor=ETAG_CURSOR)

    assert answer == FeedUnchanged(cursor=ETAG_CURSOR)


# --------------------------------------------------------------------------------
# Bounds and failures
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
async def test_a_4xx_or_5xx_is_unreachable_and_names_the_status(status: int) -> None:
    reader, client = fetcher(responding(status))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)
    assert str(status) in answer.reason


async def test_a_timeout_is_unreachable_and_names_the_bound() -> None:
    def stall(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    reader, client = fetcher(httpx.MockTransport(stall))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)
    assert "15s" in answer.reason


async def test_a_connection_failure_is_unreachable_rather_than_a_raised_error() -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    reader, client = fetcher(httpx.MockTransport(refuse))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)


async def test_a_body_past_the_size_bound_is_unreachable_rather_than_read() -> None:
    # A publisher streaming without end must not exhaust the process.
    reader, client = fetcher(responding(body=b"X" * (MAX_FEED_BYTES + 1)))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)
    assert "larger than" in answer.reason


async def test_a_body_at_the_size_bound_is_read() -> None:
    # The other half of the bound: a feed exactly at the limit is a feed syncr reads, so the
    # comparison is shown to be on the right side of the boundary.
    reader, client = fetcher(responding(body=b"X" * MAX_FEED_BYTES))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedBody)


# --------------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------------


async def test_a_byte_order_mark_is_not_read_as_part_of_the_first_property() -> None:
    # A BOM in front of BEGIN:VCALENDAR makes the first content line's NAME unrecognisable,
    # which loses the whole feed rather than one property.
    reader, client = fetcher(responding(body=b"\xef\xbb\xbf" + UNIVERSITY_TIMETABLE.encode()))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedBody)
    assert answer.body.startswith("BEGIN:VCALENDAR")


async def test_a_latin_1_feed_is_decoded_rather_than_lost() -> None:
    # RFC 5545 requires UTF-8 and older exporters send Latin-1. Losing a whole timetable over
    # one accented room name is the wrong trade.
    reader, client = fetcher(responding(body=b"SUMMARY:Caf\xe9 seminar\r\n"))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedBody)
    assert "Caf" in answer.body


# --------------------------------------------------------------------------------
# URL normalization
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("webcal://example.ac.uk/t.ics", "https://example.ac.uk/t.ics"),
        ("ics://example.ac.uk/t.ics", "https://example.ac.uk/t.ics"),
        ("WEBCAL://example.ac.uk/t.ics", "https://example.ac.uk/t.ics"),
        ("  https://example.ac.uk/t.ics  ", "https://example.ac.uk/t.ics"),
        ("http://example.ac.uk/t.ics", "http://example.ac.uk/t.ics"),
        (
            "https://calendar.google.com/calendar/ical/x%40group/private-abc/basic.ics",
            "https://calendar.google.com/calendar/ical/x%40group/private-abc/basic.ics",
        ),
        ("https://example.ac.uk/t.ics?token=abc123", "https://example.ac.uk/t.ics?token=abc123"),
        ("https://example.ac.uk/t.ics#frag", "https://example.ac.uk/t.ics"),
        ("https://Example.AC.UK/Timetable.ics", "https://example.ac.uk/Timetable.ics"),
        (CREDENTIALED_URL, "https://example.ac.uk/t.ics"),
        ("https://example.ac.uk:8443/t.ics", "https://example.ac.uk:8443/t.ics"),
    ],
    ids=[
        "webcal",
        "ics scheme",
        "upper case scheme",
        "surrounding space",
        "plain http is kept",
        "an escaped google address survives",
        "a feed token survives",
        "a fragment is dropped",
        "the host is folded but the path is not",
        "userinfo is dropped",
        "a port survives",
    ],
)
def test_an_accepted_address_is_normalized_to_what_syncr_fetches(raw: str, expected: str) -> None:
    assert normalize_feed_url(raw) == expected


def test_an_explicit_e2e_publisher_exception_normalizes_a_loopback_feed() -> None:
    url = "http://127.0.0.1:58041/timetable.ics"

    assert normalize_feed_url(url, trusted_hosts=frozenset({"127.0.0.1"})) == url


def test_two_spellings_of_one_host_normalize_to_one_address() -> None:
    # The duplication this module exists to prevent. A host is case-insensitive, so two rows
    # differing only in its case would be two sources for one feed, each contributing the same
    # commitments and the solver treating one lecture as two.
    assert normalize_feed_url("https://Example.com/t.ics") == normalize_feed_url(
        "https://example.com/t.ics"
    )


def test_a_credential_in_the_address_is_not_stored_to_be_read_back() -> None:
    # The stored address is what the Settings panel shows, so userinfo would put a password on a
    # screen the user reads.
    normalized = normalize_feed_url(CREDENTIALED_URL)

    assert "secret" not in normalized
    assert "user" not in normalized


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "example.ac.uk/t.ics",
        "ftp://example.ac.uk/t.ics",
        "https://",
        "file:///etc/passwd",
    ],
    ids=["blank", "whitespace", "no scheme", "wrong scheme", "no host", "a local file"],
)
def test_an_address_syncr_cannot_fetch_is_rejected_with_the_schemes_it_accepts(raw: str) -> None:
    with pytest.raises(ValidationFailed) as raised:
        normalize_feed_url(raw)

    assert "webcal" in raised.value.detail
    # Every rejection names the surviving capability.
    assert "still syncs" in raised.value.detail


def test_an_address_longer_than_the_column_is_rejected_rather_than_truncated() -> None:
    # Truncating would store an address that fetches something else, or nothing.
    with pytest.raises(ValidationFailed):
        normalize_feed_url(f"https://example.ac.uk/{'x' * 3000}.ics")


# --------------------------------------------------------------------------------
# The cursor a publisher's header can make too long for the column
# --------------------------------------------------------------------------------


def test_an_etag_the_column_cannot_hold_is_dropped_rather_than_stored() -> None:
    # Stored, it raised at the flush, and the flush covers the WHOLE tenant's sync pass: every
    # sibling source in that transaction loses the state it had already earned, the duty fails every
    # tick, and nothing surfaces because the failure belongs to no single source. A CDN emits long
    # ETags, so this is a publisher's header rather than a hostile one.
    oversize = '"' + "a" * CURSOR_MAX_LENGTH + '"'

    assert cursor_from({"ETag": oversize}) is None


def test_a_last_modified_the_column_cannot_hold_is_dropped_too() -> None:
    # The same bound on the other validator, so the guard is a property of the cursor rather than of
    # the header that happened to be measured.
    assert cursor_from({"Last-Modified": "M" * CURSOR_MAX_LENGTH}) is None


def test_a_cursor_at_the_column_width_is_still_stored() -> None:
    # The boundary is inclusive, so a validator the column can hold is not thrown away: dropping it
    # costs an unconditional re-read on every poll.
    exact = "a" * (CURSOR_MAX_LENGTH - len("etag:"))

    assert cursor_from({"ETag": exact}) == f"etag:{exact}"
    assert len(cursor_from({"ETag": exact}) or "") == CURSOR_MAX_LENGTH


async def test_an_oversize_etag_still_yields_a_readable_feed() -> None:
    # The body is still read and the events still parse: the oversize validator costs the CURSOR,
    # not the feed. Without this the whole answer was lost at the write.
    oversize = '"' + "a" * CURSOR_MAX_LENGTH + '"'
    reader, client = fetcher(responding(headers={"ETag": oversize}))

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedBody)
    assert answer.cursor is None
    assert answer.body.startswith("BEGIN:VCALENDAR")


async def test_a_publisher_that_trickles_is_cut_off_at_the_stated_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # httpx's timeout is PER OPERATION, so a chunk every few seconds resets the read clock and the
    # total read is bounded only by the size cap: measured against the real bound, an 80-second read
    # against 15 seconds, with the worker tick and its transaction held for all of it.
    #
    # The bound is patched DOWN rather than the trickle made longer, because a test that proves a
    # 15-second deadline by waiting 15 seconds is a test nobody runs.
    monkeypatch.setattr(feeds, "FETCH_TIMEOUT_SECONDS", 0.2)

    class Trickle(httpx.AsyncBaseTransport):
        """A publisher that answers, then sends one byte at a time for far longer than the bound."""

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            async def body() -> AsyncIterator[bytes]:
                for _ in range(100):
                    await asyncio.sleep(0.05)
                    yield b"X"

            return httpx.Response(200, content=body())

    client = httpx.AsyncClient(transport=Trickle(), timeout=30.0)
    reader = HttpFeedFetcher(client)

    async with client:
        answer = await reader.get(FEED_URL, cursor=None)

    assert isinstance(answer, FeedUnreachable)
    assert "did not answer" in answer.reason
