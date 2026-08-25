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

The last two sections are the two things a pass asks for once the anchors are written: a collision
detection, and a solve of the weeks the reconciliation invalidated. Both are conditional on what the
pass actually did, and each is conditional on a different part of the tally.
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
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_api.calendars.records import CalendarSourceId

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=3)

RECONCILED = "reconcile"
CONFIRMED = "confirm"
MARKED_STALE = "mark_possibly_stale"
# The two steps of a pass that are not anchor paths: what it asks for once the anchors are written.
DETECTED = "detect"
REQUESTED = "request"

# 2026-02-09 opens 2026-W07, so these are the weeks a reconciliation of NOW's occupancy reports.
WEEK = IsoWeek(2026, 7)
NEXT_WEEK = IsoWeek(2026, 8)

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
        created_at=EARLIER,
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


@dataclass
class RecordingSolves:
    """Records the weeks the pass asked for a solve of, which only a change may name.

    ``log`` is shared with the anchor writer by the test that asserts the ORDER of the two, for the
    same reason the collision recorder shares one: a request made before the reconciliation would
    ask the counter for weeks nothing had bumped yet.

    A double over the one method a pass calls rather than the real collaborator, whose own answer is
    read against real operation rows in ``test_anchor_sync_requests_a_solve.py``.
    """

    asked: list[frozenset[IsoWeek]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    async def request(self, weeks: frozenset[IsoWeek]) -> tuple[IsoWeek, ...]:
        self.asked.append(weeks)
        self.log.append(REQUESTED)
        return tuple(sorted(weeks))


def syncer(
    adapter: StubAdapter,
    anchors: RecordingAnchors,
    sources: RecordingSources,
    collisions: RecordingCollisions | None = None,
    solves: RecordingSolves | None = None,
) -> SourceSyncer:
    return SourceSyncer(
        sources=sources,  # type: ignore[arg-type]  # a fake over the one method a pass calls
        operations=None,  # type: ignore[arg-type]  # a scheduled pass enqueues no operation
        # One adapter per provider, keyed by the provider a source names. A stub over the one
        # method a pass calls.
        adapters={ICS: adapter},
        anchors=anchors,
        collisions=collisions or RecordingCollisions(),
        solves=solves or RecordingSolves(),  # type: ignore[arg-type]  # the one method a pass calls
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


def a_change_bearing_delta() -> tuple[FetchOutcome, SyncStateRecord]:
    """A Google poll that reported changes: the fourth kind of successful read.

    A delta is not a fourth ATTEMPT. ``reparsed`` is set exactly as a full read's is, because a
    body was read and its changes are safe to apply; ``incremental`` is what keeps the reconciler
    from removing what the delta did not mention.
    """
    outcome = FetchOutcome(
        events=(an_event("changed"),),
        removed_uids=("cancelled",),
        events_read=2,
        placed=1,
        cancelled_discarded=1,
        reparsed=True,
        incremental=True,
    )
    state = SyncStateRecord(last_success_at=NOW, last_attempt_at=NOW, anchors_current=1)
    return outcome, state


def a_quiet_delta() -> tuple[FetchOutcome, SyncStateRecord]:
    """A Google poll whose provider answered "nothing changed since your cursor".

    The same shape an ICS 304 produces: a success that reparsed nothing, so the anchors are
    confirmed rather than reconciled, whatever the mechanism that produced the answer.
    """
    return (
        FetchOutcome(incremental=True),
        SyncStateRecord(last_success_at=NOW, last_attempt_at=NOW, anchors_current=7),
    )


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
        (a_change_bearing_delta(), RECONCILED),
        (a_read(events=0), RECONCILED),
        (an_unchanged_feed(), CONFIRMED),
        (a_quiet_delta(), CONFIRMED),
        (an_unreachable_feed(), MARKED_STALE),
    ],
    ids=[
        "a-feed-was-read",
        "a-delta-reported-changes",
        "a-feed-published-nothing",
        "unchanged",
        "a-quiet-delta",
        "unreachable",
    ],
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
        (a_change_bearing_delta(), RECONCILED),
        (an_unchanged_feed(), CONFIRMED),
        (an_unreachable_feed(), MARKED_STALE),
    ],
    ids=["read", "a-change-bearing-delta", "unchanged", "unreachable"],
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
    # TENANTS survive is `calendars/runner.py`'s: its per-tenant pass answers with an empty tally
    # on a fault rather than re-raising, so a persistent fault on the first tenant does not starve
    # the rest. That containment is a property this contract leans on, so it is named where the
    # contract is stated rather than left for the two files to drift apart.
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


