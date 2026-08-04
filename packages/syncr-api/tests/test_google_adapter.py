"""The Google adapter's contract: two answers, three sync states, and no raised exception.

The transport is faked and everything below the adapter is real: the client, the backoff, the
payload validation, the value parsing, the horizon clip, and the sync-state arithmetic.

What is asserted here is the arithmetic that decides whether a stale calendar is visible, and the
one design decision this ticket made that a reader will want to check: **the sync token is a change
detector, and the read that follows it is a full one.** An incremental answer is a delta, and the
reconciler removes anchors the events do not mention, so handing it a delta would delete every
commitment the provider did not happen to change. A poll that finds no change costs one small
request, which is the saving the token exists for; a poll that finds one costs a second request and
returns the calendar.

The other claims worth naming: a failure keeps everything the source already had, a rate limit says
when syncr will try again, an unstorable token says why the next read is full, and no line this
module writes carries a title or a token.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.config import (
    ANCHOR_SOURCE,
    CURSOR_MAX_LENGTH,
    GOOGLE,
    GOOGLE_COMPONENT,
    MALFORMED_VALUE,
    MISSING_DURATION,
    SYNC_INTERVAL,
    UNKNOWN_LINE,
)
from syncr_api.calendars.google_adapter import (
    CHANGES_DETECTED,
    CURSOR_INVALIDATED,
    CURSOR_UNSTORABLE,
    GoogleAdapter,
)
from syncr_api.calendars.google_backoff import BackoffPolicy
from syncr_api.calendars.google_client import CalendarsRead, GoogleCalendarClient, GoogleReadFailed
from syncr_api.calendars.google_cursors import CURSOR_PREFIX
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.sync_state import RETAINED_NOTICE
from syncr_api.google_account.tokens import NoGoogleAccount
from syncr_common.logging import configure_logging
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.fake_google import (
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
    from collections.abc import Iterator, Sequence

    from syncr_api.calendars.google_transport import GoogleResponse

LONDON = ZoneProfile(home_zone="Europe/London")
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=6)
HORIZON = Interval(NOW, NOW + timedelta(days=14))
NEXT_TOKEN = "CNEXT-token"  # pragma: allowlist secret


def one_line(stream: io.StringIO, event: str) -> dict[str, object]:
    """The one rendered line carrying ``event``, as the fields it bound."""
    found = [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if line.startswith("{") and json.loads(line).get("event") == event
    ]
    assert len(found) == 1, f"expected exactly one {event!r} line, got {len(found)}"
    return dict(found[0])


@pytest.fixture
def rendered_lines() -> Iterator[io.StringIO]:
    """Render every log line to a captured stream, then hand the configuration back.

    structlog holds the stream it was configured with, so `capsys` sees nothing: what a line
    actually carries can only be read by configuring the renderer at a stream of one's own. The
    configuration is process-global, so it is restored on teardown.
    """
    stream = io.StringIO()
    configure_logging(environment="production", log_level="info", stream=stream)
    yield stream
    configure_logging(environment="test", log_level="info")


def source(**overrides: object) -> CalendarSourceRecord:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "provider": GOOGLE,
        "role": ANCHOR_SOURCE,
        "display_name": "Personal",
        "external_id": "primary",
        "included": True,
        "horizon_days": None,
        "sync_state": SyncStateRecord(),
    }
    return CalendarSourceRecord(**{**defaults, **overrides})  # type: ignore[arg-type]


def synced(anchors: int = 12, **overrides: object) -> SyncStateRecord:
    """A source that last succeeded six hours ago, which is what a retention claim needs."""
    defaults: dict[str, object] = {
        "last_success_at": EARLIER,
        "last_attempt_at": EARLIER,
        "cursor": f"{CURSOR_PREFIX}{SYNC_TOKEN}",
        "events_read": 30,
        "anchors_current": anchors,
        "attempts": 1,
    }
    return SyncStateRecord(**{**defaults, **overrides})  # type: ignore[arg-type]


def adapter(answers: Sequence[GoogleResponse]) -> tuple[GoogleAdapter, RecordedGoogle]:
    transport = RecordedGoogle(answers=answers)

    async def sleep(_seconds: float) -> None:
        return None

    client = GoogleCalendarClient(
        transport=transport, tokens=FixedTokens(), backoff=BackoffPolicy(), sleep=sleep
    )
    return (
        GoogleAdapter(client=client, profile=LONDON, horizon=HORIZON, clock=lambda: NOW),
        transport,
    )


# --------------------------------------------------------------------------------------
# A full read
# --------------------------------------------------------------------------------------


async def test_a_first_read_places_the_calendar_and_records_a_success() -> None:
    google, transport = adapter([ok(events_page(event("one"), event("two")))])

    outcome, state = await google.fetch(source())

    assert outcome.reparsed is True
    assert len(outcome.events) == 2
    assert outcome.events_read == 2
    assert outcome.placed == 2
    assert state.last_success_at == NOW
    assert state.last_attempt_at == NOW
    assert state.last_error is None
    assert state.cursor == f"{CURSOR_PREFIX}{SYNC_TOKEN}"
    assert state.anchors_current == 2
    assert state.attempts == 1
    assert state.resync_reason is None
    # No cursor held, so nothing incremental was asked for.
    assert "syncToken" not in transport.calls[0].params


async def test_an_event_carries_its_provider_identity_and_its_series() -> None:
    google, _ = adapter(
        [
            ok(
                events_page(
                    event(
                        "evt_20260209T090000Z",
                        recurring_event_id="series-1",
                        location="Room 4",
                        sequence=3,
                        transparency="transparent",
                    )
                )
            )
        ]
    )

    outcome, _state = await google.fetch(source())

    placed = outcome.events[0]
    # The instance id, which Google keeps when an instance is moved: that is the identity rule the
    # ICS path derives by hand, maintained by the provider here.
    assert placed.uid == "evt_20260209T090000Z"
    assert placed.series_uid == "series-1"
    assert placed.location == "Room 4"
    assert placed.sequence == 3
    assert placed.transparent is True
    assert placed.all_day is False


async def test_an_all_day_event_occupies_whole_local_days() -> None:
    google, _ = adapter(
        [ok(events_page(event("day", date_start="2026-02-10", date_end="2026-02-11")))]
    )

    outcome, _state = await google.fetch(source())

    assert outcome.events[0].all_day is True
    assert outcome.events[0].interval.duration == timedelta(hours=24)


async def test_an_event_outside_the_horizon_is_counted_rather_than_placed() -> None:
    # Not a loss and not an error, but counted: otherwise it is indistinguishable from occupancy
    # that vanished.
    google, _ = adapter(
        [
            ok(
                events_page(
                    event("inside", start="2026-02-10T09:00:00Z", end="2026-02-10T10:00:00Z"),
                    event("outside", start="2027-02-10T09:00:00Z", end="2027-02-10T10:00:00Z"),
                )
            )
        ]
    )

    outcome, state = await google.fetch(source())

    assert [one.uid for one in outcome.events] == ["inside"]
    assert outcome.unplaced == 1
    assert outcome.events_read == 2
    assert state.anchors_current == 1


async def test_an_unreadable_event_is_rejected_with_a_reason_and_the_rest_are_kept() -> None:
    # A calendar that half-works must read as neither fully working nor fully broken.
    google, _ = adapter(
        [ok(events_page(event("good"), event("bad", start="2026-02-10T09:00:00", end=None)))]
    )

    outcome, state = await google.fetch(source())

    assert [one.uid for one in outcome.events] == ["good"]
    assert len(outcome.rejected) == 1
    rejected = outcome.rejected[0]
    assert rejected.kind in {MALFORMED_VALUE, MISSING_DURATION}
    assert rejected.component == GOOGLE_COMPONENT
    assert rejected.line == UNKNOWN_LINE
    assert rejected.uid == "bad"
    # A rejection is not a failure: the attempt succeeded and the rejections travel with it.
    assert state.last_error is None
    assert state.rejections == outcome.rejected


async def test_a_rejection_states_the_reason_without_quoting_a_title() -> None:
    google, _ = adapter(
        [ok(events_page(event("bad", summary="Kontron Placement Interview", start=None, end=None)))]
    )

    outcome, _state = await google.fetch(source())

    assert "Kontron" not in outcome.rejected[0].detail


async def test_a_cancelled_event_in_a_full_read_is_counted_rather_than_placed() -> None:
    # A full read asks for no deleted events, so this is a provider answering with one anyway.
    google, _ = adapter([ok(events_page(event("gone", status="cancelled", start=None, end=None)))])

    outcome, _state = await google.fetch(source())

    assert outcome.events == ()
    assert outcome.cancelled_discarded == 1
    assert outcome.rejected == ()


# --------------------------------------------------------------------------------------
# The sync token as a change detector
# --------------------------------------------------------------------------------------


async def test_a_poll_that_finds_no_change_costs_one_request_and_reparses_nothing() -> None:
    google, transport = adapter([ok(events_page(sync_token=NEXT_TOKEN))])

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 1
    assert transport.calls[0].params["syncToken"] == SYNC_TOKEN
    # The same shape an ICS 304 produces: a success that read nothing, so the caller keeps what it
    # holds rather than removing it.
    assert outcome.reparsed is False
    assert outcome.events == ()
    assert state.last_success_at == NOW
    assert state.last_error is None
    assert state.anchors_current == 12
    assert state.events_read == 30
    # The fresh token replaces the one that produced the match.
    assert state.cursor == f"{CURSOR_PREFIX}{NEXT_TOKEN}"


async def test_a_poll_that_finds_a_change_reads_the_calendar_in_full() -> None:
    # THE design decision. The delta says what changed; the full read says what the calendar is, and
    # only the second is safe to reconcile against.
    google, transport = adapter(
        [
            ok(events_page(event("changed"), sync_token=NEXT_TOKEN)),
            ok(events_page(event("a"), event("b"))),
        ]
    )

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 2
    assert transport.calls[0].params["syncToken"] == SYNC_TOKEN
    assert "syncToken" not in transport.calls[1].params
    assert transport.calls[1].params["timeMin"] == HORIZON.start.isoformat()
    assert outcome.reparsed is True
    assert [one.uid for one in outcome.events] == ["a", "b"]
    assert state.anchors_current == 2
    assert state.resync_reason == CHANGES_DETECTED
    # Both requests are counted, because the count on the source is what the poll cost.
    assert state.attempts == 2


async def test_a_change_bigger_than_the_page_bound_is_read_fully_rather_than_stranding() -> None:
    # The detector stops on the first page that carries an entry, so a delta of any size costs one
    # page and becomes a full read. Before that, such a delta failed on the page bound with the
    # cursor retained, and every later poll re-paged it: the source could only escape when Google
    # expired the token itself.
    google, transport = adapter(
        [
            ok(events_page(event("one-of-many"), page_token="always-another")),
            ok(events_page(event("a"), event("b"))),
        ]
    )

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 2
    assert outcome.reparsed is True
    assert state.last_error is None
    assert state.resync_reason == CHANGES_DETECTED
    assert state.cursor == f"{CURSOR_PREFIX}{SYNC_TOKEN}"


async def test_an_invalidated_token_falls_back_to_a_full_read_and_records_why() -> None:
    google, transport = adapter(
        [failed(410, error_body("fullSyncRequired", code=410)), ok(events_page(event("a")))]
    )

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 2
    assert outcome.reparsed is True
    assert state.resync_reason == CURSOR_INVALIDATED
    assert state.last_error is None
    assert state.attempts == 2


async def test_a_failure_after_an_invalidation_still_records_the_attempt() -> None:
    google, _ = adapter(
        [
            failed(410, error_body("fullSyncRequired", code=410)),
            failed(404, error_body("notFound", code=404)),
        ]
    )

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert outcome.events == ()
    assert state.last_error is not None
    assert "no longer holds this calendar" in state.last_error
    # The invalidation's attempt plus the failed read's.
    assert state.attempts == 2


async def test_a_token_too_long_to_store_is_dropped_and_the_state_says_why() -> None:
    # Dropping costs one full read on the next poll. Storing it would raise at the flush and roll
    # back the whole tenant's sync pass, which is a failure attributable to no source at all.
    oversize = "x" * (CURSOR_MAX_LENGTH * 2)
    google, _ = adapter([ok(events_page(event("a"), sync_token=oversize))])

    _outcome, state = await google.fetch(source())

    assert state.cursor is None
    assert state.resync_reason == CURSOR_UNSTORABLE


async def test_an_unstorable_token_on_the_unchanged_path_keeps_the_cursor_that_worked() -> None:
    # A 304-shaped answer whose fresh token will not fit: the held token still matches, so keeping
    # it costs nothing and dropping it would force a full read for no reason.
    oversize = "x" * (CURSOR_MAX_LENGTH * 2)
    google, _ = adapter([ok(events_page(sync_token=oversize))])
    held = synced()

    _outcome, state = await google.fetch(source(sync_state=held))

    assert state.cursor == held.cursor


async def test_a_cursor_written_by_another_provider_is_not_sent_as_a_sync_token() -> None:
    google, transport = adapter([ok(events_page(event("a")))])

    await google.fetch(source(sync_state=synced(cursor='etag:"w/123"')))

    assert "syncToken" not in transport.calls[0].params


# --------------------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------------------


async def test_a_failed_read_retains_the_anchors_the_cursor_and_the_last_success() -> None:
    google, _ = adapter([failed(500)])
    held = synced()

    outcome, state = await google.fetch(source(sync_state=held))

    assert outcome.events == ()
    assert outcome.reparsed is False
    assert state.last_attempt_at == NOW
    assert state.last_success_at == EARLIER
    assert state.anchors_current == held.anchors_current
    assert state.events_read == held.events_read
    assert state.cursor == held.cursor
    assert state.last_error is not None
    assert RETAINED_NOTICE in state.last_error


async def test_a_rate_limited_read_states_that_it_backed_off_and_when_it_will_try_again() -> None:
    google, _ = adapter([failed(429, error_body("rateLimitExceeded", code=429))])

    _outcome, state = await google.fetch(source(sync_state=synced()))

    assert state.last_error is not None
    assert "rate limiting" in state.last_error
    assert "backing off" in state.last_error
    assert (NOW + SYNC_INTERVAL).strftime("%H:%M") in state.last_error
    # The attempt count is what makes a backed-off read visible instead of looking slow.
    assert state.attempts > 1


async def test_a_read_with_no_connected_account_says_so_and_names_what_still_works() -> None:
    google = GoogleAdapter(
        client=GoogleCalendarClient(
            transport=RecordedGoogle(answers=[ok(events_page())]),
            tokens=FixedTokens(answer=NoGoogleAccount()),
        ),
        profile=LONDON,
        horizon=HORIZON,
        clock=lambda: NOW,
    )

    _outcome, state = await google.fetch(source())

    assert state.last_error is not None
    assert "not connected to a Google account" in state.last_error
    assert "ICS feed still syncs" in state.last_error


@pytest.mark.parametrize(
    "answer",
    [
        failed(401),
        failed(403, error_body("insufficientPermissions")),
        failed(404, error_body("notFound", code=404)),
        failed(400, error_body("badRequest", code=400)),
        ok(b"not json"),
    ],
    ids=["unauthorized", "forbidden", "gone", "bad request", "unreadable body"],
)
async def test_no_failure_raises_out_of_a_fetch(answer: GoogleResponse) -> None:
    # A worker tick polling five calendars must not lose four because one calendar is gone.
    google, _ = adapter([answer])

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert outcome.events == ()
    assert state.last_error is not None
    assert state.last_attempt_at == NOW


# --------------------------------------------------------------------------------------
# The other two methods
# --------------------------------------------------------------------------------------


async def test_listing_calendars_answers_with_the_failure_rather_than_raising() -> None:
    google, _ = adapter([failed(403, error_body("insufficientPermissions"))])

    answer = await google.list_calendars()

    assert isinstance(answer, GoogleReadFailed)


async def test_listing_calendars_names_each_one_and_whether_it_can_be_written() -> None:
    google, _ = adapter(
        [ok(calendar_list_page(calendar("primary", summary="Personal", primary=True)))]
    )

    answer = await google.list_calendars()

    assert isinstance(answer, CalendarsRead)
    assert answer.calendars[0].display_name == "Personal"
    assert answer.calendars[0].writable is True


async def test_reconcile_refuses_by_name_and_states_what_still_works() -> None:
    # The interface is complete from this module so ticket 30 changes one method body: a caller
    # written against it today compiles, and what it gets is a refusal that says why.
    google, _ = adapter([ok(events_page())])

    with pytest.raises(NotImplementedError, match="not implemented yet"):
        await google.reconcile(source(display_name="syncr (dev)"), [])


# --------------------------------------------------------------------------------------
# What reaches a log line
# --------------------------------------------------------------------------------------


async def test_no_title_and_no_token_reaches_a_log_line(rendered_lines: io.StringIO) -> None:
    # Every block title is sensitive: `Kontron Placement Interview` discloses a job search to
    # anyone with log access, and a location discloses where the user physically is at a given hour.
    google, _ = adapter(
        [
            ok(
                events_page(
                    event(
                        "evt",
                        summary="Kontron Placement Interview",
                        location="Kontron, Reading",
                    ),
                    sync_token=SYNC_TOKEN,
                )
            )
        ]
    )

    await google.fetch(source(display_name="Personal"))

    written = rendered_lines.getvalue()
    assert "calendars.google.read" in written
    assert "Kontron" not in written
    assert "Reading" not in written
    assert SYNC_TOKEN not in written
    assert "ya29." not in written


async def test_a_failed_read_logs_counts_rather_than_a_provider_message(
    rendered_lines: io.StringIO,
) -> None:
    # The rule this test is named for was defended by nothing: adding `provider_message=reason` to
    # the failure line left it passing. So the KEY SET is asserted exactly. Any field added to that
    # line fails here, whether it carries a provider's prose, a title, or a token, and the assertion
    # cannot be satisfied by a line that merely mentions the right words.
    google, _ = adapter([failed(429, error_body("rateLimitExceeded", code=429))])

    await google.fetch(source(sync_state=synced()))

    line = one_line(rendered_lines, "calendars.google.unreachable")
    assert set(line) == {
        "event",
        "level",
        "timestamp",
        "service",
        "source_id",
        "tenant_id",
        "attempt_count",
        "rate_limited",
        "anchors_retained",
    }


async def test_no_provider_authored_text_reaches_the_failure_line(
    rendered_lines: io.StringIO,
) -> None:
    # `GoogleReadFailed.reason` interpolates a provider-controlled string on some paths, and it is
    # the sentence the PANEL renders rather than one a log line should carry. Both the reason syncr
    # composed and the prose Google sent are asserted absent.
    prose = "PROVIDER-PROSE-DO-NOT-LOG"
    google, _ = adapter([failed(403, error_body("insufficientPermissions", message=prose))])

    _outcome, state = await google.fetch(source(sync_state=synced()))

    written = rendered_lines.getvalue()
    assert prose not in written
    assert state.last_error is not None
    # The panel's own sentence is not a log field either: the line carries identifiers and counts.
    assert "refused access to this calendar" not in written


async def test_an_excluded_source_is_not_this_modules_decision() -> None:
    # Stated as a test because it is a boundary rather than an omission: the syncer does not call
    # the adapter for an excluded source, and an adapter that skipped one itself would make the
    # excluded state something two modules decide.
    google, transport = adapter([ok(events_page(event("a")))])

    await google.fetch(replace(source(), included=False))

    assert len(transport.calls) == 1
