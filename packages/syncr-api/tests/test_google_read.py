"""The Google read: pagination, rate limits, the deadline, and what a cursor is allowed to be.

The transport is faked and everything else is real: the backoff schedule, the payload validation,
the pagination loop, and the cursor bounds all run.

Four claims carry the weight here, and each is a failure proved rather than
asserted:

- **the deadline covers the whole read**, so a host that answers every page slowly is bounded by the
  same number as one that hangs on the first request. The ICS reader paid for that defect, one
  provider over;
- **the cursor is bounded before it is stored**, because an oversize write does not fail one source:
  it rolls back the transaction the whole tenant's sync pass is in, and every sibling source loses
  the state it had already earned;
- **a rate limit is read from the error's reason**, not its status, because a 403 is also what an
  insufficient grant answers and those two send the user to opposite repairs;
- **every wait is bounded and counted**, and the count reaches the source.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING

import httpx
import pytest

from syncr_api.calendars.config import CURSOR_MAX_LENGTH
from syncr_api.calendars.google_backoff import BackoffPolicy, stated_retry_after
from syncr_api.calendars.google_client import (
    CalendarsRead,
    EventsRead,
    GoogleCalendarClient,
    GoogleReadFailed,
    SyncTokenExpired,
)
from syncr_api.calendars.google_config import (
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    MAX_HONOURED_RETRY_AFTER_SECONDS,
    MAX_JITTER_SECONDS,
    MAX_PAGE_BYTES,
    MAX_PAGES,
)
from syncr_api.calendars.google_cursors import CURSOR_PREFIX, bounded_cursor, sync_token_of
from syncr_api.calendars.google_transport import GoogleResponse, HttpxGoogleTransport
from syncr_api.google_account.tokens import GoogleGrantDead, NoGoogleAccount
from syncr_domain.intervals import Interval
from tests.fake_google import (
    ACCESS_TOKEN,
    CALENDAR_ID,
    SYNC_TOKEN,
    FixedTokens,
    RecordedGoogle,
    calendar,
    calendar_list_page,
    error_body,
    event,
    events_page,
    failed,
    ok,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

WINDOW = Interval(
    datetime(2026, 2, 9, tzinfo=UTC),
    datetime(2026, 2, 23, tzinfo=UTC),
)


def client(
    answers: Sequence[GoogleResponse],
    *,
    tokens: FixedTokens | None = None,
    waits: list[float] | None = None,
) -> tuple[GoogleCalendarClient, RecordedGoogle]:
    """A client over a scripted transport, recording every wait instead of sleeping."""
    transport = RecordedGoogle(answers=answers)
    recorded = waits if waits is not None else []

    async def sleep(seconds: float) -> None:
        recorded.append(seconds)

    return (
        GoogleCalendarClient(
            transport=transport,
            tokens=tokens or FixedTokens(),
            # Seeded, so a jittered wait is a value a test can state.
            backoff=BackoffPolicy(random=Random(1)),  # noqa: S311 - jitter, not a key
            sleep=sleep,
        ),
        transport,
    )


# --------------------------------------------------------------------------------------
# What the read asks for
# --------------------------------------------------------------------------------------


async def test_a_first_read_asks_for_a_window_and_expanded_instances() -> None:
    reader, transport = client([ok(events_page(event()))])

    await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    asked = transport.calls[0].params
    assert asked["singleEvents"] == "true"
    assert asked["timeMin"] == WINDOW.start.isoformat()
    assert asked["timeMax"] == WINDOW.end.isoformat()
    assert "syncToken" not in asked
    # Google forbids showDeleted=false beside a sync token, so it is sent on neither read: an
    # incremental read that carried no deletions would leave a removed event in the plan forever.
    assert "showDeleted" not in asked
    assert transport.calls[0].token == ACCESS_TOKEN


async def test_an_incremental_read_sends_the_token_it_holds_and_no_window() -> None:
    reader, transport = client([ok(events_page())])

    await reader.list_events(CALENDAR_ID, sync_token=SYNC_TOKEN, window=WINDOW)

    asked = transport.calls[0].params
    assert asked["syncToken"] == SYNC_TOKEN
    # Google refuses these beside a sync token, so sending them would make every incremental read
    # an error rather than a read.
    assert "timeMin" not in asked
    assert "timeMax" not in asked


async def test_the_calendar_id_is_escaped_into_the_path() -> None:
    # A calendarId is an opaque provider string that reaches a URL path, and one with a slash would
    # otherwise address a different collection.
    reader, transport = client([ok(events_page())])

    await reader.list_events("a/b@group.calendar.google.com", sync_token=None, window=WINDOW)

    assert "a%2Fb%40group.calendar.google.com" in transport.calls[0].url


# --------------------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------------------


async def test_every_page_is_read_and_the_last_page_carries_the_token() -> None:
    reader, transport = client(
        [
            ok(events_page(event("one"), page_token="page-2")),
            ok(events_page(event("two"), sync_token=SYNC_TOKEN)),
        ]
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, EventsRead)
    assert [one.id for one in answer.events] == ["one", "two"]
    assert answer.sync_token == SYNC_TOKEN
    assert answer.attempts == 2
    assert transport.calls[1].params["pageToken"] == "page-2"


async def test_a_read_that_never_stops_paginating_is_cut_off_and_says_so() -> None:
    # A loop over a token the server keeps returning is an infinite loop, and a provider bug should
    # cost one source a stated failure rather than a worker tick that never ends.
    reader, _ = client([ok(events_page(event(), page_token="always-another"))])

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert f"{MAX_PAGES} pages" in answer.reason
    assert answer.attempts == MAX_PAGES


# --------------------------------------------------------------------------------------
# The detector read
# --------------------------------------------------------------------------------------


async def test_a_detector_read_stops_at_the_first_page_that_carries_a_change() -> None:
    # The caller only needs to know THAT something changed, so paging the rest is work nobody reads.
    reader, transport = client(
        [ok(events_page(event("changed"), page_token="more")), ok(events_page(event("also")))]
    )

    answer = await reader.list_events(
        CALENDAR_ID, sync_token=SYNC_TOKEN, window=WINDOW, stop_at_first_change=True
    )

    assert isinstance(answer, EventsRead)
    assert len(transport.calls) == 1
    assert [one.id for one in answer.events] == ["changed"]


async def test_a_detector_read_of_a_quiet_calendar_still_pages_to_its_token() -> None:
    # An empty page carries no change to stop on, so the token on the last page is still collected:
    # that token is what the next quiet poll spends.
    reader, transport = client(
        [ok(events_page(page_token="more")), ok(events_page(sync_token=SYNC_TOKEN))]
    )

    answer = await reader.list_events(
        CALENDAR_ID, sync_token=SYNC_TOKEN, window=WINDOW, stop_at_first_change=True
    )

    assert isinstance(answer, EventsRead)
    assert answer.events == ()
    assert answer.sync_token == SYNC_TOKEN
    assert len(transport.calls) == 2


async def test_a_delta_larger_than_the_page_bound_is_a_change_rather_than_a_failure() -> None:
    # THE bite for the stranding: without stopping early, a delta over 40 pages failed on the page
    # bound, `recorded_failure` retained the cursor, and every later poll re-paged the same delta
    # with the provider's own token expiry as the only escape.
    reader, transport = client([ok(events_page(event("one-of-many"), page_token="always-another"))])

    answer = await reader.list_events(
        CALENDAR_ID, sync_token=SYNC_TOKEN, window=WINDOW, stop_at_first_change=True
    )

    assert isinstance(answer, EventsRead)
    assert len(transport.calls) == 1


async def test_a_full_read_pages_to_the_end_even_when_the_first_page_carries_events() -> None:
    # The flag is the detector's, not the reader's: a full read whose first page had events and
    # stopped there would report a calendar as holding one page of it.
    reader, transport = client(
        [ok(events_page(event("one"), page_token="more")), ok(events_page(event("two")))]
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, EventsRead)
    assert [one.id for one in answer.events] == ["one", "two"]
    assert len(transport.calls) == 2


# --------------------------------------------------------------------------------------
# The sync token
# --------------------------------------------------------------------------------------


async def test_a_410_on_a_read_that_sent_a_token_is_an_invalidation() -> None:
    reader, _ = client([failed(410, error_body("fullSyncRequired", code=410))])

    answer = await reader.list_events(CALENDAR_ID, sync_token=SYNC_TOKEN, window=WINDOW)

    assert isinstance(answer, SyncTokenExpired)
    assert answer.attempts == 1


async def test_a_410_without_a_token_is_a_failure_rather_than_an_invalidation() -> None:
    # Nothing to invalidate, so reading it as one would loop a full read into another full read.
    reader, _ = client([failed(410, error_body("deleted", code=410))])

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        (f"{CURSOR_PREFIX}{SYNC_TOKEN}", SYNC_TOKEN),
        (None, None),
        ('etag:"w/123"', None),
        ("modified:Mon, 09 Feb 2026 09:00:00 GMT", None),
        (CURSOR_PREFIX, None),
    ],
    ids=["a sync token", "no cursor", "an ICS etag", "an ICS date", "a bare prefix"],
)
def test_a_cursor_reads_as_a_sync_token_only_when_it_is_one(
    cursor: str | None, expected: str | None
) -> None:
    # A cursor written by another provider's adapter reads as no token, so a source whose provider
    # changed reads fully once instead of sending Google an ETag.
    assert sync_token_of(cursor) == expected


def test_a_sync_token_the_column_can_hold_is_stored_with_its_prefix() -> None:
    assert bounded_cursor(SYNC_TOKEN) == f"{CURSOR_PREFIX}{SYNC_TOKEN}"


def test_a_sync_token_too_long_for_the_column_is_dropped_rather_than_truncated() -> None:
    # THE bite check for the defect the ICS reader paid for, one provider over: an oversize write
    # raises at the flush and rolls back the whole tenant's sync pass. Truncating is not an option
    # either, because a truncated token is not an older token: Google answers 410 to it forever.
    oversize = "x" * (CURSOR_MAX_LENGTH * 2)

    assert bounded_cursor(oversize) is None


def test_a_sync_token_exactly_at_the_bound_is_kept() -> None:
    # The bound is on the STORED value, prefix included, so the edge is worth stating.
    exact = "x" * (CURSOR_MAX_LENGTH - len(CURSOR_PREFIX))

    stored = bounded_cursor(exact)

    assert stored is not None
    assert len(stored) == CURSOR_MAX_LENGTH


# --------------------------------------------------------------------------------------
# Rate limits and retries
# --------------------------------------------------------------------------------------


async def test_a_rate_limited_read_backs_off_and_retries() -> None:
    waits: list[float] = []
    reader, _transport = client(
        [
            failed(429, error_body("rateLimitExceeded", code=429)),
            failed(429, error_body("rateLimitExceeded", code=429)),
            ok(events_page(event())),
        ],
        waits=waits,
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, EventsRead)
    assert answer.attempts == 3
    assert len(waits) == 2
    # Truncated exponential: each wait doubles, and every one carries jitter, so no two clients
    # retry in step.
    assert waits[0] < waits[1]
    assert all(0 < wait <= MAX_BACKOFF_SECONDS + MAX_JITTER_SECONDS for wait in waits)


async def test_a_sustained_rate_limit_stops_at_the_attempt_bound_and_is_reported() -> None:
    waits: list[float] = []
    reader, _ = client([failed(429, error_body("userRateLimitExceeded", code=429))], waits=waits)

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert answer.rate_limited is True
    assert answer.attempts == MAX_ATTEMPTS
    assert len(waits) == MAX_ATTEMPTS - 1


async def test_a_403_naming_a_rate_limit_is_retried() -> None:
    reader, _ = client([failed(403, error_body("rateLimitExceeded")), ok(events_page(event()))])

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, EventsRead)


async def test_a_403_naming_an_insufficient_grant_is_not_retried() -> None:
    # The distinction the status alone cannot make: one waits, the other reconnects, and retrying a
    # scope problem four times tells the user their calendar is rate limited.
    waits: list[float] = []
    reader, _ = client([failed(403, error_body("insufficientPermissions"))], waits=waits)

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert answer.rate_limited is False
    assert answer.attempts == 1
    assert waits == []
    assert "refused access to this calendar" in answer.reason


async def test_a_retry_after_the_provider_stated_is_honoured_up_to_a_ceiling() -> None:
    waits: list[float] = []
    reader, _ = client(
        [
            failed(429, error_body("rateLimitExceeded", code=429), **{"Retry-After": "7"}),
            ok(events_page(event())),
        ],
        waits=waits,
    )

    await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert waits == [7.0]


async def test_a_retry_after_longer_than_a_poll_interval_is_capped() -> None:
    waits: list[float] = []
    reader, _ = client(
        [
            failed(503, error_body("backendError", code=503), **{"Retry-After": "600"}),
            ok(events_page(event())),
        ],
        waits=waits,
    )

    await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert waits == [MAX_HONOURED_RETRY_AFTER_SECONDS]


@pytest.mark.parametrize(
    "stated",
    ["Mon, 09 Feb 2026 09:00:30 GMT", "soon", "", "-5", "nan"],
    ids=["an http date", "words", "empty", "negative", "not a number"],
)
def test_a_retry_after_syncr_cannot_read_falls_back_to_the_schedule(stated: str) -> None:
    # The bite check behind this site's row in the construction sweep: `float()` on a provider's
    # header must not raise, and an unreadable value must not become no wait at all.
    assert stated_retry_after({"Retry-After": stated}) is None


def test_a_retry_after_of_zero_is_read_as_zero_rather_than_as_absent() -> None:
    assert stated_retry_after({"Retry-After": "0"}) == 0.0


async def test_a_rate_limit_on_a_later_page_gets_the_same_retries_as_the_first() -> None:
    # The budget is per REQUEST. Shared with pagination, a rate limit on page four got zero retries
    # while page one got four, which is not what either docstring described.
    waits: list[float] = []
    reader, _transport = client(
        [
            ok(events_page(event("p1"), page_token="p2")),
            ok(events_page(event("p2"), page_token="p3")),
            ok(events_page(event("p3"), page_token="p4")),
            failed(429, error_body("rateLimitExceeded", code=429)),
            failed(429, error_body("rateLimitExceeded", code=429)),
            ok(events_page(event("p4"))),
        ],
        waits=waits,
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, EventsRead)
    assert [one.id for one in answer.events] == ["p1", "p2", "p3", "p4"]
    # Three pages, two refusals, two waits, and the read still completed.
    assert len(waits) == 2


async def test_the_attempt_count_still_reports_every_call_the_read_made() -> None:
    # The per-request budget must not shrink what the SOURCE reports: a read that took six calls is
    # a different story from one that took one, and that is what reaches the panel.
    reader, _transport = client(
        [
            ok(events_page(event("p1"), page_token="p2")),
            failed(503),
            ok(events_page(event("p2"))),
        ]
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, EventsRead)
    assert answer.attempts == 3


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_a_server_error_is_retried(status: int) -> None:
    reader, _ = client([failed(status), ok(events_page(event()))])

    assert isinstance(
        await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW), EventsRead
    )


async def test_a_transport_failure_is_retried_and_then_reported() -> None:
    transport = RecordedGoogle(answers=[ok(events_page())])
    transport.raises = httpx.ConnectError("no route")
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    reader = GoogleCalendarClient(
        transport=transport,
        tokens=FixedTokens(),
        backoff=BackoffPolicy(random=Random(1)),  # noqa: S311 - jitter, not a key
        sleep=sleep,
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert "ConnectError" in answer.reason
    assert answer.attempts == MAX_ATTEMPTS


# --------------------------------------------------------------------------------------
# The deadline
# --------------------------------------------------------------------------------------


async def test_the_deadline_covers_the_whole_read_rather_than_one_request() -> None:
    # The defect this shape exists to avoid: a host that answers every page slowly passes any
    # per-request timeout while the read runs forever. Every page here answers well inside a
    # plausible per-request timeout, and the read is still stopped, which is the distinction.
    #
    # The margin between the two is 20x rather than a few multiples, deliberately. This is the one
    # assertion in the file that depends on WALL CLOCK: it claims several pages arrived before the
    # deadline, and on a contended machine a narrow margin makes that claim fail for load rather
    # than for behaviour. A whole-member run of this suite was measured between 201 and 294 seconds
    # on the same tree, so the contention is real and the margin has to absorb it.
    #
    # The page bound sets the other side of the window: 40 pages have to outlast the deadline or the
    # read ends by the wrong bound and the test passes for the wrong reason, which is exactly what a
    # smaller per-page wait produced when this was first widened. So the wait is a twentieth of the
    # deadline, and forty of them are twice it.
    deadline = 0.5
    per_page = deadline / 20

    class _Slow:
        def __init__(self) -> None:
            self.calls = 0

        async def get(self, url: str, *, params: object, token: str) -> GoogleResponse:
            self.calls += 1
            await asyncio.sleep(per_page)
            return ok(events_page(event(), page_token="another"))

    transport = _Slow()
    reader = GoogleCalendarClient(
        transport=transport,
        tokens=FixedTokens(),
        deadline_seconds=deadline,
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert "did not answer this read within" in answer.reason
    # Several pages arrived, each of them promptly, and the read still ended: bounded by the
    # deadline rather than by the page bound.
    assert 1 < transport.calls < MAX_PAGES
    # And the two properties that make this test about the WHOLE read rather than one slow request:
    # no single request came close to the deadline, and the page bound could not have ended it.
    assert per_page * 10 < deadline
    assert per_page * MAX_PAGES > deadline


async def test_the_deadline_also_bounds_a_read_that_hangs_on_its_first_request() -> None:
    async def never_answers(url: str, *, params: object, token: str) -> GoogleResponse:
        await asyncio.sleep(60)
        raise AssertionError("unreachable: the deadline stops this read")

    class _Hung:
        get = staticmethod(never_answers)

    reader = GoogleCalendarClient(
        transport=_Hung(),
        tokens=FixedTokens(),
        deadline_seconds=0.05,
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert answer.attempts == 1


async def test_the_backoff_waits_count_against_the_read_deadline() -> None:
    # A read that retried for longer than the deadline would hold a worker tick doing work the next
    # tick redoes, so the waits are inside the budget rather than beside it.
    async def slow_sleep(seconds: float) -> None:
        await asyncio.sleep(0.05)

    reader = GoogleCalendarClient(
        transport=RecordedGoogle(answers=[failed(503)]),
        tokens=FixedTokens(),
        backoff=BackoffPolicy(random=Random(1)),  # noqa: S311 - jitter, not a key
        sleep=slow_sleep,
        deadline_seconds=0.06,
    )

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert "did not answer this read within" in answer.reason


# --------------------------------------------------------------------------------------
# Bodies, and what the boundary refuses
# --------------------------------------------------------------------------------------


async def test_a_page_larger_than_the_bound_is_refused_rather_than_parsed() -> None:
    reader, _ = client([GoogleResponse(status=200, body=None)])

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert f"{MAX_PAGE_BYTES // (1024 * 1024)}MB" in answer.reason


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b'{"items": "not a list"}', b'{"items": [{"summary": "no id"}]}'],
    ids=["not json", "an array", "items is not a list", "an item with no identifier"],
)
async def test_a_body_that_does_not_match_the_contract_is_refused(body: bytes) -> None:
    # A provider contract can change under you, so the shape is declared and a mismatch is a stated
    # failure at the boundary rather than an AttributeError three layers into placement.
    reader, _ = client([ok(body)])

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert "cannot read" in answer.reason


async def test_an_unknown_field_on_an_event_does_not_break_the_read() -> None:
    reader, _ = client([ok(b'{"items": [{"id": "x", "eventType": "birthday", "newThing": 1}]}')])

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, EventsRead)
    assert [one.id for one in answer.events] == ["x"]


# --------------------------------------------------------------------------------------
# No token to read with
# --------------------------------------------------------------------------------------


async def test_no_connected_account_is_reported_without_a_call() -> None:
    tokens = FixedTokens(answer=NoGoogleAccount())
    reader, transport = client([ok(events_page())], tokens=tokens)

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert "not connected" in answer.reason
    assert transport.calls == []


async def test_a_dead_grant_is_reported_with_the_reason_the_token_layer_gave() -> None:
    tokens = FixedTokens(answer=GoogleGrantDead("the authorization was revoked"))
    reader, _ = client([ok(events_page())], tokens=tokens)

    answer = await reader.list_events(CALENDAR_ID, sync_token=None, window=WINDOW)

    assert isinstance(answer, GoogleReadFailed)
    assert answer.reason == "the authorization was revoked"


# --------------------------------------------------------------------------------------
# The calendar list
# --------------------------------------------------------------------------------------


async def test_the_calendar_list_reads_every_page_and_names_what_can_be_written() -> None:
    reader, _ = client(
        [
            ok(calendar_list_page(calendar("primary", primary=True), page_token="next")),
            ok(calendar_list_page(calendar("holidays", access_role="reader"))),
        ]
    )

    answer = await reader.list_calendars()

    assert isinstance(answer, CalendarsRead)
    assert [(one.calendar_id, one.writable, one.primary) for one in answer.calendars] == [
        ("primary", True, True),
        ("holidays", False, False),
    ]


async def test_a_calendar_the_account_removed_is_not_offered() -> None:
    reader, _ = client([ok(calendar_list_page(calendar("gone", deleted=True), calendar("kept")))])

    answer = await reader.list_calendars()

    assert isinstance(answer, CalendarsRead)
    assert [one.calendar_id for one in answer.calendars] == ["kept"]


async def test_a_calendar_with_no_title_reads_back_as_its_identifier() -> None:
    # A blank row in a selection list is not a choice, and the identifier is an address the user can
    # recognise.
    reader, _ = client([ok(calendar_list_page(calendar("team@group.calendar", summary=None)))])

    answer = await reader.list_calendars()

    assert isinstance(answer, CalendarsRead)
    assert answer.calendars[0].display_name == "team@group.calendar"


# --------------------------------------------------------------------------------------
# The transport itself
# --------------------------------------------------------------------------------------


async def test_the_transport_presents_the_bearer_token_and_bounds_the_body() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, content=b'{"items": []}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        answer = await HttpxGoogleTransport(http).get(
            "https://example.test/events", params={"a": "b"}, token=ACCESS_TOKEN
        )

    assert answer.status == 200
    assert answer.body == b'{"items": []}'
    assert seen["authorization"] == f"Bearer {ACCESS_TOKEN}"


async def test_the_transport_reports_an_oversize_body_as_no_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_PAGE_BYTES + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        answer = await HttpxGoogleTransport(http).get(
            "https://example.test/events", params={}, token=ACCESS_TOKEN
        )

    assert answer.body is None
