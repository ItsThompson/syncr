"""The calendar poll's cadence, its due-ness rule, and its place on the worker loop.

The sync itself is proven against real Postgres in ``test_calendar_routes_integration.py``. What
is proven here is the schedule around it, which is where two mistakes are easy and invisible.

**The first tick schedules rather than polling.** The worker ticks every few seconds, and a
container that restarts under `restart: unless-stopped` starts a fresh runner each time, so a
runner that polled immediately would send a burst of requests at a publisher on every crash.

**Due-ness lives on the source, not in the runner.** So a restart does not reset every feed's
schedule, and a source added mid-interval is polled on the next tick rather than waiting out an
interval it was not present for. That is asserted through ``sync_due``, against a fake repository
and a fake fetcher, because a real feed would make the test about the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.calendars.anchor_writing import AnchorDelta
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS, SYNC_INTERVAL
from syncr_api.calendars.events import FetchOutcome
from syncr_api.calendars.feeds import FeedAnswer, FeedBody, FeedUnreachable
from syncr_api.calendars.ics_adapter import IcsAdapter
from syncr_api.calendars.records import CalendarSourceRecord, SyncStateRecord
from syncr_api.calendars.runner import TENANT_POLL_FAILURES, CalendarSyncRunner
from syncr_api.calendars.sync import SourceSyncer, SyncPass
from syncr_api.worker.main import RUNNERS, WorkerContext, run_iteration
from syncr_common.logging import is_sensitive_key
from syncr_domain.intervals import Interval
from syncr_domain.zones import ZoneProfile
from tests.hostile_ics import EMPTY_FEED

if TYPE_CHECKING:
    from syncr_api.calendars.records import CalendarSourceId

START = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
HOME = ZoneProfile(home_zone="Europe/London")
HORIZON = Interval(START, START + timedelta(days=14))

TIMETABLE = "https://example.ac.uk/timetable.ics"
HOLIDAYS = "https://example.org/holidays.ics"


class MovableClock:
    def __init__(self, at: datetime) -> None:
        self.now = at

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


class CountingSessions:
    """Records how many sessions were opened, which is how many polls really ran.

    Answers the tenant enumeration with nothing, so a poll completes without a database and what
    is measured is the cadence rather than the fetching.
    """

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self) -> CountingSessions:
        self.opened += 1
        return self

    async def __aenter__(self) -> CountingSessions:
        return self

    async def __aexit__(self, *_exit: object) -> None:
        return None

    def begin(self) -> CountingSessions:
        return self

    async def scalars(self, _statement: object) -> list[object]:
        return []


@dataclass
class FakeSources:
    """The included sources of one tenant, and the sync states written back to them."""

    sources: list[CalendarSourceRecord] = field(default_factory=list)
    saved: dict[CalendarSourceId, SyncStateRecord] = field(default_factory=dict)

    async def included_for(self, _provider: str) -> tuple[CalendarSourceRecord, ...]:
        return tuple(self.sources)

    async def save_sync_state(self, source_id: CalendarSourceId, state: SyncStateRecord) -> None:
        self.saved[source_id] = state


@dataclass
class RecordedFetcher:
    """Answers by URL, and records which URLs were asked for."""

    answers: dict[str, FeedAnswer]
    asked: list[str] = field(default_factory=list)

    async def get(self, url: str, *, cursor: str | None) -> FeedAnswer:
        self.asked.append(url)
        return self.answers[url]


def source(
    *, external_id: str = TIMETABLE, attempted: datetime | None = None, anchors: int = 0
) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="University timetable",
        external_id=external_id,
        included=True,
        horizon_days=None,
        sync_state=SyncStateRecord(
            last_success_at=attempted, last_attempt_at=attempted, anchors_current=anchors
        ),
    )


def syncer(sources: FakeSources, fetcher: RecordedFetcher, clock: MovableClock) -> SourceSyncer:
    adapter = IcsAdapter(fetcher=fetcher, profile=HOME, horizon=HORIZON, clock=clock)
    return SourceSyncer(
        sources=sources,  # type: ignore[arg-type]  # a fake over the two methods a pass calls
        operations=None,  # type: ignore[arg-type]  # a scheduled pass enqueues no operation
        adapters={ICS: adapter},
        anchors=SilentAnchors(),
        clock=clock,
    )


class SilentAnchors:
    """An anchor writer that records nothing, for the tests about the SCHEDULE.

    What this file asserts is when a poll happens, not what it writes. Which of the three anchor
    paths one attempt takes is asserted in ``test_anchor_reconciliation.py``, against a writer
    that records the call.
    """

    async def reconcile(self, source: object, outcome: object) -> AnchorDelta:
        del source, outcome
        return AnchorDelta()

    async def confirm(self, source: object) -> AnchorDelta:
        del source
        return AnchorDelta()

    async def mark_possibly_stale(self, source: object) -> AnchorDelta:
        del source
        return AnchorDelta()


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock(START)


@pytest.fixture
def sessions() -> CountingSessions:
    return CountingSessions()


@pytest.fixture
def context(sessions: CountingSessions, settings: object) -> WorkerContext:
    class _Database:
        sessionmaker = sessions

    return WorkerContext(settings=settings, database=_Database())  # type: ignore[arg-type]


# --------------------------------------------------------------------------------
# One tenant's fault is one tenant's
# --------------------------------------------------------------------------------


class _ThreeTenants:
    """A session factory that enumerates three tenants and fails inside the second's pass.

    The failure is raised where a real one would be: a settings read, an anchor write, or a bug,
    all of which happen INSIDE the per-tenant transaction. An adapter's own failures never reach
    here, because an adapter records a provider's behaviour on the source instead of raising.
    """

    def __init__(self, tenants: list[object]) -> None:
        self.tenants = tenants
        self.polled: list[object] = []

    def __call__(self) -> _ThreeTenants:
        return self

    async def __aenter__(self) -> _ThreeTenants:
        return self

    async def __aexit__(self, *_exit: object) -> None:
        return None

    def begin(self) -> _ThreeTenants:
        return self

    async def scalars(self, _statement: object) -> list[object]:
        return self.tenants


async def test_one_tenants_fault_does_not_drop_the_tenants_after_it(
    settings: object, clock: MovableClock
) -> None:
    # With one process serving every tenant, an exception unwinding the loop would make one
    # tenant's bug every tenant's outage: the pass for every tenant after it would not run, and
    # nothing on any panel would say so.
    faulty = uuid4()
    tenants = [uuid4(), faulty, uuid4()]
    sessions = _ThreeTenants(list(tenants))

    class _Database:
        sessionmaker = sessions

    context = WorkerContext(settings=settings, database=_Database())  # type: ignore[arg-type]
    runner = CalendarSyncRunner(interval=SYNC_INTERVAL, clock=clock)
    attempted: list[object] = []

    async def one_tenant(
        _context: object,
        _session: object,
        _feeds: object,
        _google: object,
        tenant_id: object,
        *,
        now: object,
    ) -> SyncPass:
        del now
        attempted.append(tenant_id)
        if tenant_id == faulty:
            message = "a settings read that could not reach the database"
            raise RuntimeError(message)
        return SyncPass(attempted=1, succeeded=1)

    runner._poll_tenant = one_tenant  # type: ignore[assignment,method-assign]  # the seam

    tally = await runner.poll(context, None, None, now=clock())  # type: ignore[arg-type]

    # Every tenant was attempted, and the two healthy ones are in the tally.
    assert attempted == tenants
    assert tally.attempted == 2
    assert tally.succeeded == 2


async def test_a_contained_fault_is_counted_rather_than_only_logged(
    settings: object, clock: MovableClock
) -> None:
    # A tenant failing every tick would otherwise leave every counter at zero while the duty
    # reported healthy, because the boundary is what stops the call raising at all.
    sessions = _ThreeTenants([uuid4()])

    class _Database:
        sessionmaker = sessions

    context = WorkerContext(settings=settings, database=_Database())  # type: ignore[arg-type]
    runner = CalendarSyncRunner(interval=SYNC_INTERVAL, clock=clock)

    async def always_fails(*_args: object, **_kwargs: object) -> SyncPass:
        message = "an anchor write that violated a constraint"
        raise RuntimeError(message)

    runner._poll_tenant = always_fails  # type: ignore[method-assign]  # the seam
    before = TENANT_POLL_FAILURES._value.get()

    await runner.poll(context, None, None, now=clock())  # type: ignore[arg-type]

    assert TENANT_POLL_FAILURES._value.get() == before + 1


# --------------------------------------------------------------------------------
# The cadence
# --------------------------------------------------------------------------------


def test_the_runner_is_on_the_worker_loop() -> None:
    # Nothing else polls a feed, so a runner that is not registered is a subscription that
    # silently never updates.
    assert any(isinstance(runner, CalendarSyncRunner) for runner in RUNNERS)


async def test_the_first_tick_schedules_rather_than_polling(
    context: WorkerContext, sessions: CountingSessions, clock: MovableClock
) -> None:
    runner = CalendarSyncRunner(interval=SYNC_INTERVAL, clock=clock)

    await runner(context)

    assert sessions.opened == 0
    assert runner.next_due_at == START + SYNC_INTERVAL


async def test_a_tick_before_the_interval_does_nothing(
    context: WorkerContext, sessions: CountingSessions, clock: MovableClock
) -> None:
    runner = CalendarSyncRunner(interval=SYNC_INTERVAL, clock=clock)
    await runner(context)

    clock.advance(SYNC_INTERVAL - timedelta(seconds=1))
    await runner(context)

    assert sessions.opened == 0


async def test_a_tick_at_the_interval_polls_and_reschedules(
    context: WorkerContext, sessions: CountingSessions, clock: MovableClock
) -> None:
    runner = CalendarSyncRunner(interval=SYNC_INTERVAL, clock=clock)
    await runner(context)
    clock.advance(SYNC_INTERVAL)

    await runner(context)

    assert sessions.opened == 1
    assert runner.next_due_at == START + SYNC_INTERVAL + SYNC_INTERVAL


async def test_many_ticks_produce_one_poll_per_interval(
    context: WorkerContext, sessions: CountingSessions, clock: MovableClock
) -> None:
    # The property the cadence exists for: the loop's resolution is not the poll's schedule.
    runner = CalendarSyncRunner(interval=SYNC_INTERVAL, clock=clock)
    for _tick in range(200):
        await runner(context)
        clock.advance(timedelta(seconds=30))

    # 200 ticks of 30 seconds is 100 minutes, which holds six whole quarter-hour intervals after
    # the first tick schedules the seventh.
    assert sessions.opened == 6


async def test_a_failing_poll_does_not_stop_the_loop(context: WorkerContext) -> None:
    # The loop's own contract, asserted through this runner: one failing duty must not take the
    # others down, and the worker counts the failure rather than exiting.
    class _Failing(CalendarSyncRunner):
        async def __call__(self, _context: WorkerContext) -> None:
            raise RuntimeError("the publisher went away")

    failures = await run_iteration(context, [_Failing(interval=SYNC_INTERVAL, clock=lambda: START)])

    assert failures == 1


# --------------------------------------------------------------------------------
# Due-ness
# --------------------------------------------------------------------------------


async def test_a_source_nobody_has_attempted_is_due_immediately(clock: MovableClock) -> None:
    # A feed added mid-interval is polled on the next tick rather than waiting out an interval it
    # was not present for.
    sources = FakeSources([source()])
    fetcher = RecordedFetcher({TIMETABLE: FeedBody(body=EMPTY_FEED, cursor=None)})

    tally = await syncer(sources, fetcher, clock).sync_due(now=clock())

    assert fetcher.asked == [TIMETABLE]
    assert tally == SyncPass(attempted=1, succeeded=1)


async def test_a_source_attempted_inside_the_interval_is_not_polled(clock: MovableClock) -> None:
    sources = FakeSources([source(attempted=START - SYNC_INTERVAL + timedelta(seconds=1))])
    fetcher = RecordedFetcher({TIMETABLE: FeedBody(body=EMPTY_FEED, cursor=None)})

    tally = await syncer(sources, fetcher, clock).sync_due(now=clock())

    assert fetcher.asked == []
    assert tally == SyncPass()
    # And nothing was written, so a tick that had no work leaves every sync instant alone.
    assert sources.saved == {}


async def test_a_source_attempted_at_the_interval_is_polled(clock: MovableClock) -> None:
    # The boundary, on the due side, so the comparison is shown not to be off by one interval.
    sources = FakeSources([source(attempted=START - SYNC_INTERVAL)])
    fetcher = RecordedFetcher({TIMETABLE: FeedBody(body=EMPTY_FEED, cursor=None)})

    await syncer(sources, fetcher, clock).sync_due(now=clock())

    assert fetcher.asked == [TIMETABLE]


async def test_the_interval_is_measured_from_the_attempt_not_the_success(
    clock: MovableClock,
) -> None:
    # A feed that has been down for a week is retried on the same schedule as one that works,
    # rather than being hammered on every tick.
    failing = source(attempted=None, anchors=7)
    failing = replace(
        failing,
        sync_state=SyncStateRecord(
            last_success_at=START - timedelta(days=7),
            last_attempt_at=START - timedelta(minutes=1),
            last_error="the feed answered 503 Service Unavailable",
            anchors_current=7,
        ),
    )
    sources = FakeSources([failing])
    fetcher = RecordedFetcher({TIMETABLE: FeedUnreachable(reason="still down")})

    await syncer(sources, fetcher, clock).sync_due(now=clock())

    assert fetcher.asked == []


async def test_one_feeds_failure_does_not_stop_the_next_from_being_polled(
    clock: MovableClock,
) -> None:
    sources = FakeSources([source(external_id=TIMETABLE), source(external_id=HOLIDAYS)])
    fetcher = RecordedFetcher(
        {
            TIMETABLE: FeedUnreachable(reason="the feed answered 503 Service Unavailable"),
            HOLIDAYS: FeedBody(body=EMPTY_FEED, cursor=None),
        }
    )

    tally = await syncer(sources, fetcher, clock).sync_due(now=clock())

    assert fetcher.asked == [TIMETABLE, HOLIDAYS]
    # Attempted twice, succeeded once, and both attempts recorded: staleness is computable for
    # the one that failed and current for the one that did not.
    assert tally.attempted == 2
    assert tally.succeeded == 1
    assert len(sources.saved) == 2


async def test_an_excluded_source_is_not_fetched_at_all(clock: MovableClock) -> None:
    # A forced sync on one answers without a fetch, because "nothing happened, by your own
    # instruction" is the honest answer and an error would be wrong.
    excluded = replace(source(), included=False)
    fetcher = RecordedFetcher({})

    outcome, state = await syncer(FakeSources(), fetcher, clock).sync(excluded)

    assert fetcher.asked == []
    assert outcome.reparsed is False
    assert outcome.events == ()
    # And its state is handed back untouched: the last attempt on it still describes the last time
    # syncr actually read it, rather than being overwritten by an attempt that never happened.
    assert state == excluded.sync_state


@pytest.mark.parametrize(
    "fields",
    [
        SyncPass(attempted=1, succeeded=1, events=2, rejected=3).as_log_fields(),
        FetchOutcome(
            events_read=3, duplicates_discarded=1, cancelled_discarded=1, reparsed=True
        ).as_log_fields(),
    ],
    ids=["a poll's tally", "a parse's tally"],
)
def test_no_count_is_bound_under_a_name_the_redactor_eats(fields: dict[str, int]) -> None:
    # Redaction is by key name and cannot tell a title from a number, so a count bound under a key
    # the redactor eats would render as [redacted] and the line would say nothing. Asked of the
    # redactor's own predicate rather than of a list copied from it, so a rename over there is
    # caught here rather than in a log nobody is reading at the time.
    #
    # Both tallies, because the parse's is the one the adapter binds on EVERY read.
    assert fields
    assert [key for key in fields if is_sensitive_key(key)] == []