# --------------------------------------------------------------------------------
# Which weeks a pass asks for a solve of.
#
# The reconciliation bumps the weeks whose occupancy moved, and a bump is a guard rather than an
# act: it makes a running solve's conditional write fail and replaces it with nothing. So the pass
# asks, and it asks for the weeks the reconciliation named and no others. The condition is not the
# detection's: a removal frees space, which can raise no conflict and still leaves a week whose plan
# describes occupancy that has gone.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("delta", "invalidated"),
    [
        (AnchorDelta(created=1, current=1, occupied_weeks=frozenset({WEEK})), {WEEK}),
        (
            AnchorDelta(updated=1, current=1, occupied_weeks=frozenset({WEEK, NEXT_WEEK})),
            {WEEK, NEXT_WEEK},
        ),
        (AnchorDelta(removed=1, current=0, occupied_weeks=frozenset({WEEK})), {WEEK}),
        (AnchorDelta(current=7), set()),
        (AnchorDelta(marked_stale=7, current=7), set()),
    ],
    ids=["created", "moved-across-a-boundary", "removed", "nothing-changed", "marked-stale"],
)
async def test_the_weeks_a_pass_invalidated_are_the_weeks_it_asks_to_solve(
    delta: AnchorDelta, invalidated: set[IsoWeek]
) -> None:
    # The pass hands on the tally's own set rather than deriving a second answer from the counts:
    # which weeks a change reached is the reconciler's question, and answering it twice is how two
    # readings of one change come to disagree.
    solves = RecordingSolves()
    outcome, state = a_read(events=1)

    await syncer(
        StubAdapter(outcome, state),
        DeltaAnchors(delta),  # type: ignore[arg-type]  # a writer over the three a pass calls
        RecordingSources(),
        solves=solves,
    ).sync(a_source())

    assert solves.asked == [frozenset(invalidated)]


async def test_a_pass_that_only_removed_asks_for_a_solve_and_for_no_detection() -> None:
    """The discriminating pair, and why the two conditions are not one flag.

    A removal frees time. Nothing new can have landed on a planned block, so there is no conflict to
    raise; and the week's plan still describes an hour of occupancy the source says is gone, so it
    needs the solve. A pass that reused the detection's condition would skip exactly this case, and
    a cancelled lecture is the case a stale plan is most visible in.
    """
    collisions = RecordingCollisions()
    solves = RecordingSolves()
    outcome, state = a_read(events=0)

    await syncer(
        StubAdapter(outcome, state),
        DeltaAnchors(AnchorDelta(removed=1, current=0, occupied_weeks=frozenset({WEEK}))),  # type: ignore[arg-type]
        RecordingSources(),
        collisions,
        solves,
    ).sync(a_source())

    assert solves.asked == [frozenset({WEEK})]
    assert collisions.asked == []


async def test_an_excluded_source_asks_for_no_solve() -> None:
    # It is not fetched at all, so no commitment of it moved and no week of it was invalidated.
    solves = RecordingSolves()
    outcome, state = a_read(events=3)

    await syncer(
        StubAdapter(outcome, state), RecordingAnchors(), RecordingSources(), solves=solves
    ).sync(a_source(included=False))

    assert solves.asked == []


async def test_a_solve_is_asked_for_after_the_anchors_are_reconciled() -> None:
    # The other order that is load-bearing. The request reads the version rows the reconciliation
    # bumped, so asking first would enumerate the weeks as they were before the feed moved anything
    # and would ask for nothing. One shared log, because two "it happened" lists cannot say which.
    log: list[str] = []
    outcome, state = a_read(events=1)

    await syncer(
        StubAdapter(outcome, state),
        DeltaAnchors(AnchorDelta(created=1, current=1, occupied_weeks=frozenset({WEEK})), log),  # type: ignore[arg-type]
        RecordingSources(),
        solves=RecordingSolves(log=log),
    ).sync(a_source())

    assert log == [RECONCILED, REQUESTED]
