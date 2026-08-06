"""Duty 1 against a real Postgres: the plan that exists because time passed.

This is the checkpoint's headline capability and it has no other producer, so what it does has to be
driven end to end rather than through fakes: the pass reads eight tables, appends a revision through
the real append-only repository, and leaves an operation and a projection behind.

Six groups.

**A week nobody has touched gets a plan.** The revision's reason is ``horizon_advanced``, an
operation of kind ``materialize`` records that it happened, the week's input version is bumped
because the live plan is a solve input, and a projection is queued.

**It is idempotent.** A second pass creates no operation and appends no revision, which is what
makes a fifteen-minute cadence free.

**One instant, and chronological order.** Every revision a pass appends carries the same
``created_at``, because ``now`` is read once; and the weeks are planned oldest first, which is what
matters on first run.

**Minimum inputs missing does nothing.** Guessing at a plan without Areas would be worse than
showing why one cannot exist, so no operation and no revision appear, and the gauge says the horizon
has a hole.

**The horizon's length is the write target's.** Widening it brings the newly covered weeks in on the
next tick and bumps their input versions.

**A read never triggers a materialization or a solve.** Every parameterless GET route under the api
prefix is driven and the operation and revision counts are compared before and after: navigating
between weeks is not a mutation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.repository import AreaRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, HORIZON_DAYS_DEFAULT, ICS, WRITE_TARGET
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import (
    create_database,
    create_db_engine,
    create_db_lifespan,
    create_sessionmaker,
)
from syncr_api.core.settings import (
    API_PREFIX,
    DEV_ALLOWED_ORIGINS,
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.horizon.config import MAINTAINER_INTERVAL, MaintainerDuty
from syncr_api.horizon.maintainer import HorizonPass, PlanHorizonMaintainer
from syncr_api.horizon.runner import PlanHorizonRunner
from syncr_api.horizon.weeks import next_local_midnight
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.production import WeekProducer
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import plan_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import MATERIALIZE, PENDING, PROJECTION, SUCCEEDED
from syncr_api.solving.models import Operation
from syncr_api.solving.repository import OperationRepository
from syncr_api.templates.repository import DayTypeRepository, WeekPatternRepository
from syncr_api.user_settings.models import Settings
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.worker.main import WorkerContext
from syncr_common.metrics import REGISTRY
from syncr_domain.plan import RevisionReason
from syncr_domain.templates import WeekPattern
from syncr_domain.weeks import IsoWeek, Weekday
from tests.boundaries import read_paths
from tests.live_tenants import PASSWORD, delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
AUCKLAND = "Pacific/Auckland"
BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# Monday of 2026-W07, mid-morning in London, so a fortnight's horizon covers W07 and W08 and the
# week list is the two-week case rather than the three-week one.
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
LAST_WEEK = IsoWeek(2026, 6)
THIS_WEEK = IsoWeek(2026, 7)
NEXT_WEEK = IsoWeek(2026, 8)
THIRD_WEEK = IsoWeek(2026, 9)

# A fortnight from a Monday touches two weeks; three weeks needs one more day than the fortnight's
# last, so 15 days is the shortest widening that brings a third week in.
THREE_WEEKS_OF_DAYS = 15


class Ticking:
    """A clock that advances a millisecond per read, as a real one does.

    Two assertions rest on that. Every operation one pass creates takes a distinct
    ``scheduled_for``, so the order the weeks were planned in is readable from the rows. And every
    revision one pass appends carries the SAME ``created_at``, because the pass reads the clock
    once and passes that instant down: a pass reading it per week would stamp each revision
    differently.
    """

    STEP = timedelta(milliseconds=1)

    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        read = self.at
        self.at += self.STEP
        return read

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
async def other_owner(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[UserRecord]:
    account = await seed_owner(sessions)
    yield account
    await delete_tenant(sessions, account.tenant_id)


@pytest.fixture
def clock() -> Ticking:
    return Ticking()


@pytest.fixture
async def context(live_database_url: str) -> AsyncIterator[WorkerContext]:
    """A worker context over the live database, as the worker process composes one."""
    worker = build_service_settings(service=WORKER_SERVICE, env=EnvSettings(_env_file=None))
    database = create_database(live_database_url)
    yield WorkerContext(settings=worker, database=database)
    await database.engine.dispose()


async def declare_the_minimum(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, home_zone: str = LONDON
) -> None:
    """Areas, a day shape, a weight set, and a home zone: the least a plan can exist from.

    Deliberately less than a declared week. What the maintainer decides is whether a week HAS a
    plan and whether one CAN exist, and a fuller week would make this suite a second test of the
    assembler's resolutions.
    """
    async with sessions() as session, session.begin():
        settings = SettingsRepository(session, tenant_id)
        locked = await settings.lock(created_at=NOW)
        await settings.write(
            visible_hours=locked.visible_hours,
            day_start=locked.day_start,
            day_end=locked.day_end,
            review_cadence=locked.review_cadence,
            home_zone=home_zone,
        )
        await AreaRepository(session, tenant_id).create(
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
        await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)


async def declare_a_write_target(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, horizon_days: int
) -> None:
    """A projection target with a stated horizon, which is what decides how many weeks are kept."""
    async with sessions() as session, session.begin():
        sources = CalendarSourceRepository(session, tenant_id)
        target = await sources.create(
            provider=ICS,
            role=ANCHOR_SOURCE,
            display_name="Phone",
            external_id="https://example.test/plan.ics",
            included=True,
            horizon_days=None,
            created_at=NOW,
        )
        await sources.designate_write_target(target.id, horizon_days=horizon_days)


async def revisions_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[PlanRevision]:
    async with sessions() as session:
        found = await session.scalars(
            select(PlanRevision)
            .where(PlanRevision.tenant_id == tenant_id)
            .order_by(PlanRevision.iso_week)
        )
        return list(found)


async def operations_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[Operation]:
    async with sessions() as session:
        found = await session.scalars(
            select(Operation)
            .where(Operation.tenant_id == tenant_id)
            .order_by(Operation.scheduled_for, Operation.kind)
        )
        return list(found)


async def a_pass(
    context: WorkerContext, clock: Ticking, *, now: datetime | None = None
) -> datetime:
    """One maintainer pass over every tenant, at one instant read from the clock."""
    return await PlanHorizonRunner(clock=clock).plan(context, now=now or clock())


def weeks_without_a_plan() -> float:
    """The gauge, read as a scraper reads it rather than through a private attribute."""
    return _sample("syncr_horizon_weeks_without_plan")


def tenant_pass_failures() -> float:
    """The contained-fault counter, read the same way."""
    return _sample("syncr_horizon_tenant_failures_total")


def _sample(family: str) -> float:
    sample = REGISTRY.get_sample_value(family)
    assert sample is not None, f"{family} is not in the registry"
    return sample


# --------------------------------------------------------------------------------
# A week nobody has touched gets a plan
# --------------------------------------------------------------------------------


async def test_a_horizon_week_with_no_plan_is_planned(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    await declare_the_minimum(sessions, owner.tenant_id)

    await a_pass(context, clock)

    appended = await revisions_of(sessions, owner.tenant_id)
    assert [row.iso_week for row in appended] == [str(THIS_WEEK), str(NEXT_WEEK)]
    assert {row.reason for row in appended} == {RevisionReason.HORIZON_ADVANCED.value}


def test_the_reason_a_maintained_week_states_is_not_the_one_a_fallback_states() -> None:
    """The two paths through one materialization are told apart by the history they leave."""
    reasons = {RevisionReason.HORIZON_ADVANCED.value, RevisionReason.MATERIALIZED.value}

    assert len(reasons) == 2


async def test_the_plan_it_appends_is_a_document_the_domain_can_rebuild(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """The one place a stored document is written by production code rather than by a test."""
    await declare_the_minimum(sessions, owner.tenant_id)

    await a_pass(context, clock)

    first, _next_week = await revisions_of(sessions, owner.tenant_id)
    rebuilt = plan_document(first.document)
    assert rebuilt.iso_week == THIS_WEEK
    assert set(rebuilt.zone_by_date) == set(THIS_WEEK.dates())


async def test_an_operation_records_that_the_week_was_materialized(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    await declare_the_minimum(sessions, owner.tenant_id)

    await a_pass(context, clock)

    materializations = [
        one for one in await operations_of(sessions, owner.tenant_id) if one.kind == MATERIALIZE
    ]
    assert len(materializations) == 2
    assert {one.status for one in materializations} == {SUCCEEDED}
    assert all(one.result_revision_id is not None for one in materializations)
    assert all(one.started_at is not None for one in materializations), "it ran, so it was claimed"


async def test_a_projection_is_queued_for_each_week_it_planned(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """The queue is the operations table, so the maintainer leaves work rather than doing it."""
    await declare_the_minimum(sessions, owner.tenant_id)

    await a_pass(context, clock)

    projections = [
        one for one in await operations_of(sessions, owner.tenant_id) if one.kind == PROJECTION
    ]
    assert [one.iso_week for one in projections] == [str(THIS_WEEK), str(NEXT_WEEK)]
    assert {one.status for one in projections} == {PENDING}


async def test_the_weeks_input_version_is_bumped_because_the_live_plan_changed(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """A week nobody had touched has no version row at all, so the plan is its first reference."""
    await declare_the_minimum(sessions, owner.tenant_id)
    async with sessions() as session:
        assert await WeekInputVersionRepository(session, owner.tenant_id).current(THIS_WEEK) is None

    await a_pass(context, clock)

    async with sessions() as session:
        assert await WeekInputVersionRepository(session, owner.tenant_id).current(THIS_WEEK) == 1


# --------------------------------------------------------------------------------
# It is idempotent
# --------------------------------------------------------------------------------


async def test_a_second_pass_creates_no_operation_and_appends_no_revision(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """Running it twice costs nothing, which is what makes a quarter-hour cadence free."""
    await declare_the_minimum(sessions, owner.tenant_id)
    await a_pass(context, clock)
    after_one = (
        len(await revisions_of(sessions, owner.tenant_id)),
        len(await operations_of(sessions, owner.tenant_id)),
    )

    await a_pass(context, clock)

    assert (
        len(await revisions_of(sessions, owner.tenant_id)),
        len(await operations_of(sessions, owner.tenant_id)),
    ) == after_one


async def test_a_week_that_already_has_a_plan_is_skipped(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """Skipped by a read of the live revision, which is one indexed read per horizon week."""
    await declare_the_minimum(sessions, owner.tenant_id)
    async with sessions() as session, session.begin():
        tally = await PlanHorizonMaintainer(session, owner.tenant_id, clock).plan(
            THIS_WEEK, now=NOW
        )
    assert tally.planned == 1

    async with sessions() as session, session.begin():
        again = await PlanHorizonMaintainer(session, owner.tenant_id, clock).plan(
            THIS_WEEK, now=NOW
        )

    assert (again.already_planned, again.planned) == (1, 0)


# --------------------------------------------------------------------------------
# One instant, and chronological order
# --------------------------------------------------------------------------------


async def test_every_revision_a_pass_appends_carries_one_instant(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """``now`` is read once and passed down, so a tick's decisions share one instant.

    The clock advances on every read, so a pass that read it per week would stamp each revision
    differently. At 00:00 those two readings would name different local dates, and the week brought
    in would not be the week planned.
    """
    await declare_the_minimum(sessions, owner.tenant_id)

    await a_pass(context, clock)

    stamps = {row.created_at for row in await revisions_of(sessions, owner.tenant_id)}
    assert len(stamps) == 1


async def test_the_weeks_are_planned_oldest_first(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """Which matters on first run: the week the user is looking at exists before the others.

    Readable from the rows because the clock advances per read, so each operation's own
    ``scheduled_for`` records when it was created within the pass.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    await declare_a_write_target(sessions, owner.tenant_id, horizon_days=THREE_WEEKS_OF_DAYS)

    await a_pass(context, clock)

    ordered = [
        one.iso_week
        for one in sorted(
            (
                one
                for one in await operations_of(sessions, owner.tenant_id)
                if one.kind == MATERIALIZE
            ),
            key=lambda one: one.scheduled_for,
        )
    ]
    assert ordered == [str(THIS_WEEK), str(NEXT_WEEK), str(THIRD_WEEK)]


