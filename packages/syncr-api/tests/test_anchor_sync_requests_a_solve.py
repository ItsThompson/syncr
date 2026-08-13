"""What one sync pass leaves in the operations table, against a real Postgres.

A pass that moved a commitment bumps the input version of every week whose occupancy moved. That
bump is a guard and not an act: it makes a running solve's conditional write fail, and the solve it
supersedes is replaced by nothing unless something asks. So the week ends up holding a plan built
around an hour the timetable has moved out of, and the version that says so reaches nothing. This
suite is the other half of ``test_anchor_sync_bumps_the_weeks.py``: that one asserts the bump, this
one asserts the operation the bump has to reach.

Driven through a whole ``SourceSyncer`` rather than through the reconciler, because the request is
the pass's and not the reconciler's, and because the point of stating it once is that a forced sync
and a scheduled poll cannot ask for different things. Only the adapter is a stub: a real feed would
make the suite about the network.

Four groups.

**A change leaves one pending solve per week it invalidated**, and a move across a week boundary
leaves one for each side.

**The three non-changes leave none.** A read that reparsed the feed and found every component
identical, a feed that answered "unchanged", and a feed that could not be read. The first is the one
that matters: it is what a fifteen-minute poll of a healthy timetable is, and a pass that enqueued
on every attempt would hold a supersede loop open forever, because each supersession enqueues a
follow-up and the next poll supersedes that.

**Two consecutive unchanged polls leave none**, which is the sequence rather than the single pass. A
poll that enqueued because the previous poll had enqueued is the same loop reached a different way.

**A week nobody has planned gets no solve.** It has no version row, so the counter left it alone,
and a solve of it would produce a plan for a week outside everything the tenant has planned.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.calendars.records import SyncStateRecord
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.calendars.solve_requests import TrackedWeekSolves
from syncr_api.calendars.sync import SourceSyncer
from syncr_api.conflicts.ingest import IngestConflicts
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import PENDING, SOLVE
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.models import Operation
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

HOME_ZONE = "UTC"

# 2026-02-09 is the Monday that opens 2026-W07.
WEEK = IsoWeek(2026, 7)
NEXT_WEEK = IsoWeek(2026, 8)
MONDAY_0000 = datetime(2026, 2, 9, 0, 0, tzinfo=UTC)
WEDNESDAY_1000 = MONDAY_0000 + timedelta(days=2, hours=10)
NEXT_WEDNESDAY_1000 = WEDNESDAY_1000 + timedelta(days=7)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
DEBOUNCE = debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS)

TIMETABLE = "https://example.ac.uk/timetable.ics"
LECTURE_UID = "lecture@example.ac.uk"


@pytest.fixture
async def engine(live_database_url: str) -> AsyncIterator[AsyncEngine]:
    live = create_db_engine(live_database_url)
    yield live
    await live.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
def tenant_id(owner: UserRecord) -> TenantId:
    return owner.tenant_id


@pytest.fixture
async def source(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> CalendarSourceRecord:
    async with sessions() as session, session.begin():
        return await CalendarSourceRepository(session, tenant_id).create(
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name="University timetable",
            external_id=TIMETABLE,
            included=True,
            horizon_days=None,
            created_at=NOW,
        )


class StubAdapter:
    """One prepared answer, standing for whatever the feed would have said.

    A stub rather than a real fetch, because what is under test is what the pass does with an
    answer. The three answers a feed can give are constructed by the helpers below, so which of the
    three anchor paths the pass takes is still decided by the pass itself.
    """

    def __init__(self, outcome: FetchOutcome, state: SyncStateRecord) -> None:
        self._outcome = outcome
        self._state = state

    async def fetch(self, source: CalendarSourceRecord) -> tuple[FetchOutcome, SyncStateRecord]:
        del source
        return self._outcome, self._state


def an_event(
    uid: str = LECTURE_UID, *, start: datetime = WEDNESDAY_1000, minutes: int = 120
) -> RawEvent:
    return RawEvent(
        uid=uid,
        series_uid=None,
        title="Computer Science Lecture",
        interval=Interval(start, start + timedelta(minutes=minutes)),
        location="Lecture Theatre 3",
        sequence=0,
        all_day=False,
    )


def a_read(*events: RawEvent) -> StubAdapter:
    """A fetch that actually reparsed the feed, which is the only attempt that may remove."""
    return StubAdapter(
        FetchOutcome(events=events, events_read=len(events), placed=len(events), reparsed=True),
        SyncStateRecord(
            last_success_at=NOW,
            last_attempt_at=NOW,
            events_read=len(events),
            anchors_current=len(events),
        ),
    )


def an_unchanged_feed() -> StubAdapter:
    """A 304: a successful attempt that reparsed nothing, so the last parse still stands."""
    return StubAdapter(
        FetchOutcome(),
        SyncStateRecord(last_success_at=NOW, last_attempt_at=NOW, anchors_current=1),
    )


def an_unreachable_feed() -> StubAdapter:
    """A failure: the attempt moved and the success did not."""
    return StubAdapter(
        FetchOutcome(),
        SyncStateRecord(
            last_success_at=NOW - timedelta(hours=3),
            last_attempt_at=NOW,
            last_error="the publisher answered 503.",
            anchors_current=1,
        ),
    )


async def synced(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
    adapter: StubAdapter,
) -> None:
    """One pass over one source, composed the way both of production's compositions do.

    One transaction, because that is what a pass is: the anchor rows, the versions its changes
    invalidated, and the operations those versions ask for either all land or none of them do.
    """
    async with sessions() as session, session.begin():
        version_rows = WeekInputVersionRepository(session, tenant_id)
        await SourceSyncer(
            sources=CalendarSourceRepository(session, tenant_id),
            operations=OperationLifecycle(OperationRepository(session, tenant_id), lambda: NOW),
            adapters={ICS: adapter},
            anchors=AnchorReconciler(
                AnchorRepository(session, tenant_id),
                AnchorTypeRepository(session, tenant_id),
                versions=TrackedWeekInputVersions(version_rows, clock=lambda: NOW),
                home_zone=HOME_ZONE,
            ),
            collisions=IngestConflicts(session, tenant_id),
            solves=TrackedWeekSolves(
                version_rows,
                build_solve_coordinator(session, tenant_id, clock=lambda: NOW, debounce=DEBOUNCE),
            ),
            clock=lambda: NOW,
        ).sync(source)


async def track(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *weeks: IsoWeek
) -> None:
    """Give each week a version row, which is what makes it a week anything acts on.

    A week with no row has no plan and no running solve, so a suite that seeded none would read
    every assertion below as green while nothing had been asked for at all.
    """
    async with sessions() as session, session.begin():
        versions = WeekInputVersionRepository(session, tenant_id)
        for week in weeks:
            await versions.bump(week, at=NOW)


async def pending_solves(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[Operation]:
    async with sessions() as session:
        found = await session.scalars(
            select(Operation)
            .where(
                Operation.tenant_id == tenant_id,
                Operation.kind == SOLVE,
                Operation.status == PENDING,
            )
            .order_by(Operation.iso_week)
        )
    return list(found)


def weeks_of(operations: Sequence[Operation]) -> list[str | None]:
    return [one.iso_week for one in operations]


# --------------------------------------------------------------------------------
# A change leaves one pending solve per week it invalidated.
# --------------------------------------------------------------------------------


async def test_a_sync_that_created_a_commitment_leaves_one_pending_solve_for_the_week(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    await track(sessions, tenant_id, WEEK)

    await synced(sessions, tenant_id, source, a_read(an_event()))

    assert weeks_of(await pending_solves(sessions, tenant_id)) == [str(WEEK)]


async def test_a_sync_that_moved_a_commitment_leaves_one_pending_solve_for_the_week(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The lecture theatre changed the hour, not the day. A solve that placed work around the old
    # hour read a week that no longer exists, and this is the operation that replaces it.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    await synced(
        sessions, tenant_id, source, a_read(an_event(start=WEDNESDAY_1000 + timedelta(hours=3)))
    )

    assert weeks_of(await pending_solves(sessions, tenant_id)) == [str(WEEK)]


async def test_a_sync_that_removed_a_commitment_leaves_one_pending_solve_for_the_week(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The cancelled lecture's hours are free now, which is the case a stale plan is most visible
    # in: the user is shown occupancy the source says is gone.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    await synced(sessions, tenant_id, source, a_read())

    assert weeks_of(await pending_solves(sessions, tenant_id)) == [str(WEEK)]


async def test_a_commitment_moved_across_a_week_boundary_leaves_one_solve_for_each_week(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # Both sides: the week it left now holds free time its solve read as occupied, and the week it
    # arrived in holds occupancy its own solve read as free. Two weeks, two operations, because the
    # single-flight invariant is per week.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK, NEXT_WEEK)

    await synced(sessions, tenant_id, source, a_read(an_event(start=NEXT_WEDNESDAY_1000)))

    assert weeks_of(await pending_solves(sessions, tenant_id)) == [str(WEEK), str(NEXT_WEEK)]


async def test_the_solve_a_poll_asks_for_is_due_at_the_end_of_the_debounce_window(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    """Nothing here is immediate, which is what lets several feeds landing together coalesce.

    An immediate request would pull the due instant to now on every pass, so a tenant with four
    timetable feeds would solve each week up to four times per tick instead of once.
    """
    await track(sessions, tenant_id, WEEK)

    await synced(sessions, tenant_id, source, a_read(an_event()))

    scheduled = [one.scheduled_for for one in await pending_solves(sessions, tenant_id)]
    assert scheduled == [NOW + DEBOUNCE]


async def test_a_second_changed_pass_joins_the_pending_solve_rather_than_adding_one(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    """One pending operation per week however many passes ask, which is the coordinator's rule.

    Asserted here rather than assumed, because it is what makes "one per affected week" a property
    of the table rather than of how many times the poll happened to run.
    """
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)
    await synced(
        sessions, tenant_id, source, a_read(an_event(start=WEDNESDAY_1000 + timedelta(hours=3)))
    )

    await synced(
        sessions, tenant_id, source, a_read(an_event(start=WEDNESDAY_1000 + timedelta(hours=5)))
    )

    assert weeks_of(await pending_solves(sessions, tenant_id)) == [str(WEEK)]


# --------------------------------------------------------------------------------
# The three non-changes leave none.
# --------------------------------------------------------------------------------


async def test_a_read_that_changed_nothing_leaves_no_pending_solve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # THE ordinary case. A steady feed republishes every component on every poll, so a pass that
    # enqueued on every attempt would supersede this week's solve every fifteen minutes forever.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    await synced(sessions, tenant_id, source, a_read(an_event()))

    assert await pending_solves(sessions, tenant_id) == []


async def test_two_consecutive_polls_that_changed_nothing_leave_no_pending_solve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # The loop this closes is the sequence rather than one pass: a poll that enqueued because the
    # previous poll had enqueued would hold the week superseded for as long as the feed exists.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    await synced(sessions, tenant_id, source, a_read(an_event()))
    first = await pending_solves(sessions, tenant_id)
    await synced(sessions, tenant_id, source, a_read(an_event()))

    assert first == []
    assert await pending_solves(sessions, tenant_id) == []


async def test_a_feed_that_answered_unchanged_leaves_no_pending_solve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A 304 means the last parse still stands, so no occupancy moved and no solve read anything
    # wrongly. The pass still clears the possibly-stale flag, so it is a pass that WROTE and asked
    # for nothing.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    await synced(sessions, tenant_id, source, an_unchanged_feed())

    assert await pending_solves(sessions, tenant_id) == []


async def test_a_failed_sync_leaves_no_pending_solve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # A feed being down is not evidence that a lecture was cancelled. The anchors are retained and
    # marked possibly stale, and asking for a solve here would make an unreachable publisher
    # supersede this week's plan every fifteen minutes.
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, WEEK)

    await synced(sessions, tenant_id, source, an_unreachable_feed())

    assert await pending_solves(sessions, tenant_id) == []


async def test_an_excluded_source_leaves_no_pending_solve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    # It is not fetched at all, so nothing about the tenant's commitments changed.
    await track(sessions, tenant_id, WEEK)

    await synced(sessions, tenant_id, replace(source, included=False), a_read(an_event()))

    assert await pending_solves(sessions, tenant_id) == []


# --------------------------------------------------------------------------------
# The bound: only the weeks the counter moved.
# --------------------------------------------------------------------------------


async def test_a_week_nobody_has_planned_is_not_asked_to_solve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    """No version row, so the counter left it alone and this leaves it alone for the same reason.

    A week with no row has no plan and no running solve to invalidate. A solve of one would produce
    a plan for a week nothing has planned, and the number of such weeks is the publisher's to
    decide: a component's accepted length is bounded in days, so one of them can reach every week
    of a year.
    """
    await synced(sessions, tenant_id, source, a_read(an_event()))

    assert await pending_solves(sessions, tenant_id) == []


async def test_only_the_planned_side_of_a_move_across_a_boundary_is_asked_to_solve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    """The discriminating case for the bound, and why the test above is not enough on its own.

    One pass invalidates two weeks and exactly one of them holds a plan. A pass that asked for
    every week it touched would pass the tracked cases above, and this one is what notices.
    """
    await synced(sessions, tenant_id, source, a_read(an_event()))
    await track(sessions, tenant_id, NEXT_WEEK)

    await synced(sessions, tenant_id, source, a_read(an_event(start=NEXT_WEDNESDAY_1000)))

    assert weeks_of(await pending_solves(sessions, tenant_id)) == [str(NEXT_WEEK)]


async def test_a_week_between_two_commitments_a_term_apart_is_not_asked_to_solve(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
) -> None:
    """One span is read, so the weeks inside it that the pass did not change have to drop.

    Two commitments a fortnight apart leave the week between them untouched, and that week holds a
    plan, so it is a row the span's read returns and the intersection has to reject.
    """
    between = NEXT_WEEK
    await track(sessions, tenant_id, WEEK, between, IsoWeek(2026, 9))

    await synced(
        sessions,
        tenant_id,
        source,
        a_read(
            an_event("near@example.ac.uk", start=WEDNESDAY_1000),
            an_event("far@example.ac.uk", start=WEDNESDAY_1000 + timedelta(days=14)),
        ),
    )

    assert weeks_of(await pending_solves(sessions, tenant_id)) == [
        str(WEEK),
        str(IsoWeek(2026, 9)),
    ]
