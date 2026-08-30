"""The Google adapter's contract: two answers, three sync states, and no raised exception.

The transport is faked and everything below the adapter is real: the client, the backoff, the
payload validation, the value parsing, the horizon clip, and the sync-state arithmetic.

What is asserted here is the arithmetic that decides whether a stale calendar is visible, and the
design decision a reader will want to check: **a delta is applied as what it is, a list of
changes.** An incremental answer is not the calendar; handing it to a reconciler that removes what
it was not told about would delete every commitment the provider did not happen to change. So the
delta keeps its own shape all the way to the anchor writer: its events are created and updated
exactly as a full read's are, its removals travel as the identifiers the provider named, and a poll
that reports nothing changed is answered exactly as an ICS 304 is. The token buys the poll that
costs one small request instead of a fortnight of events, and no longer costs a second request on
a poll that found a change.

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
    CURSOR_INVALIDATED,
    CURSOR_UNSTORABLE,
    DELTA_OVER_MAX_PAGES,
    GoogleAdapter,
)
from syncr_api.calendars.google_backoff import BackoffPolicy
from syncr_api.calendars.google_client import CalendarsRead, GoogleCalendarClient, GoogleReadFailed
from syncr_api.calendars.google_config import MAX_PAGES
from syncr_api.calendars.google_cursors import CURSOR_PREFIX
from syncr_api.calendars.injection import READS_ONLY
from syncr_api.calendars.projection_errors import ProjectionRefused
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
        "created_at": NOW - timedelta(days=30),
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
        GoogleAdapter(
            client=client,
            profile=LONDON,
            horizon=HORIZON,
            clock=lambda: NOW,
            # The read side under test here holds the refusing arm of the write seam, which is what
            # the request composition passes: the reconciliation is the projection suite's.
            writes=READS_ONLY,
        ),
        transport,
    )


# --------------------------------------------------------------------------------------
# A full read
# --------------------------------------------------------------------------------------


async def test_a_first_read_places_the_calendar_and_records_a_success() -> None:
    google, transport = adapter([ok(events_page(event("one"), event("two")))])

    outcome, state = await google.fetch(source())

    # One request, because a read of the calendar is not followed by another one: the answer that
    # lists the calendar IS the calendar, and only an answer that lists changes needs a second read.
    assert len(transport.calls) == 1
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


async def test_a_full_read_is_not_a_delta_and_reports_no_removed_identifier() -> None:
    # The other half of the pair below: a read of the calendar states what is there, and absence is
    # what removes everything else, so it has no removal to name and is not a list of changes.
    google, _ = adapter([ok(events_page(event("one"), event("two")))])

    outcome, _state = await google.fetch(source())

    assert outcome.incremental is False
    assert outcome.removed_uids == ()


async def test_a_full_read_names_no_removal_even_when_the_provider_volunteers_one() -> None:
    # The emptiness has to survive the case that could fill it. A full read asks for no deleted
    # events and gets them anyway, and naming those identifiers would leave one outcome carrying two
    # removal rules: everything absent from it, plus a list. Absence already covers both.
    google, _ = adapter(
        [
            ok(
                events_page(
                    event("kept"),
                    event("gone-1", status="cancelled", start=None, end=None),
                    event("gone-2", status="cancelled", start=None, end=None),
                )
            )
        ]
    )

    outcome, _state = await google.fetch(source())

    assert outcome.removed_uids == ()
    # Counted, and by a figure that is neither the event count nor one.
    assert outcome.cancelled_discarded == 2
    assert [one.uid for one in outcome.events] == ["kept"]


# --------------------------------------------------------------------------------------
# A change-bearing delta is the attempt's answer
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


async def test_a_poll_that_finds_a_change_applies_the_delta_rather_than_reading_fully() -> None:
    # THE design decision, inverted from what it was: the delta says what changed, and applying it
    # IS the poll. A second read of the whole calendar would spend a fortnight of events to learn
    # nothing the delta had not already said.
    google, transport = adapter(
        [
            ok(
                events_page(
                    event("moved", start="2026-02-11T09:00:00Z", end="2026-02-11T10:00:00Z"),
                    sync_token=NEXT_TOKEN,
                )
            )
        ]
    )

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 1
    assert transport.calls[0].params["syncToken"] == SYNC_TOKEN
    assert outcome.incremental is True
    assert outcome.reparsed is True
    assert [one.uid for one in outcome.events] == ["moved"]
    assert outcome.removed_uids == ()
    assert state.last_success_at == NOW
    assert state.last_error is None
    assert state.anchors_current == 1
    assert state.attempts == 1
    assert state.resync_reason is None
    # The fresh token replaces the one that produced the delta.
    assert state.cursor == f"{CURSOR_PREFIX}{NEXT_TOKEN}"


async def test_a_delta_wider_than_one_page_is_paged_to_its_end_and_applied_whole() -> None:
    # Every entry of a delta is a change to make, so an early stop would apply part of one and keep
    # a cursor that skips the rest.
    google, transport = adapter(
        [
            ok(events_page(event("p1"), page_token="more")),
            ok(events_page(event("p2"), sync_token=NEXT_TOKEN)),
        ]
    )

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 2
    assert [one.uid for one in outcome.events] == ["p1", "p2"]
    assert outcome.reparsed is True
    assert state.cursor == f"{CURSOR_PREFIX}{NEXT_TOKEN}"
    assert state.attempts == 2


async def test_an_incremental_read_carries_the_delta_and_the_identifiers_it_removed() -> None:
    # What a read that asked "what changed" produces, which is a different value from a read of the
    # calendar: two entries changed, three are gone, and one syncr cannot read. The removals are the
    # half that has nowhere else to travel, because a list of changes cannot express one by absence.
    google, transport = adapter(
        [
            ok(
                events_page(
                    event("moved", start="2026-02-11T09:00:00Z", end="2026-02-11T10:00:00Z"),
                    event("gone-1", status="cancelled", start=None, end=None),
                    event("added"),
                    event("gone-2", status="cancelled", start=None, end=None),
                    event("unreadable", start="2026-02-10T09:00:00", end=None),
                    event("gone-3", status="cancelled", start=None, end=None),
                )
            )
        ]
    )

    outcome, _state = await google.read_changes(
        source(sync_state=synced()), since=SYNC_TOKEN, at=NOW
    )

    assert transport.calls[0].params["syncToken"] == SYNC_TOKEN
    assert outcome.incremental is True
    # In the order the provider stated them, and distinct from the entries that changed: a count
    # alone could not tell the two sets apart, and neither set has one member.
    assert outcome.removed_uids == ("gone-1", "gone-2", "gone-3")
    assert [one.uid for one in outcome.events] == ["moved", "added"]
    assert [one.uid for one in outcome.rejected] == ["unreadable"]
    # Every entry the provider offered is accounted for by exactly one term, so a removal cannot be
    # a component that vanished with no explanation anywhere. The refusals enter as their count
    # rather than as the sample, because the sample is bounded per kind and the count is what the
    # accounting closes over.
    assert outcome.events_read == 6
    # The identity the class documents, over the terms it names. A removal is a component a
    # cancellation discarded, so it closes here as well as in the crossing below: two identities
    # over one set of entries would let a term go missing from whichever one nobody asserts.
    assert outcome.events_read == (
        outcome.placed
        + outcome.rejected_count
        + outcome.cancelled_discarded
        + outcome.duplicates_discarded
        + outcome.overrides_applied
        + outcome.unplaced
    )
    # And the same total over the terms a delta's READER cares about, which is where the identifiers
    # rather than the count are what a removal is evidenced by.
    assert outcome.events_read == len(outcome.events) + len(outcome.removed_uids) + (
        outcome.rejected_count
    )
    # A change-bearing delta is a successful read, and this mark is what sends it down the
    # reconcile path: the anchor writer removes by identifier here, never by absence, which is
    # what keeps the entries the delta did not mention exactly where they stand.
    assert outcome.reparsed is True


async def test_a_delta_carrying_only_removals_is_a_read_that_removes_them() -> None:
    # The case a change count cannot see. A poll whose every entry is a cancellation reports no
    # event at all, so a reader that asked only "did any event change" would call it unchanged and
    # leave the removed commitments occupying the plan until something else happened to move.
    google, transport = adapter(
        [
            ok(
                events_page(
                    event("gone-1", status="cancelled", start=None, end=None),
                    event("gone-2", status="cancelled", start=None, end=None),
                    sync_token=NEXT_TOKEN,
                )
            )
        ]
    )

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 1
    assert state.last_error is None
    assert state.anchors_current == 0
    # What comes back is still the delta, so the removals travel as the identifiers the provider
    # named rather than as an absence nobody can address.
    assert outcome.incremental is True
    assert outcome.reparsed is True
    assert outcome.events == ()
    assert outcome.removed_uids == ("gone-1", "gone-2")


async def test_an_unreadable_delta_entry_is_still_a_change_whose_rejection_is_recorded() -> None:
    # An entry that produced neither an event nor a removal is still a change: something moved, and
    # answering "unchanged" would leave whatever moved unread until something else happened. The
    # rejection rides the successful attempt, because the read itself succeeded.
    # Deliberately conservative afterwards: the reconcile path clears staleness only off the anchors
    # it touches, so flags an earlier failure left stay set when a delta names nothing to touch.
    # The provider did answer, so confirm's global clear would also be defensible; revisit if a
    # source can sit stale behind repeated unreadable deltas.
    google, transport = adapter(
        [ok(events_page(event("unreadable", start="2026-02-10T09:00:00", end=None)))]
    )

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 1
    assert outcome.reparsed is True
    assert outcome.events == ()
    assert [one.uid for one in outcome.rejected] == ["unreadable"]
    assert state.rejected_total == 1


async def test_a_delta_reports_an_occurrence_that_moved_out_of_the_horizon() -> None:
    # The case a windowed reading of a delta would hide, and the one that matters most: the anchor
    # inside the window is the one that has to go. A full read is windowed at the provider and would
    # simply not list it, which removes it by absence; a delta is not windowed at all, because
    # Google refuses `timeMin` beside a sync token, so clipping here is syncr choosing to lose it.
    google, _ = adapter(
        [
            ok(
                events_page(
                    event("moved-away", start="2027-02-10T09:00:00Z", end="2027-02-10T10:00:00Z")
                )
            )
        ]
    )

    outcome, _state = await google.read_changes(
        source(sync_state=synced()), since=SYNC_TOKEN, at=NOW
    )

    assert [one.uid for one in outcome.events] == ["moved-away"]
    # Not counted as unplaced either: a delta places nothing, so there is no window to fall outside
    # of and nothing for that term to mean here.
    assert outcome.unplaced == 0


async def test_a_delta_outside_the_horizon_still_accounts_for_every_entry() -> None:
    # The identity on the one delta shape that can break it while leaving every count zero. A clip
    # applied here drops the entry from `placed` and adds it to nothing, so one entry the provider
    # sent would sit in no term at all: the state the tally exists to make impossible. Its own test
    # rather than another assertion in the test above, because that one asserts the event list first
    # and would fail there before reaching this, which would leave the identity unarmed.
    google, _ = adapter(
        [
            ok(
                events_page(
                    event("moved-away", start="2027-02-10T09:00:00Z", end="2027-02-10T10:00:00Z")
                )
            )
        ]
    )

    outcome, _state = await google.read_changes(
        source(sync_state=synced()), since=SYNC_TOKEN, at=NOW
    )

    assert outcome.events_read == 1
    assert outcome.events_read == (
        outcome.placed
        + outcome.rejected_count
        + outcome.cancelled_discarded
        + outcome.duplicates_discarded
        + outcome.overrides_applied
        + outcome.unplaced
    )


async def test_a_change_outside_the_horizon_is_applied_rather_than_escalated() -> None:
    # The same rule at the decision it feeds. The occurrence has already left the plan's window, so
    # treating the delta as unchanged would be the wrong answer; and reading fully over the horizon
    # would find nothing new, because a windowed read cannot list an event outside it. Applying the
    # delta is both cheaper and the only answer that touches the commitment at all.
    google, transport = adapter(
        [
            ok(
                events_page(
                    event("moved-away", start="2027-02-10T09:00:00Z", end="2027-02-10T10:00:00Z"),
                    sync_token=NEXT_TOKEN,
                )
            )
        ]
    )

    outcome, _state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 1
    assert outcome.reparsed is True
    assert [one.uid for one in outcome.events] == ["moved-away"]


async def test_a_poll_that_finds_no_change_answers_with_an_empty_delta() -> None:
    # The cheap poll, as the value it now carries: a delta that names nothing changed and nothing
    # removed. `reparsed` stays unset, which is what keeps it answering exactly as an ICS 304 does.
    google, transport = adapter([ok(events_page(sync_token=NEXT_TOKEN))])

    outcome, _state = await google.fetch(source(sync_state=synced()))

    assert len(transport.calls) == 1
    assert outcome.incremental is True
    assert outcome.removed_uids == ()
    assert outcome.events == ()
    assert outcome.reparsed is False


async def test_the_delta_line_states_what_changed_and_what_was_removed(
    rendered_lines: io.StringIO,
) -> None:
    # The two figures an operator needs to read one applied delta, under names the redactor keeps:
    # the titles these lines pass over are the most sensitive values in the product.
    google, _ = adapter(
        [
            ok(
                events_page(
                    event("changed"),
                    event("gone-1", status="cancelled", start=None, end=None),
                    event("gone-2", status="cancelled", start=None, end=None),
                    sync_token=NEXT_TOKEN,
                )
            )
        ]
    )

    await google.fetch(source(sync_state=synced()))

    line = one_line(rendered_lines, "calendars.google.delta")
    # Asserted as an exact key set, so a field added to this line has to be justified here rather
    # than arriving with whatever it carries.
    assert set(line) == {
        "event",
        "level",
        "timestamp",
        "service",
        "source_id",
        "tenant_id",
        "changed_count",
        "rejected_count",
        "removed_count",
        "attempt_count",
    }
    # Two different figures, so neither can be read as the other's constant.
    assert line["changed_count"] == 1
    assert line["removed_count"] == 2


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


async def test_a_failed_read_is_not_a_delta() -> None:
    # The third answer `fetch` sorts, and the one that was sorted by a field's DEFAULT rather than
    # by anything asserted. A failure record carries an empty event list for a different reason than
    # a quiet poll does, and a caller that read its silence about an event as a removal would delete
    # the calendar every time Google was briefly unreachable.
    google, _ = adapter([failed(500)])

    outcome, state = await google.fetch(source(sync_state=synced()))

    assert outcome.incremental is False
    assert outcome.removed_uids == ()
    assert state.last_error is not None


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


async def test_a_delta_over_max_pages_does_not_retain_the_cursor() -> None:
    # A delta that exceeds the page bound did not finish, so the cursor that produced it cannot
    # claim the read completed. Retaining it would make the next poll re-page through the same
    # bound and never finish; dropping it costs one full read instead, and the source's
    # resync_reason names why. This is the exposure the one-page detector closed by construction
    # and a paging delta path reopens.
    google, transport = adapter([ok(events_page(event("change"), page_token="always-another"))])
    held = synced()

    outcome, state = await google.fetch(source(sync_state=held))

    # MAX_PAGES pages were read, each carrying a change and another page token. The 41st page
    # is the one the bound stops at.
    assert len(transport.calls) == MAX_PAGES
    # A bounded failure is not a delta: its events do not reach the anchor writer.
    assert outcome.events == ()
    assert outcome.incremental is False
    assert outcome.reparsed is False
    # The cursor that produced the read is NOT retained: the next poll reads fully.
    assert state.cursor is None
    assert state.resync_reason == DELTA_OVER_MAX_PAGES
    # The failure is still recorded: the read did not succeed, and the anchors are retained.
    assert state.last_error is not None
    assert RETAINED_NOTICE in state.last_error
    assert state.last_success_at == EARLIER
    assert state.anchors_current == held.anchors_current
    assert state.attempts == MAX_PAGES


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
        writes=READS_ONLY,
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


async def test_the_adapter_a_request_composes_refuses_to_write() -> None:
    # The structural half of "the projection never sits on a request": the read composition holds
    # the refusing arm, so no route can reach a destructive write however it is wired.
    google, transport = adapter([ok(events_page())])

    with pytest.raises(ProjectionRefused, match="only writes the plan from its background worker"):
        await google.reconcile(source(display_name="syncr (dev)"), [])

    # And it refused before spending a request, which is what makes the refusal free.
    assert transport.calls == []


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
