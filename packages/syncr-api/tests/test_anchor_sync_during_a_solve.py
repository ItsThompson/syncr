"""A calendar sync landing during a running solve, against a real Postgres.

The window is the whole point and it is not narrow in practice: a solve is roughly a second and a
half, and the poll that reads a timetable runs on its own schedule. So a lecture moving between the
instant a solve loads its inputs and the instant it writes is an ordinary event rather than a
contrived one.

The interleaving, driven at the only instant it can be:

```
 t0  a solve is claimed and LOADS its inputs   ──▶ stamped at version V
 t1  a sync moves a commitment in that week    ──▶ the week's inputs changed, V becomes V+1
 t2  the solve finishes and takes the row lock ──▶ V+1 != V, so it is SUPERSEDED and writes nothing
 t3  the follow-up loads the week again        ──▶ guarded on V+1, which is the occupancy that holds
```

Without the bump at t1 the guard matches, the solve adopts, and the plan of record describes a week
where a lecture sits in an hour the timetable has already moved it out of. Nothing later corrects
it: the solve reported success, so no follow-up is enqueued.

**The control is the same interleaving with a poll that changed nothing.** A steady feed republishes
every component on every poll, and if that were enough to invalidate, no solve of the week would
reach a write at all: each supersession enqueues a follow-up, and the poll fifteen minutes later
supersedes that. So the suite asserts both answers, because only the pair distinguishes a guard that
fires on a change from one that fires on an attempt.

The sync is driven through the reconciler rather than through a whole ``SourceSyncer``. Which of the
three attempts a pass takes is ``tests/test_anchor_sync_routing.py``'s subject, and composing an
adapter here would put a feed parse between the assertion and what it is about.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select

from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, ICS
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.db import create_database, create_db_engine, create_sessionmaker
from syncr_api.core.settings import (
    DEFAULT_SOLVE_DEBOUNCE_MS,
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.authority import classify
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import PENDING, SUCCEEDED, SUPERSEDED
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.solving.models import Operation
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.repository import DayTypeRepository, WeekPatternRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_api.worker.main import WorkerContext
from syncr_domain.intervals import Interval
from syncr_domain.tasks import Priority
from syncr_domain.templates import WeekPattern
from syncr_domain.weeks import IsoWeek, Weekday
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.calendars.records import CalendarSourceRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
WEEK = IsoWeek(2026, 7)
# Wednesday morning of the week, so the week has a past and a future and the solve has somewhere to
# place work.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
# Wednesday afternoon of the same week, and the hour the timetable moves it to. Both inside WEEK, so
# the sync invalidates exactly the week being solved and nothing else is in play.
LECTURE_AT = datetime(2026, 2, 11, 14, 0, tzinfo=UTC)
MOVED_TO = LECTURE_AT + timedelta(hours=1)

TIMETABLE = "https://example.ac.uk/timetable.ics"
LECTURE_UID = "lecture@example.ac.uk"


class Ticking:
    """A clock a test moves by hand, so the solve and the sync are ordered by intent."""

    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, by: timedelta) -> None:
        self.at += by


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
def clock() -> Ticking:
    return Ticking()


@pytest.fixture
async def context(live_database_url: str) -> AsyncIterator[WorkerContext]:
    worker = build_service_settings(service=WORKER_SERVICE, env=EnvSettings(_env_file=None))
    database = create_database(live_database_url)
    yield WorkerContext(settings=worker, database=database)
    await database.engine.dispose()


async def declare_the_minimum(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    """A home zone, one Area, a day shape, a weight set, and one task the solver can place.

    The task is what makes the write reachable: a week with an Area and no content solves to an
    empty document, which classifies as nothing and appends no revision, so the control would be
    asserting about a solve that had nothing to write either way.
    """
    async with sessions() as session, session.begin():
        settings = SettingsRepository(session, tenant_id)
        locked = await settings.lock(created_at=NOW)
        await settings.write(
            visible_hours=locked.visible_hours,
            day_start=locked.day_start,
            day_end=locked.day_end,
            review_cadence=locked.review_cadence,
            home_zone=LONDON,
        )
        area = await AreaRepository(session, tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(30),
            floor_hours=Decimal(3),
            created_at=NOW,
        )
        day_type = await DayTypeRepository(session, tenant_id).create(
            name="Weekday", created_at=NOW
        )
        await WeekPatternRepository(session, tenant_id).replace(
            WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )
        await TaskRepository(session, tenant_id).create(
            area_id=area.id,
            project_id=None,
            title="Interview preparation",
            estimate_minutes=120,
            deadline=None,
            priority=Priority.NORMAL,
            min_chunk_minutes=30,
            splittable=True,
            created_at=NOW,
        )
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)


async def a_source(
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


def a_lecture(*, start: datetime) -> RawEvent:
    return RawEvent(
        uid=LECTURE_UID,
        series_uid=None,
        title="Computer Science Lecture",
        interval=Interval(start, start + timedelta(hours=2)),
        location="Lecture Theatre 3",
        sequence=0,
        all_day=False,
    )


async def synced(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    source: CalendarSourceRecord,
    *,
    lecture_at: datetime,
    clock: Ticking,
) -> None:
    """One poll of the timetable, composed the way both of production's compositions do.

    The counter and the home zone are what production hands the reconciler, so the invalidation
    this performs is the one a real poll performs rather than one arranged here.
    """
    events = (a_lecture(start=lecture_at),)
    async with sessions() as session, session.begin():
        reconciler = AnchorReconciler(
            AnchorRepository(session, tenant_id),
            AnchorTypeRepository(session, tenant_id),
            versions=TrackedWeekInputVersions(
                WeekInputVersionRepository(session, tenant_id), clock=clock
            ),
            home_zone=LONDON,
        )
        await reconciler.reconcile(
            source,
            FetchOutcome(events=events, events_read=1, placed=1, reparsed=True),
        )


async def requested(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> OperationRecord:
    async with sessions() as session, session.begin():
        return await build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).request_solve(WEEK, 1, immediate=True)


async def claimed(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> OperationRecord:
    async with sessions() as session, session.begin():
        claim = await build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).claim_next()
    assert claim is not None, "the coordinator had no due operation to claim"
    return claim


def a_dispatch(context: WorkerContext, tenant_id: TenantId, clock: Ticking) -> SolveDispatch:
    return SolveDispatch(
        context.database,
        tenant_id,
        clock=clock,
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
    )


async def holds(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, version: int, clock: Ticking
) -> bool:
    """Whether the week is still at ``version``: the guard the dispatch's write is made under.

    Asked in its own transaction, which releases the row lock immediately. The row already exists
    here, so this creates nothing and the answer is a read.
    """
    async with sessions() as session, session.begin():
        return await WeekInputVersionRepository(session, owner.tenant_id).holds_version(
            WEEK, version, at=clock()
        )


async def revisions_of(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> Any:
    async with sessions() as session:
        return await PlanRepository(session, tenant_id).latest(WEEK)


async def pending_solves(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[Operation]:
    async with sessions() as session:
        found = await session.scalars(
            select(Operation)
            .where(Operation.tenant_id == tenant_id, Operation.status == PENDING)
            .order_by(Operation.scheduled_for)
        )
    return list(found)


async def a_first_bump(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> int:
    """The version row the week arrives at the solve with, as some earlier mutation left it."""
    async with sessions() as session, session.begin():
        return await WeekInputVersionRepository(session, owner.tenant_id).bump(WEEK, at=clock())


class TestASyncLandingDuringARunningSolve:
    async def test_a_moved_commitment_supersedes_the_solve_and_it_writes_nothing(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """The guard, driven at the only instant it can fire: after the load, before the write.

        Asserted through ``holds_version`` as well as through the status, because that is the
        statement the write is made under: the version the solve stamped when it loaded is no longer
        the version the row holds, so the write transaction carries no revision at all.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        source = await a_source(sessions, owner.tenant_id)
        await synced(sessions, owner.tenant_id, source, lecture_at=LECTURE_AT, clock=clock)
        await a_first_bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim = await claimed(sessions, owner, clock)
        dispatch = a_dispatch(context, owner.tenant_id, clock)
        loaded = await dispatch._loaded(claim, WEEK)

        await synced(sessions, owner.tenant_id, source, lecture_at=MOVED_TO, clock=clock)

        assert await holds(sessions, owner, loaded.input_version, clock) is False
        solved = await dispatch._solved(loaded, WEEK)
        finished = await dispatch._written(
            claim,
            WEEK,
            loaded,
            solved,
            classify(loaded.inputs.live_plan, solved.document, now=loaded.inputs.now),
        )

        assert finished.status == SUPERSEDED
        assert finished.status != SUCCEEDED
        assert await revisions_of(sessions, owner.tenant_id) is None

    async def test_a_poll_that_changed_nothing_leaves_the_solve_free_to_write(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """The control, and the failure it rules out.

        The same interleaving with the same feed publishing the same lecture: the poll changes
        nothing, so the version does not move and the solve writes. Without this, a guard that
        fired on every attempt would pass the test above, and a fifteen-minute poll would hold every
        week of the plan superseded forever while every counter read healthy.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        source = await a_source(sessions, owner.tenant_id)
        await synced(sessions, owner.tenant_id, source, lecture_at=LECTURE_AT, clock=clock)
        await a_first_bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim = await claimed(sessions, owner, clock)
        dispatch = a_dispatch(context, owner.tenant_id, clock)
        loaded = await dispatch._loaded(claim, WEEK)

        await synced(sessions, owner.tenant_id, source, lecture_at=LECTURE_AT, clock=clock)

        assert await holds(sessions, owner, loaded.input_version, clock) is True
        solved = await dispatch._solved(loaded, WEEK)
        finished = await dispatch._written(
            claim,
            WEEK,
            loaded,
            solved,
            classify(loaded.inputs.live_plan, solved.document, now=loaded.inputs.now),
        )

        assert finished.status == SUCCEEDED
        written = await revisions_of(sessions, owner.tenant_id)
        assert written is not None
        assert written.document["blocks"]

    async def test_the_follow_up_is_guarded_on_the_version_the_sync_left(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """What makes the supersession a step forward rather than a discard.

        Exactly one follow-up is enqueued, and it loads the week at the version the sync left, so
        the plan it produces is against the occupancy the timetable now publishes. A second
        supersession here would be the loop the closed range exists to prevent.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        source = await a_source(sessions, owner.tenant_id)
        await synced(sessions, owner.tenant_id, source, lecture_at=LECTURE_AT, clock=clock)
        await a_first_bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim = await claimed(sessions, owner, clock)
        dispatch = a_dispatch(context, owner.tenant_id, clock)
        loaded = await dispatch._loaded(claim, WEEK)
        await synced(sessions, owner.tenant_id, source, lecture_at=MOVED_TO, clock=clock)
        solved = await dispatch._solved(loaded, WEEK)
        await dispatch._written(
            claim,
            WEEK,
            loaded,
            solved,
            classify(loaded.inputs.live_plan, solved.document, now=loaded.inputs.now),
        )

        clock.advance(timedelta(seconds=5))
        pending = await pending_solves(sessions, owner.tenant_id)
        follow_up = await claimed(sessions, owner, clock)
        again = a_dispatch(context, owner.tenant_id, clock)
        reloaded = await again._loaded(follow_up, WEEK)

        assert len(pending) == 1
        assert follow_up.id != claim.id
        assert reloaded.input_version == loaded.input_version + 1
        assert await holds(sessions, owner, reloaded.input_version, clock) is True