# --------------------------------------------------------------------------------
# Minimum inputs missing does nothing
# --------------------------------------------------------------------------------


async def test_a_week_whose_minimum_inputs_are_missing_is_left_alone(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """A tenant with no Areas and no day shape: nothing is created and nothing is appended.

    The weight set is seeded so the readiness guard is the ONLY thing in the way. Without it the
    production path would refuse for a different reason, and this would pass whether the guard
    existed or not.
    """
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)

    await a_pass(context, clock)

    assert await revisions_of(sessions, owner.tenant_id) == []
    assert await operations_of(sessions, owner.tenant_id) == []


async def test_such_a_week_is_counted_as_not_ready_rather_than_as_a_failure(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> None:
    """The tally distinguishes the two, because the log line an operator reads is different.

    Both leave the horizon with a hole and both reach the gauge, so the gauge alone cannot tell them
    apart: this is what says the week was skipped deliberately rather than that something broke.
    """
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)

    async with sessions() as session, session.begin():
        tally = await PlanHorizonMaintainer(session, owner.tenant_id, clock).plan(
            THIS_WEEK, now=NOW
        )

    assert tally == HorizonPass(weeks=1, not_ready=1)


async def test_a_tenant_with_areas_but_no_day_shape_is_still_left_alone(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """Both minimum inputs are minimum: a day shape is what materializes anything at all."""
    async with sessions() as session, session.begin():
        await AreaRepository(session, owner.tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(30),
            floor_hours=Decimal(3),
            created_at=NOW,
        )
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)

    await a_pass(context, clock)

    assert await revisions_of(sessions, owner.tenant_id) == []


