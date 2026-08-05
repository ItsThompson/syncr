"""Which of the three anchor paths one sync attempt takes, and what it writes back.

This is the invariant pair A3 and A4, and it is the one place in the subsystem where getting the
condition wrong is silent and destructive.

An unchanged feed and an unreachable feed both come back with an EMPTY event list. So a reconciler
that removed anchors absent from the events it was handed would clear every commitment of a healthy
feed that answered 304, and would clear every commitment of a feed whose publisher was down. Only
``FetchOutcome.reparsed`` distinguishes "the feed said nothing changed" from "the feed published
nothing", and only ``last_error`` distinguishes a failure from either.

So the syncer is exercised with a recording writer rather than a real reconciler: what is asserted
is the CHOICE, and asserting it through a real reconciler would make the test about SQL.

The sync-state write is asserted too, because the reconciler's own count replaces the parser's
event count: two events reaching one reconciliation key make those two numbers differ, and the
panel reports the number of anchors rather than the number of components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.anchor_writing import AnchorDelta
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.sync import SourceSyncer
from syncr_domain.intervals import Interval

if TYPE_CHECKING:
    from syncr_api.calendars.records import CalendarSourceId

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=3)

RECONCILED = "reconcile"
CONFIRMED = "confirm"
MARKED_STALE = "mark_possibly_stale"
# The one step of a pass that is not an anchor path: what it asks for once the anchors are written.
DETECTED = "detect"

# What each recorded call answers with, so a test can tell the count came from the writer rather
# than from the parser's event list.
COUNTS = {RECONCILED: 41, CONFIRMED: 37, MARKED_STALE: 29}


def an_event(uid: str) -> RawEvent:
    return RawEvent(
        uid=uid,
        series_uid=None,
        title="Lecture",
        interval=Interval(NOW, NOW + timedelta(hours=2)),
        location=None,
        sequence=0,
        all_day=False,
    )


def a_source(*, included: bool = True) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="University timetable",
        external_id="https://example.ac.uk/timetable.ics",
        included=included,
        horizon_days=None,
        sync_state=SyncStateRecord(
            last_success_at=EARLIER, last_attempt_at=EARLIER, anchors_current=7
        ),
    )


@dataclass
class RecordingAnchors:
    """An anchor writer that records which path it was asked for, and answers a known count."""

    calls: list[str] = field(default_factory=list)

    async def reconcile(self, source: CalendarSourceRecord, outcome: FetchOutcome) -> AnchorDelta:
        del source, outcome
        self.calls.append(RECONCILED)
        return AnchorDelta(created=1, removed=2, current=COUNTS[RECONCILED])

    async def confirm(self, source: CalendarSourceRecord) -> AnchorDelta:
        del source
        self.calls.append(CONFIRMED)
        return AnchorDelta(current=COUNTS[CONFIRMED])

    async def mark_possibly_stale(self, source: CalendarSourceRecord) -> AnchorDelta:
        del source
        self.calls.append(MARKED_STALE)
        return AnchorDelta(marked_stale=7, current=COUNTS[MARKED_STALE])


@dataclass
class StubAdapter:
    """One prepared answer, standing for whichever of the three the adapter would have produced."""

    outcome: FetchOutcome
    state: SyncStateRecord

    async def fetch(self, source: CalendarSourceRecord) -> tuple[FetchOutcome, SyncStateRecord]:
        del source
        return self.outcome, self.state


@dataclass
class RecordingSources:
    """Records the sync state written, which is the other half of what a pass produces."""

    saved: list[tuple[CalendarSourceId, SyncStateRecord]] = field(default_factory=list)

    async def save_sync_state(self, source_id: CalendarSourceId, state: SyncStateRecord) -> None:
        self.saved.append((source_id, state))


@dataclass
class RecordingCollisions:
    """Records whether the pass asked for a detection, which only a change may do.

    ``log`` is shared with the anchor writer by the test that asserts the ORDER of the two. Two
    independent "it happened" lists cannot say which happened first, and the order is the whole
    claim: a detection that ran before the reconciliation would read the commitments as they were
    before the feed moved them.
    """

    asked: list[datetime] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    async def detect(self, *, now: datetime) -> object:
        self.asked.append(now)
        self.log.append(DETECTED)
        return ()


def syncer(
    adapter: StubAdapter,
    anchors: RecordingAnchors,
    sources: RecordingSources,
    collisions: RecordingCollisions | None = None,
) -> SourceSyncer:
    return SourceSyncer(
        sources=sources,  # type: ignore[arg-type]  # a fake over the one method a pass calls
        operations=None,  # type: ignore[arg-type]  # a scheduled pass enqueues no operation
        # One adapter per provider, keyed by the provider a source names. A stub over the one
        # method a pass calls.
        adapters={ICS: adapter},
        anchors=anchors,
        collisions=collisions or RecordingCollisions(),
        clock=lambda: NOW,
    )


def a_read(*, events: int) -> tuple[FetchOutcome, SyncStateRecord]:
    """A fetch that actually read the feed, whatever it found."""
    outcome = FetchOutcome(
        events=tuple(an_event(f"uid-{index}") for index in range(events)),
        events_read=events,
        placed=events,
        reparsed=True,
    )
    state = SyncStateRecord(
        last_success_at=NOW, last_attempt_at=NOW, events_read=events, anchors_current=events
    )
    return outcome, state


def an_unchanged_feed() -> tuple[FetchOutcome, SyncStateRecord]:
    """A 304: a successful attempt that reparsed nothing, so the last parse still stands."""
    return FetchOutcome(), SyncStateRecord(
        last_success_at=NOW, last_attempt_at=NOW, anchors_current=7
    )


def an_unreachable_feed() -> tuple[FetchOutcome, SyncStateRecord]:
    """A failure: the attempt moved and the success did not."""
    return FetchOutcome(), SyncStateRecord(
        last_success_at=EARLIER,
        last_attempt_at=NOW,
        last_error="the publisher answered 503.",
        anchors_current=7,
    )


@pytest.mark.parametrize(
    ("fetched", "expected"),
    [
        (a_read(events=3), RECONCILED),
        (a_read(events=0), RECONCILED),
        (an_unchanged_feed(), CONFIRMED),
        (an_unreachable_feed(), MARKED_STALE),
    ],
    ids=["a-feed-was-read", "a-feed-published-nothing", "unchanged", "unreachable"],
)
async def test_each_attempt_takes_the_anchor_path_it_should(
    fetched: tuple[FetchOutcome, SyncStateRecord], expected: str
) -> None:
    anchors = RecordingAnchors()
    outcome, state = fetched

    await syncer(StubAdapter(outcome, state), anchors, RecordingSources()).sync(a_source())

    assert anchors.calls == [expected]


async def test_a_feed_that_published_nothing_removes_and_an_empty_answer_does_not() -> None:
    # The pair the whole routing exists for. All three of these carry an empty event list, and
    # exactly one of them means "remove the anchors you hold".
    read_nothing = RecordingAnchors()
    unchanged = RecordingAnchors()
    unreachable = RecordingAnchors()

    for fetched, anchors in (
        (a_read(events=0), read_nothing),
        (an_unchanged_feed(), unchanged),
        (an_unreachable_feed(), unreachable),
    ):
        outcome, state = fetched
        assert outcome.events == ()
        await syncer(StubAdapter(outcome, state), anchors, RecordingSources()).sync(a_source())

    assert read_nothing.calls == [RECONCILED]
    assert unchanged.calls == [CONFIRMED]
    assert unreachable.calls == [MARKED_STALE]


@pytest.mark.parametrize(
    ("fetched", "path"),
    [
        (a_read(events=3), RECONCILED),
        (an_unchanged_feed(), CONFIRMED),
        (an_unreachable_feed(), MARKED_STALE),
    ],
    ids=["read", "unchanged", "unreachable"],
)
async def test_the_reconcilers_own_count_is_what_the_sync_state_records(
    fetched: tuple[FetchOutcome, SyncStateRecord], path: str
) -> None:
    # The parser's event count and the rows a source contributes differ whenever two events reach
    # one reconciliation key, and the panel reports anchors. Asserted for all three attempts,
    # because a count carried forward from an earlier attempt would drift silently.
    sources = RecordingSources()
    outcome, state = fetched
    source = a_source()

    await syncer(StubAdapter(outcome, state), RecordingAnchors(), sources).sync(source)

    assert [written.anchors_current for _id, written in sources.saved] == [COUNTS[path]]
    assert [source_id for source_id, _written in sources.saved] == [source.id]


async def test_the_error_and_the_instants_the_adapter_recorded_survive_the_count_replacement() -> (
    None
):
    # Only `anchors_current` moves. A rewritten state that dropped the error would make a failed
    # sync read as a success, which is the failure the sync-state rules exist to prevent.
    sources = RecordingSources()
    outcome, state = an_unreachable_feed()

    await syncer(StubAdapter(outcome, state), RecordingAnchors(), sources).sync(a_source())

    _source_id, written = sources.saved[0]
    assert written.last_error == state.last_error
    assert written.last_success_at == EARLIER
    assert written.last_attempt_at == NOW


async def test_an_excluded_source_touches_no_anchor_and_writes_no_state() -> None:
    # The user asked for zero anchors from it. Reconciling would remove every anchor it
    # contributed, and marking them stale would report a problem the user already resolved.
    anchors = RecordingAnchors()
    sources = RecordingSources()
    outcome, state = a_read(events=3)

    result, returned_state = await syncer(StubAdapter(outcome, state), anchors, sources).sync(
        a_source(included=False)
    )

    assert anchors.calls == []
    assert sources.saved == []
    assert result.events == ()
    assert returned_state.last_attempt_at == EARLIER


# --------------------------------------------------------------------------------
# What happens when the WRITER fails, rather than the feed.
#
# This path was untested, and that is what let a publisher's NUL byte abort a whole tenant's tick
# silently: the raise came from inside `_reconciled`, before `save_sync_state`, so `last_error` was
# never written and the panel kept showing the last success. The scrub in `anchors.identity` closed
# the feed-shaped cause. What is pinned here is the contract for every OTHER cause.
# --------------------------------------------------------------------------------


class FailingAnchors:
    """An anchor writer whose reconcile fails the way a database fault would."""

    def __init__(self) -> None:
        self.attempted = 0

    async def reconcile(self, source: CalendarSourceRecord, outcome: FetchOutcome) -> AnchorDelta:
        del source, outcome
        self.attempted += 1
        message = "the database went away mid-pass"
        raise RuntimeError(message)

    async def confirm(self, source: CalendarSourceRecord) -> AnchorDelta:
        del source
        return AnchorDelta()

    async def mark_possibly_stale(self, source: CalendarSourceRecord) -> AnchorDelta:
        del source
        return AnchorDelta()


async def test_a_failing_anchor_writer_propagates_and_records_no_partial_state() -> None:
    # Deliberate, and stated rather than incidental. A writer that fails is syncr's fault, not the
    # publisher's: the feed was read successfully. Writing `last_error` here would blame the feed
    # for a defect on our side, and the panel would tell the user to go and check a calendar
    # provider that did nothing wrong.
    #
    # So it propagates, and nothing is half-written: a tenant's anchors and the sync state that
    # counts them land together or not at all.
    #
    # WHAT PROPAGATION DEPENDS ON, stated here because this test is what blesses it.
    # Propagating is only contained if the WORKER LOOP catches per tenant. `worker/main.py` catches
    # per duty, so the process survives and the tick is counted either way. Whether the other
    # TENANTS survive is `calendars/runner.py`'s to decide: if its per-tenant loop does not catch, a
    # raise unwinds the whole pass and every tenant ordered after the failing one is skipped for
    # that tick, and a persistent fault on the first starves the rest one tick at a time.
    #
    # Not this ticket's regression: that loop already awaits `SettingsRepository.read()` before a
    # syncer exists, so a database fault could always unwind it, and P0 runs one tenant. It IS a
    # property this contract leans on, so it is named where the contract is stated rather than left
    # for the two files to drift apart. Per-tenant containment belongs to the runner's owner.
    anchors = FailingAnchors()
    sources = RecordingSources()
    outcome, state = a_read(events=3)

    with pytest.raises(RuntimeError, match="went away"):
        await syncer(StubAdapter(outcome, state), anchors, sources).sync(a_source())  # type: ignore[arg-type]

    assert anchors.attempted == 1
    # The invariant that matters: no PARTIAL state. A state written before the anchors it counts
    # would claim a successful sync of rows that were then rolled back.
    assert sources.saved == []


# --------------------------------------------------------------------------------
# When a pass asks for a collision detection.
#
# A conflict is detected when the commitment arrives rather than found later by a solve, so the
# pass that ingested it is what asks. The condition is what matters: a poll runs every fifteen
# minutes and most of them change nothing, so asking on every attempt would read every horizon
# week's plan and every commitment in it for no possible answer.
# --------------------------------------------------------------------------------


@dataclass
class DeltaAnchors:
    """An anchor writer answering with a stated tally, whichever path it was asked for."""

    delta: AnchorDelta
    log: list[str] = field(default_factory=list)

    async def reconcile(self, source: CalendarSourceRecord, outcome: FetchOutcome) -> AnchorDelta:
        del source, outcome
        self.log.append(RECONCILED)
        return self.delta

    async def confirm(self, source: CalendarSourceRecord) -> AnchorDelta:
        del source
        return self.delta

    async def mark_possibly_stale(self, source: CalendarSourceRecord) -> AnchorDelta:
        del source
        return self.delta


@pytest.mark.parametrize(
    ("delta", "asks"),
    [
        (AnchorDelta(created=1, current=1), True),
        (AnchorDelta(updated=1, current=7), True),
        (AnchorDelta(removed=2, current=5), False),
        (AnchorDelta(marked_stale=7, current=7), False),
        (AnchorDelta(scrubbed=3, current=7), False),
        (AnchorDelta(current=7), False),
    ],
    ids=["created", "updated", "removed-only", "marked-stale", "scrubbed-only", "nothing-changed"],
)
async def test_a_detection_is_asked_for_exactly_when_a_commitment_arrived_or_moved(
    delta: AnchorDelta, asks: bool
) -> None:
    collisions = RecordingCollisions()
    outcome, state = a_read(events=1)

    await syncer(
        StubAdapter(outcome, state),
        DeltaAnchors(delta),  # type: ignore[arg-type]  # a writer over the three a pass calls
        RecordingSources(),
        collisions,
    ).sync(a_source())

    assert (collisions.asked == [NOW]) is asks


async def test_an_excluded_source_asks_for_no_detection() -> None:
    # It is not fetched at all, so nothing about the tenant's commitments changed.
    collisions = RecordingCollisions()
    outcome, state = a_read(events=3)

    await syncer(
        StubAdapter(outcome, state), RecordingAnchors(), RecordingSources(), collisions
    ).sync(a_source(included=False))

    assert collisions.asked == []


async def test_a_detection_runs_after_the_anchors_are_reconciled() -> None:
    # The order that is load-bearing, and the only one: a detection reads the commitments the pass
    # just wrote, so running it first would read the week as it was before the feed moved anything
    # and would raise nothing. One shared log, because two "it happened" lists cannot say which.
    #
    # The sync-state write's position is deliberately NOT asserted: it is in the same transaction,
    # so nothing about atomicity or about what the detection sees depends on where it falls.
    log: list[str] = []
    outcome, state = a_read(events=1)

    await syncer(
        StubAdapter(outcome, state),
        DeltaAnchors(AnchorDelta(created=1, current=1), log),  # type: ignore[arg-type]
        RecordingSources(),
        RecordingCollisions(log=log),
    ).sync(a_source())

    assert log == [RECONCILED, DETECTED]