async def test_the_gauge_sits_at_zero_once_every_horizon_week_is_planned(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    await declare_the_minimum(sessions, owner.tenant_id)

    await a_pass(context, clock)

    assert weeks_without_a_plan() == 0


async def test_the_gauge_counts_a_week_no_plan_can_exist_for(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """A week the maintainer cannot plan is still a week inside the horizon with nothing to project.

    Which is what the alert reads: a sustained non-zero value is the failure that would otherwise
    reach the user as a calendar going blank at a week boundary.
    """
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)

    await a_pass(context, clock)

    assert weeks_without_a_plan() > 0


async def test_the_tick_is_timed_under_its_own_duty(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """Labeled by duty, because the second duty's cost is unrelated to this one's."""
    await declare_the_minimum(sessions, owner.tenant_id)
    runner = PlanHorizonRunner(clock=clock)
    await runner(context)  # the first tick schedules
    clock.advance(MAINTAINER_INTERVAL)

    await runner(context)

    counted = REGISTRY.get_sample_value(
        "syncr_maintainer_tick_duration_seconds_count", {"duty": MaintainerDuty.HORIZON.value}
    )
    assert counted == 1


async def test_a_tenant_whose_week_raises_does_not_stop_another_tenants(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    other_owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """One week's fault is contained to that week, so the pass finishes and the rest are planned.

    The broken tenant has Areas and a day shape but no active weight set, which the producer refuses
    rather than planning around: it is the reachable fault that is not a bug in this suite.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    async with sessions() as session, session.begin():
        await AreaRepository(session, other_owner.tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(30),
            floor_hours=Decimal(3),
            created_at=NOW,
        )
        day_type = await DayTypeRepository(session, other_owner.tenant_id).create(
            name="Weekday", created_at=NOW
        )
        await WeekPatternRepository(session, other_owner.tenant_id).replace(
            WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )

    await a_pass(context, clock)

    assert len(await revisions_of(sessions, owner.tenant_id)) == 2, "a fault stopped a good tenant"
    assert await revisions_of(sessions, other_owner.tenant_id) == []
    assert weeks_without_a_plan() == 2, "the broken tenant's two horizon weeks"


async def test_the_gauge_does_not_grow_across_passes(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """It measures a state, so it is SET from the pass's tally rather than nudged per week.

    A gauge incremented per week would read two after one pass and four after two, which the alert
    would report as a horizon getting worse while nothing changed.
    """
    async with sessions() as session, session.begin():
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)

    await a_pass(context, clock)
    after_one = weeks_without_a_plan()
    await a_pass(context, clock)

    assert weeks_without_a_plan() == after_one
    assert after_one > 0, "the assertion above would hold at zero for the wrong reason"


# --------------------------------------------------------------------------------
# The horizon's length is the write target's
# --------------------------------------------------------------------------------


async def test_widening_the_horizon_brings_the_newly_covered_week_in_on_the_next_tick(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    await declare_the_minimum(sessions, owner.tenant_id)
    await declare_a_write_target(sessions, owner.tenant_id, horizon_days=HORIZON_DAYS_DEFAULT)
    await a_pass(context, clock)
    assert [row.iso_week for row in await revisions_of(sessions, owner.tenant_id)] == [
        str(THIS_WEEK),
        str(NEXT_WEEK),
    ]

    async with sessions() as session, session.begin():
        sources = CalendarSourceRepository(session, owner.tenant_id)
        (target,) = [one for one in await sources.list_all() if one.role == WRITE_TARGET]
        await sources.set_horizon(target.id, horizon_days=THREE_WEEKS_OF_DAYS)
    await a_pass(context, clock)

    assert [row.iso_week for row in await revisions_of(sessions, owner.tenant_id)] == [
        str(THIS_WEEK),
        str(NEXT_WEEK),
        str(THIRD_WEEK),
    ]


async def test_the_newly_covered_weeks_input_version_is_bumped_too(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    await declare_the_minimum(sessions, owner.tenant_id)
    await declare_a_write_target(sessions, owner.tenant_id, horizon_days=THREE_WEEKS_OF_DAYS)

    await a_pass(context, clock)

    async with sessions() as session:
        versions = WeekInputVersionRepository(session, owner.tenant_id)
        assert await versions.current(THIRD_WEEK) == 1


async def test_a_tenant_with_no_write_target_still_has_its_weeks_planned(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """The horizon falls back to the default, so planning does not wait on a projection bound."""
    await declare_the_minimum(sessions, owner.tenant_id)

    await a_pass(context, clock)

    assert len(await revisions_of(sessions, owner.tenant_id)) == 2


async def test_the_horizon_starts_on_the_tenants_local_date_rather_than_the_utc_one(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """Thirteen hours east, the UTC date is still in the PREVIOUS ISO week.

    At this instant Auckland is on Monday of 2026-W07 while UTC is on Sunday of 2026-W06, so a
    horizon computed in UTC would plan the week the user finished yesterday and stop one week short
    of the one they are looking at. Nothing else in this suite can see that: in London in February
    the two dates are the same.
    """
    await declare_the_minimum(sessions, owner.tenant_id, home_zone=AUCKLAND)
    sunday_in_utc = datetime(2026, 2, 8, 12, 0, tzinfo=UTC)
    assert sunday_in_utc.date().isocalendar().week == LAST_WEEK.week, "the fixture's own premise"

    await a_pass(context, Ticking(sunday_in_utc), now=sunday_in_utc)

    assert [row.iso_week for row in await revisions_of(sessions, owner.tenant_id)] == [
        str(THIS_WEEK),
        str(NEXT_WEEK),
    ]


# --------------------------------------------------------------------------------
# When the next pass is due
# --------------------------------------------------------------------------------


async def test_the_first_tick_schedules_rather_than_plans(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """A process that restarts often must not run a pass on every boot."""
    await declare_the_minimum(sessions, owner.tenant_id)
    runner = PlanHorizonRunner(clock=clock)

    await runner(context)

    assert await revisions_of(sessions, owner.tenant_id) == []
    assert runner.next_due_at is not None


async def test_the_next_pass_is_due_at_the_earlier_of_the_interval_and_local_midnight(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
) -> None:
    """Mid-morning, the interval is the earlier bound, so it is what the pass answers with."""
    await declare_the_minimum(sessions, owner.tenant_id)
    clock = Ticking(NOW)

    due = await a_pass(context, clock, now=NOW)

    assert due == NOW + MAINTAINER_INTERVAL
    assert due < next_local_midnight(NOW, LONDON)


async def test_close_to_midnight_the_midnight_is_the_earlier_bound(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
) -> None:
    """Which is the whole reason midnight is a trigger: the horizon advances AT the date change.

    Ten minutes before local midnight, a pure fifteen-minute cadence would next plan five minutes
    INTO the new day, so a week entering the horizon would wait out the remainder of a cycle whose
    phase a restart decides.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    ten_to_midnight = datetime(2026, 2, 9, 23, 50, tzinfo=UTC)
    clock = Ticking(ten_to_midnight)

    due = await a_pass(context, clock, now=ten_to_midnight)

    assert due == next_local_midnight(ten_to_midnight, LONDON)
    assert due < ten_to_midnight + MAINTAINER_INTERVAL


# --------------------------------------------------------------------------------
# A read never triggers a materialization or a solve
# --------------------------------------------------------------------------------


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


# The one read a request-response client cannot drive: an SSE body never ends, so a `GET` against it
# blocks until the connection is closed. Excluded here rather than everywhere, and named rather than
# filtered by shape, so adding a second endless route is a diff a reviewer reads as what it is. What
# the stream writes is asserted in `test_event_stream.py`, which drives the generator directly.
ENDLESS_READS: Final = frozenset({f"{API_PREFIX}/events"})


def parameterless_reads(settings: ServiceSettings) -> list[str]:
    """Every GET route under the api prefix that needs no path parameter and answers.

    The predicate is ``tests.boundaries.read_paths``, so this half and the parameterized half
    cannot overlap or leave a route in neither. A route WITH a parameter is left out here because a
    value has to be invented for it; the week view is the one that matters most and it drives its
    own half in ``test_week_routes_integration.py``.
    """
    return [
        path
        for path in read_paths(create_app(settings), parameterized=False)
        if path not in ENDLESS_READS
    ]


def test_every_endless_read_is_a_route_that_exists(settings: ServiceSettings) -> None:
    """So an exclusion cannot outlive the route it was written for and quietly widen the hole."""
    every = set(read_paths(create_app(settings), parameterized=False))

    assert every >= ENDLESS_READS


async def test_no_read_route_creates_an_operation_or_appends_a_revision(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    live_database_url: str,
    settings: ServiceSettings,
) -> None:
    """Navigating between weeks is not a mutation, so a read must leave both tables untouched."""
    await declare_the_minimum(sessions, owner.tenant_id)
    paths = parameterless_reads(settings)
    assert paths, "no parameterless read route was found, so this asserted nothing"

    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _sign_in(client, owner.email)
        for path in paths:
            answered = client.get(path, headers=headers)
            # A stated 503 is legitimate: a deployment with no Google client refuses that read
            # rather than faulting. What must not happen is a fault, because a route that raised
            # might have raised AFTER writing.
            assert answered.status_code != HTTPStatus.INTERNAL_SERVER_ERROR, (path, answered.text)
    await database.engine.dispose()

    assert await revisions_of(sessions, owner.tenant_id) == []
    assert await operations_of(sessions, owner.tenant_id) == []


async def test_counting_rows_would_have_caught_a_write(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """The control on the assertion above: the same two counts DO move when work is done.

    Without this, a suite whose row counts were read from the wrong tenant would pass the read test
    for the wrong reason.
    """
    await declare_the_minimum(sessions, owner.tenant_id)

    await a_pass(context, clock)

    assert await revisions_of(sessions, owner.tenant_id) != []
    assert await operations_of(sessions, owner.tenant_id) != []


def _sign_in(http: TestClient, email: str) -> dict[str, str]:
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


# --------------------------------------------------------------------------------
# The plan of last resort
# --------------------------------------------------------------------------------


async def test_materialize_week_appends_its_own_reason(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> None:
    """The fallback path, driven directly: its caller is the coordinator's terminal-failure branch.

    A test asserts the reason distinguishes it from the maintainer's own path, because the history
    is what says which produced a week: one exists because time passed and one because a solve
    could not.
    """
    await declare_the_minimum(sessions, owner.tenant_id)

    async with sessions() as session, session.begin():
        await _producer(session, owner.tenant_id, clock).materialize_week(THIS_WEEK, now=NOW)

    (appended,) = await revisions_of(sessions, owner.tenant_id)
    assert appended.reason == RevisionReason.MATERIALIZED.value


async def test_the_two_production_paths_leave_different_histories(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> None:
    await declare_the_minimum(sessions, owner.tenant_id)

    async with sessions() as session, session.begin():
        producer = _producer(session, owner.tenant_id, clock)
        await producer.advance_into(THIS_WEEK, now=NOW)
        await producer.materialize_week(NEXT_WEEK, now=NOW)

    reasons = {row.iso_week: row.reason for row in await revisions_of(sessions, owner.tenant_id)}
    assert reasons == {
        str(THIS_WEEK): RevisionReason.HORIZON_ADVANCED.value,
        str(NEXT_WEEK): RevisionReason.MATERIALIZED.value,
    }


async def test_a_tenant_with_no_active_weight_set_is_refused_rather_than_planned(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> None:
    """A revision records the weights in force, and a tenant with none was not created here.

    Provisioning seeds version 1 in the transaction that creates a tenant, so this is a corrupt
    tenant. Refused loudly, because the alternative is writing a version no row has.
    """
    from syncr_api.plans.production import NoWeightSetInForce

    async with sessions() as session, session.begin():
        await AreaRepository(session, owner.tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(30),
            floor_hours=Decimal(3),
            created_at=NOW,
        )

    with pytest.raises(NoWeightSetInForce):
        async with sessions() as session, session.begin():
            await _producer(session, owner.tenant_id, clock).advance_into(THIS_WEEK, now=NOW)


def _producer(session: AsyncSession, tenant_id: TenantId, clock: Ticking) -> WeekProducer:
    from syncr_api.plans.assembler import AssemblyCaller
    from syncr_api.plans.injection import build_week_assembler
    from syncr_api.solving.lifecycle import OperationLifecycle

    return WeekProducer(
        assembler=build_week_assembler(session, tenant_id, caller=AssemblyCaller.MAINTAINER),
        revisions=PlanRepository(session, tenant_id),
        versions=WeekInputVersionRepository(session, tenant_id),
        weights=WeightSetRepository(session, tenant_id),
        operations=OperationLifecycle(OperationRepository(session, tenant_id), clock),
    )


def test_the_row_counts_read_the_tables_the_duty_writes() -> None:
    """A control on the two helpers: they read the two tables the duty writes, and no others."""
    assert PlanRevision.__tablename__ == "plan_revisions"
    assert Operation.__tablename__ == "operations"


async def test_a_tenant_whose_zone_cannot_be_read_does_not_stop_another_tenants_pass(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    other_owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """The one fault that sits BEFORE the per-week boundary, so it needs its own.

    ``local_date`` resolves the stored ``home_zone`` through the zone layer, which refuses an
    identifier it does not know. Uncontained, that read aborts the pass: the tenants after it are
    never visited and, worse, ``HORIZON_WEEKS_WITHOUT_PLAN.set(...)`` is never reached. On a fresh
    process the gauge then reads zero and ``HorizonNotMaintained``, which fires above zero, cannot
    fire for a duty that fails on every pass. That is an alert inverted by a failure path.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    await declare_the_minimum(sessions, other_owner.tenant_id)
    async with sessions() as session, session.begin():
        # Written past the boundary that would have refused it, which is the only way this state
        # exists: the settings route validates a zone before storing one.
        await session.execute(
            update(Settings)
            .where(Settings.tenant_id == other_owner.tenant_id)
            .values(home_zone="Mars/Olympus_Mons")
        )
    before = tenant_pass_failures()

    await a_pass(context, clock)

    assert len(await revisions_of(sessions, owner.tenant_id)) == 2, "a fault stopped a good tenant"
    assert await revisions_of(sessions, other_owner.tenant_id) == []
    assert tenant_pass_failures() == before + 1
    assert weeks_without_a_plan() > 0, (
        "the gauge has to be set from what the pass DID reach, or the alert cannot fire for a "
        "tenant whose weeks are never planned"
    )


async def test_a_tenant_whose_zone_cannot_be_read_still_leaves_the_pass_due_again(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    clock: Ticking,
) -> None:
    """No midnight is knowable for that tenant, so the interval is the only bound left.

    A pass that answered with no due instant at all would never run again.
    """
    await declare_the_minimum(sessions, owner.tenant_id)
    async with sessions() as session, session.begin():
        await session.execute(
            update(Settings)
            .where(Settings.tenant_id == owner.tenant_id)
            .values(home_zone="Mars/Olympus_Mons")
        )

    due = await a_pass(context, clock, now=NOW)

    assert due == NOW + MAINTAINER_INTERVAL
