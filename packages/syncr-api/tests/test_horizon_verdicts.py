"""Duty 2 against a real Postgres: the transition nothing but the clock caused.

A week becomes impossible most often because earlier slack went unused, and no
mutation causes that: the user did nothing, the plan did not change, and Friday's deadline is now
unreachable. Reads are forbidden from writing, so without this duty the early-catch metric's
denominator would lose its most ordinary case while its numerator kept every session transition, and
the ratio would report a number better than the truth.

Seven groups.

**A week that becomes impossible because time passed is recorded, within one tick.** The tenant is
declared once and never touched again: the only thing that changes between the two ticks is the
clock.

**A tick that changes nothing writes nothing.** Which is what makes the fifteen-minute cadence free,
and what a verdict recomputed identically comes to.

**The maintainer writes on a ``feasible`` flip and never on a provenance change.** Its probe
re-derives provenance, so the tick after a solve would otherwise flip ``solver`` back to ``probe``
and the next solve would flip it back, forever.

**One instant per tick.** Every transition a tick records carries the same ``occurred_at``, and it
is the instant duty 1 stamped its revisions with.

**One transaction per week.** A week whose probe raises is contained, counted, and does not take
another week's transition with it, and a failure after the append leaves no row at all.

**The week list is the local one.** A tenant thirteen hours east probes the week its own date names.

**How the plan came to exist is not something this duty reads.** The transition is the same whether
the live revision was materialized or adopted from a solve, which is why a change to duty
1's producer cannot change duty 2.

**The solve usually speaks first.** Duty 1 leaves requests, not plans, and the worker's solve duty
realizes them inside the same loop, so a completed solve records its verdict on the SOLVE surface
before duty 2 probes. A first impossibility is therefore often that row; duty 2 adds only what is
still news, and the tests below read the EPISODE with each row's surface asserted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from syncr_api.areas.repository import AreaRepository
from syncr_api.core.db import create_database, create_db_engine, create_sessionmaker
from syncr_api.core.settings import (
    DEFAULT_SOLVE_DEBOUNCE_MS,
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.horizon.config import MAINTAINER_INTERVAL, MaintainerDuty
from syncr_api.horizon.metrics import TransitionDirection
from syncr_api.horizon.runner import PlanHorizonRunner
from syncr_api.horizon.verdicts import TimeDrivenVerdicts, VerdictPass
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.declarations import VerdictToRecord
from syncr_api.plans.facts import VerdictEvent
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.production import WeekProducer
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.surfaces import VerdictSurface
from syncr_api.plans.verdict_events import VerdictEventRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.injection import debounce_window
from syncr_api.solving.runner import SolveRunner
from syncr_api.tasks.repository import TaskRepository
from syncr_api.worker.main import WorkerContext
from syncr_common.metrics import REGISTRY
from syncr_domain.feasibility import Provenance, ShortfallKind
from syncr_domain.intervals import Interval
from syncr_domain.plan import RevisionReason
from syncr_domain.tasks import Priority
from tests.live_horizons import (
    AUCKLAND,
    CAPACITY_LEFT_MINUTES,
    LATE_IN_THE_WEEK,
    NEXT_WEEK,
    NOW,
    THIRD_WEEK,
    THIS_WEEK,
    Ticking,
)
from tests.live_minimums import AREA_FLOOR_HOURS, declare_the_minimum
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.records import VerdictEventRecord
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

pytestmark = pytest.mark.integration

# Sunday of 2026-W07 at 22:00 in London, where February is UTC. The week's span ends at the
# following Monday's local midnight, so two hours of capacity are left and the Area's three-hour
# floor cannot be reached: the gap is 60 minutes and nothing but the clock produced it.
FLOOR_MINUTES = int(AREA_FLOOR_HOURS) * 60
EXPECTED_GAP_MINUTES = FLOOR_MINUTES - CAPACITY_LEFT_MINUTES

# A fortnight away from the plan, covering both horizon weeks except the last hour of each. Both
# weeks are then impossible against the Area's three-hour floor from the FIRST tick, which is the
# only way two transitions can be recorded by one tick and the single-instant rule driven.
AWAY_FROM = datetime(2026, 2, 9, 0, 0, tzinfo=UTC)
AWAY_UNTIL = datetime(2026, 2, 22, 23, 0, tzinfo=UTC)


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
    """A worker context over the live database, as the worker process composes one."""
    worker = build_service_settings(service=WORKER_SERVICE, env=EnvSettings(_env_file=None))
    database = create_database(live_database_url)
    yield WorkerContext(settings=worker, database=database)
    await database.engine.dispose()


async def a_tick(context: WorkerContext, clock: Ticking) -> VerdictPass:
    """One whole maintainer tick, both duties, at one instant read from the clock.

    Driven through the runner rather than through duty 2 alone, because duty 2 runs over the weeks
    duty 1 resolved: a suite that called duty 2 with a week list of its own would not be driving the
    thing the worker runs. Answers with duty 2's tally.
    """
    now = clock()
    runner = PlanHorizonRunner(clock=clock)
    planned = await runner.plan(context, now=now)
    # The pass leaves requests, not plans. The worker's solve duty realizes them within one loop
    # of the debounce window, which is the step between duty 1 asking for a week and duty 2
    # probing it; a suite that probed without it would be driving a horizon nobody solved.
    clock.advance(debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS))
    await SolveRunner(clock=clock).drain(context)
    return await runner.record_transitions(context, planned.weeks, now=now)


async def declared(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    home_zone: str = "Europe/London",
) -> None:
    """The minimum, plus work in a SECOND, floorless Area that a solved week can hold.

    A solve of a week with nothing to place adopts nothing, and this suite's probe reads the
    live revision, so every tenant here declares content beside the minimum. The work sits in an
    Area with no floor deliberately: a placed block honours part of its own Area's floor, so a
    Career task would shrink the very gap the infeasible flips are asserted against.
    """
    await declare_the_minimum(sessions, tenant_id, home_zone=home_zone)
    async with sessions() as session, session.begin():
        areas = AreaRepository(session, tenant_id)
        health = await areas.create(
            parent_id=None,
            name="Health",
            pigment_index=2,
            budget_percent=Decimal(10),
            floor_hours=Decimal(0),
            created_at=NOW,
        )
        await TaskRepository(session, tenant_id).create(
            area_id=health.id,
            project_id=None,
            title="Swim laps",
            estimate_minutes=120,
            deadline=None,
            priority=Priority.NORMAL,
            min_chunk_minutes=30,
            splittable=True,
            created_at=NOW,
        )


def _producer(session: AsyncSession, tenant_id: TenantId) -> WeekProducer:
    """The week producer, as the maintainer suite composes it, for one appended revision."""
    from syncr_api.solving.lifecycle import OperationLifecycle
    from syncr_api.solving.repository import OperationRepository as Ops

    return WeekProducer(
        assembler=build_week_assembler(session, tenant_id, caller=AssemblyCaller.MAINTAINER),
        revisions=PlanRepository(session, tenant_id),
        versions=WeekInputVersionRepository(session, tenant_id),
        weights=WeightSetRepository(session, tenant_id),
        operations=OperationLifecycle(Ops(session, tenant_id), lambda: LATE_IN_THE_WEEK),
    )


async def transitions_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, iso_week: IsoWeek = THIS_WEEK
) -> list[VerdictEventRecord]:
    """One week's verdict rows on every surface, oldest first.

    A solve lands between duty 1 and duty 2 of one tick, so the week's FIRST row usually carries
    the SOLVE surface and duty 2 records what is still news beside it. What this suite reads is the
    episode those rows describe, with the surface asserted per row rather than filtered away.
    """
    async with sessions() as session:
        return await VerdictEventRepository(session, tenant_id).for_week(iso_week)


async def every_maintainer_row(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[VerdictEvent]:
    """Every MAINTAINER-surface row of the tenant, for assertions about duty 2's own writes."""
    async with sessions() as session:
        found = await session.scalars(
            select(VerdictEvent)
            .where(
                VerdictEvent.tenant_id == tenant_id,
                VerdictEvent.surface == VerdictSurface.MAINTAINER.value,
            )
            .order_by(VerdictEvent.iso_week, VerdictEvent.occurred_at)
        )
        return list(found)


async def every_transition(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[VerdictEvent]:
    """Every verdict row of the tenant on every surface, ordered by week then instant."""
    async with sessions() as session:
        found = await session.scalars(
            select(VerdictEvent)
            .where(VerdictEvent.tenant_id == tenant_id)
            .order_by(VerdictEvent.iso_week, VerdictEvent.occurred_at)
        )
        return list(found)


async def declare_a_fortnight_away(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    """An off-plan span over both horizon weeks, which is capacity neither week has.

    A real state rather than a contrived floor: the user is away, so the Area's floor cannot be
    reached in either week, and both weeks are impossible from the first tick.
    """
    async with sessions() as session, session.begin():
        await OffPlanPeriodRepository(session, tenant_id).create(
            interval=Interval(AWAY_FROM, AWAY_UNTIL),
            keep_frame=False,
            label="Away",
            created_at=NOW,
        )


async def declare_a_floor(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, hours: Decimal
) -> None:
    """Restate the CAREER Area's floor, as the Areas route would.

    Named rather than taken as the first row: this tenant holds a second, floorless Area beside
    Career, and the rows answer in no stable order between two declarations stamped with one
    instant.
    """
    async with sessions() as session, session.begin():
        areas = AreaRepository(session, tenant_id)
        (declared,) = [one for one in await areas.list_all() if one.name == "Career"]
        await areas.write(
            declared.id,
            name=declared.name,
            pigment_index=declared.pigment_index,
            budget_percent=declared.budget_percent,
            floor_hours=hours,
        )


def maintainer_transitions(direction: TransitionDirection) -> float:
    """The maintainer's direction counter, read as a scraper reads it."""
    sample = REGISTRY.get_sample_value(
        "syncr_maintainer_verdict_transitions_total", {"direction": direction.value}
    )
    assert sample is not None, "the direction was not exported, so nothing could read it"
    return sample


def recorded_transitions(*, surface: VerdictSurface, feasible: bool) -> float:
    """The transition counter for one surface and direction, read the same way."""
    sample = REGISTRY.get_sample_value(
        "syncr_verdict_transitions_total",
        {
            "provenance": surface.provenance.value,
            "feasible": "true" if feasible else "false",
            "surface": surface.value,
        },
    )
    assert sample is not None, "the series was not exported, so nothing could read it"
    return sample


def method_errors(component: str, method: str) -> float:
    sample = REGISTRY.get_sample_value(
        "syncr_method_errors_total", {"component": component, "method": method}
    )
    return 0.0 if sample is None else sample


# --------------------------------------------------------------------------------
# A week becomes impossible because time passed
# --------------------------------------------------------------------------------


async def test_a_week_becomes_impossible_with_no_user_action_and_the_flip_is_recorded(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """The headline case, and the clock is the only thing that moves between the two ticks.

    Monday morning the week holds a plan and enough capacity for the Area's three-hour floor. By
    Sunday at 22:00 two hours of the week are left, the floor cannot be reached, and no mutation has
    happened: the user did nothing, the plan did not change, and no read may write. The gap
    is asserted as a figure rather than as a sign, because a shortfall recorded from the wrong frame
    would still be positive.
    """
    await declared(sessions, owner.tenant_id)
    early = Ticking(NOW)
    await a_tick(context, early)
    assert await every_maintainer_row(sessions, owner.tenant_id) == [], (
        "a healthy week is not a discovery, so the maintainer records nothing for it"
    )
    before = maintainer_transitions(TransitionDirection.TO_INFEASIBLE)

    late = Ticking(LATE_IN_THE_WEEK)
    await a_tick(context, late)

    recorded = await transitions_of(sessions, owner.tenant_id)
    # The solve the early tick drained spoke first (healthy, SOLVE surface); duty 2 records the
    # discovery beside it.
    assert [(one.surface, one.feasible) for one in recorded] == [
        (VerdictSurface.SOLVE, True),
        (VerdictSurface.MAINTAINER, False),
    ]
    one = recorded[-1]
    assert one.iso_week == THIS_WEEK
    assert one.provenance is Provenance.PROBE
    assert one.session_mode_active is False
    assert one.largest_gap_minutes == EXPECTED_GAP_MINUTES
    assert ShortfallKind.FLOORS_EXCEED_CAPACITY in one.shortfall_kinds
    assert one.caused_by_operation_id is None
    assert maintainer_transitions(TransitionDirection.TO_INFEASIBLE) == before + 1


async def test_the_transition_is_recorded_within_one_tick_of_the_week_becoming_impossible(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """The lag the design promises is one tick, which is fifteen minutes.

    Driven as the runner schedules it rather than by calling the pass twice: the second tick is due
    exactly one interval after the first, and the row it writes is stamped with that instant.
    """
    await declared(sessions, owner.tenant_id)
    became_impossible_at = LATE_IN_THE_WEEK - timedelta(minutes=1)
    clock = Ticking(became_impossible_at - MAINTAINER_INTERVAL)
    runner = PlanHorizonRunner(clock=clock)
    await runner(context)  # the first tick schedules
    due = runner.next_due_at
    assert due is not None
    clock.advance(MAINTAINER_INTERVAL)

    # The due tick, stated as its two duties with the worker's solve duty between them: the pass
    # asks, the drain realizes, and duty 2 probes what the drain produced.
    now = clock()
    planned = await PlanHorizonRunner(clock=clock).plan(context, now=now)
    clock.advance(debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS))
    await SolveRunner(clock=clock).drain(context)
    await PlanHorizonRunner(clock=clock).record_transitions(context, planned.weeks, now=now)

    (one,) = await transitions_of(sessions, owner.tenant_id)
    assert one.occurred_at - became_impossible_at <= MAINTAINER_INTERVAL


# --------------------------------------------------------------------------------
# Only on a transition
# --------------------------------------------------------------------------------


async def test_a_second_tick_that_finds_the_same_verdict_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """A verdict recomputed identically is not news, which is what makes the cadence free.

    The week is impossible from its first instant, and the solve the tick drained already said so on
    the SOLVE surface; duty 2 probes the same verdict and adds nothing, on this tick and on every
    tick after it.
    """
    await declared(sessions, owner.tenant_id)
    clock = Ticking(LATE_IN_THE_WEEK)
    await a_tick(context, clock)
    after_one = await transitions_of(sessions, owner.tenant_id)
    assert [(one.surface, one.feasible) for one in after_one] == [(VerdictSurface.SOLVE, False)]

    clock.advance(MAINTAINER_INTERVAL)
    await a_tick(context, clock)

    assert await transitions_of(sessions, owner.tenant_id) == after_one


async def test_a_week_the_maintainer_finds_healthy_is_never_recorded(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """A week with no row holds no open episode, which is the state a feasible row denotes.

    So a periodic probe reporting that a week is fine writes nothing, on the first tick and on every
    tick after it. Recording it would put one row per horizon week per tenant into a corpus nothing
    ever prunes, and none of them would carry a discovery.
    """
    await declared(sessions, owner.tenant_id)
    clock = Ticking(NOW)

    await a_tick(context, clock)
    clock.advance(MAINTAINER_INTERVAL)
    await a_tick(context, clock)

    assert await every_maintainer_row(sessions, owner.tenant_id) == [], (
        "a healthy week is not a discovery, whichever surface answered first"
    )


async def test_the_close_of_an_episode_is_recorded_too(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """Both directions, because an episode that never closes cannot be measured.

    The Area's floor is lowered between the ticks, which is a mutation that computes no verdict: the
    Areas route changes a declaration and asks for a solve, and nothing on that path probes. So the
    week's recovery has no mutation to attach to either, and this duty is what records it.
    """
    await declared(sessions, owner.tenant_id)
    clock = Ticking(LATE_IN_THE_WEEK)
    await a_tick(context, clock)
    before = maintainer_transitions(TransitionDirection.TO_FEASIBLE)

    await declare_a_floor(sessions, owner.tenant_id, hours=Decimal(0))
    clock.advance(MAINTAINER_INTERVAL)
    await a_tick(context, clock)

    recorded = await transitions_of(sessions, owner.tenant_id)
    # The opening impossibility was the drained solve's own row; the recovery has no mutation to
    # attach to, so the closing flip is duty 2's.
    assert [(one.surface, one.feasible) for one in recorded] == [
        (VerdictSurface.SOLVE, False),
        (VerdictSurface.MAINTAINER, True),
    ]
    assert recorded[1].largest_gap_minutes == 0
    assert recorded[1].shortfall_kinds == ()
    assert maintainer_transitions(TransitionDirection.TO_FEASIBLE) == before + 1


# --------------------------------------------------------------------------------
# A feasible flip, never a provenance change
# --------------------------------------------------------------------------------


async def test_the_tick_after_a_solve_adds_no_provenance_only_row(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """A provenance change alone is not a transition, or the probe would flip ``solver`` back.

    The solve's own row is seeded as the commit path writes one, because what is under test is what
    the maintainer does NEXT: it probes the same impossible week, reaches ``probe`` provenance, and
    must write nothing. A periodic re-confirmation is not a discovery.
    """
    await declared(sessions, owner.tenant_id)
    clock = Ticking(LATE_IN_THE_WEEK)
    await a_tick(context, clock)
    # The drained solve's own row already carries SOLVER provenance, so seed the confirmation that
    # a second solve would write and hold it as the row duty 2 must not top up.
    confirmed = await _seed_a_solver_row(sessions, owner.tenant_id, at=clock())

    clock.advance(MAINTAINER_INTERVAL)
    await a_tick(context, clock)

    recorded = await transitions_of(sessions, owner.tenant_id)
    assert [one.provenance for one in recorded] == [Provenance.SOLVER, Provenance.SOLVER]
    assert recorded[1].id == confirmed.id, "the maintainer added a row where VE8 forbids one"


async def _seed_a_solver_row(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, at: datetime
) -> VerdictEventRecord:
    """The confirmation a completed solve appends, written through the same repository."""
    async with sessions() as session, session.begin():
        return await VerdictEventRepository(session, tenant_id).append(
            VerdictToRecord(
                iso_week=THIS_WEEK,
                occurred_at=at,
                provenance=Provenance.SOLVER,
                feasible=False,
                largest_gap_minutes=EXPECTED_GAP_MINUTES,
                shortfall_kinds=(ShortfallKind.FLOORS_EXCEED_CAPACITY,),
                surface=VerdictSurface.SOLVE,
                session_mode_active=False,
                input_version=1,
                caused_by_operation_id=uuid4(),
            )
        )


# --------------------------------------------------------------------------------
# One instant per tick
# --------------------------------------------------------------------------------


async def test_every_transition_one_tick_records_carries_the_ticks_own_instant(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """One instant per tick, against a clock that advances on every read.

    Two healthy weeks become impossible together when an off-plan span is declared between ticks,
    so ONE tick records two transitions. Both carry one ``occurred_at``, and it is that tick's own
    instant: a duty that read the clock per week would stamp each row differently, and a tick's
    transitions would then be evaluated against several instants.
    """
    await declared(sessions, owner.tenant_id)
    clock = Ticking(NOW)

    await a_tick(context, clock)
    settled_after = clock.at
    await declare_a_fortnight_away(sessions, owner.tenant_id)
    clock.advance(MAINTAINER_INTERVAL)
    due_at = settled_after + MAINTAINER_INTERVAL

    await a_tick(context, clock)

    recorded = await every_maintainer_row(sessions, owner.tenant_id)
    assert [one.iso_week for one in recorded] == [str(THIS_WEEK), str(NEXT_WEEK)]
    assert {one.occurred_at for one in recorded} == {due_at}
    async with sessions() as session:
        stamps = await session.scalars(
            select(PlanRevision.created_at).where(PlanRevision.tenant_id == owner.tenant_id)
        )
    # Each tick kept its own instant: every revision is the FIRST tick's (the drain that realized
    # it solved within that tick's window), and both transitions are the second's.
    assert stamps and max(stamps) < settled_after


# --------------------------------------------------------------------------------
# One transaction per week, and the faults it contains
# --------------------------------------------------------------------------------


async def test_one_weeks_failure_does_not_lose_another_weeks_transition(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """A transaction per week, so a week that raised takes only its own row with it.

    The fault is counted where it can be read: the contained raise still passes through
    ``measured``, so ``syncr_method_errors_total{component="horizon_verdicts"}`` moves. Without that
    a duty failing on every week would leave both transition counters at zero, which reads exactly
    like a tick on which nothing changed.
    """
    await declared(sessions, owner.tenant_id)
    clock = Ticking(NOW)
    await a_tick(context, clock)
    # Both healthy weeks become impossible together, so ONE tick holds two transitions to write:
    # the patch fails the first append and the second must survive it.
    await declare_a_fortnight_away(sessions, owner.tenant_id)
    before = method_errors("horizon_verdicts", "record")
    real = VerdictEventRepository.append
    appends = 0

    async def failing_first(
        self: VerdictEventRepository, transition: VerdictToRecord
    ) -> VerdictEventRecord:
        nonlocal appends
        appends += 1
        if appends == 1:
            raise RuntimeError("simulated append failure")
        return await real(self, transition)

    clock.advance(MAINTAINER_INTERVAL + debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS))
    with patch.object(VerdictEventRepository, "append", failing_first):
        await a_tick(context, clock)

    recorded = await every_maintainer_row(sessions, owner.tenant_id)
    assert [one.iso_week for one in recorded] == [str(NEXT_WEEK)], (
        "the second week's transition was lost to the first week's failure"
    )
    assert method_errors("horizon_verdicts", "record") == before + 1


async def test_a_failure_after_the_append_leaves_no_row(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """The row is written in the job's transaction, so it cannot commit on its own.

    The counter increment is the one statement that follows the append, so failing it is the
    reachable way to ask whether the row was already committed. It must not be.
    """
    await declared(sessions, owner.tenant_id)
    await a_tick(context, Ticking(NOW))
    # A floor the remaining capacity cannot hold turns the week infeasible without any mutation
    # that probes, so this tick's duty 2 reaches its own append.
    await declare_a_floor(sessions, owner.tenant_id, hours=Decimal(6))

    with patch(
        "syncr_api.horizon.verdicts.MAINTAINER_VERDICT_TRANSITIONS.labels",
        side_effect=RuntimeError("simulated failure after the append"),
    ):
        tally = await a_tick(context, Ticking(LATE_IN_THE_WEEK))

    assert tally.failed == 1, "the failure this asserts about did not happen"
    assert await every_maintainer_row(sessions, owner.tenant_id) == [], (
        "a failure after the append left a row behind"
    )


async def test_a_week_with_no_live_plan_is_not_probed(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, engine: AsyncEngine
) -> None:
    """A verdict about a plan that does not exist is a verdict about nothing.

    Driven against the duty directly, because the runner is handed the weeks duty 1 resolved and a
    week duty 1 could not plan is exactly the case: a tenant with no Areas has a horizon and no
    plans, and this duty must not assemble one.
    """
    sessions_of = create_sessionmaker(engine)
    async with sessions_of() as session, session.begin():
        tally = await TimeDrivenVerdicts(session, owner.tenant_id).record(THIS_WEEK, now=NOW)

    assert tally.without_a_plan == 1
    assert tally.recorded == 0
    assert await every_transition(sessions, owner.tenant_id) == []


# --------------------------------------------------------------------------------
# The tick histogram, and the local week list
# --------------------------------------------------------------------------------


async def test_the_verdict_duty_is_timed_under_its_own_label(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """Labeled by duty, because duty 2 assembles every planned week and duty 1 skips it."""
    await declared(sessions, owner.tenant_id)
    clock = Ticking(NOW)
    runner = PlanHorizonRunner(clock=clock)
    await runner(context)  # the first tick schedules
    clock.advance(MAINTAINER_INTERVAL)
    before = _tick_count(MaintainerDuty.VERDICTS)

    await runner(context)

    assert _tick_count(MaintainerDuty.VERDICTS) == before + 1
    assert _tick_count(MaintainerDuty.HORIZON) is not None


def _tick_count(duty: MaintainerDuty) -> float:
    """The tick count for one duty; absent reads as zero, as the maintainer suite's reads it.

    A histogram child exists only once something observed it, and this suite run alone never times
    a tick before its own first one.
    """
    sample = REGISTRY.get_sample_value(
        "syncr_maintainer_tick_duration_seconds_count", {"duty": duty.value}
    )
    return 0.0 if sample is None else sample


async def test_the_assemblies_duty_2_performs_are_visible_on_the_assembly_histogram(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """The cost of this duty, as a measurement rather than a sentence.

    Duty 2 performs roughly 288 full ASSEMBLIES a day, not 288 bare probes: the probe arithmetic is
    sub-millisecond and the assembly is the cost. ``syncr_assembly_duration_seconds{caller=
    "maintainer"}`` is what makes them visible, so the figure an operator would read before
    shortening the interval is asserted to move once per week probed.
    """
    await declared(sessions, owner.tenant_id)
    clock = Ticking(LATE_IN_THE_WEEK)
    runner = PlanHorizonRunner(clock=clock)
    planned = await runner.plan(context, now=LATE_IN_THE_WEEK)
    # Duty 2 assembles only weeks that hold a plan, and the pass leaves requests, so the solve
    # duty runs first -- as it does in the worker loop this tick stands in for.
    clock.advance(debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS))
    await SolveRunner(clock=clock).drain(context)
    before = _assemblies_by_the_maintainer()

    tally = await runner.record_transitions(context, planned.weeks, now=LATE_IN_THE_WEEK)

    probed = sum(len(weeks) for weeks in planned.weeks.values())
    assert tally.weeks == probed, "duty 2 probed a different set of weeks than duty 1 resolved"
    # Scoped to this tenant's weeks, because a pass covers every tenant the database holds and the
    # histogram counts only the weeks that held a plan to assemble.
    ours = len(planned.weeks.get(owner.tenant_id, ()))
    assert _assemblies_by_the_maintainer() == before + ours


def _assemblies_by_the_maintainer() -> float:
    sample = REGISTRY.get_sample_value(
        "syncr_assembly_duration_seconds_count", {"caller": AssemblyCaller.MAINTAINER.value}
    )
    return 0.0 if sample is None else sample


async def test_a_tenant_far_east_probes_the_week_its_own_date_names(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """Thirteen hours east of UTC, at an instant whose UTC date is in the previous ISO week.

    Nothing else in this suite could tell a local horizon from a UTC one, and the week list is duty
    1's: what this asserts is that duty 2 probes the weeks that list holds rather than re-deriving
    them.
    """
    await declared(sessions, owner.tenant_id, home_zone=AUCKLAND)
    # Sunday 22:00 UTC is Monday 11:00 in Auckland, so the local date is already in W08 while the
    # UTC date is still in W07.
    clock = Ticking(LATE_IN_THE_WEEK)
    runner = PlanHorizonRunner(clock=clock)
    planned = await runner.plan(context, now=LATE_IN_THE_WEEK)
    clock.advance(debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS))
    await SolveRunner(clock=clock).drain(context)
    await runner.record_transitions(context, planned.weeks, now=LATE_IN_THE_WEEK)

    async with sessions() as session:
        planned_weeks = await session.scalars(
            select(PlanRevision.iso_week)
            .where(PlanRevision.tenant_id == owner.tenant_id)
            .order_by(PlanRevision.iso_week)
        )
    assert set(planned_weeks) == {str(NEXT_WEEK), str(THIRD_WEEK)}, (
        "the local date is in W08, so W07 is behind this tenant's horizon"
    )
    # Scoped to this tenant, because a pass covers every tenant the database holds and this claim is
    # about which weeks THIS tenant's local date names.
    assert planned.weeks[owner.tenant_id] == (NEXT_WEEK, THIRD_WEEK)
    # Scoped to this tenant, because the pass tally above covers every tenant the database holds.
    async with sessions() as session, session.begin():
        for week in planned.weeks[owner.tenant_id]:
            probed = await TimeDrivenVerdicts(session, owner.tenant_id).record(
                week, now=LATE_IN_THE_WEEK
            )
            assert probed.without_a_plan == 0
    assert await every_maintainer_row(sessions, owner.tenant_id) == [], (
        "both weeks are wholly ahead, so neither is short of capacity"
    )


# --------------------------------------------------------------------------------
# What produced the plan is not something this duty reads
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason", [RevisionReason.MATERIALIZED.value, RevisionReason.AUTO_APPLIED_FILL.value]
)
async def test_the_transition_is_the_same_whatever_produced_the_live_plan(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    context: WorkerContext,
    reason: str,
) -> None:
    """Duty 2 reads whether a week HAS a live revision, never which path appended it.

    A change to duty 1's producer moves the revision reason with it. This is the assertion that says
    such a change cannot reach duty 2: the same transition is recorded under either reason.
    """
    await declared(sessions, owner.tenant_id)
    # A live revision appended through the producer's own path, so no solve row precedes duty 2
    # and the transition this asserts about is duty 2's own.
    async with sessions() as session, session.begin():
        await _producer(session, owner.tenant_id).advance_into(THIS_WEEK, now=LATE_IN_THE_WEEK)
        await session.execute(
            update(PlanRevision)
            .where(PlanRevision.tenant_id == owner.tenant_id)
            .values(reason=reason)
        )
        planned = {owner.tenant_id: (THIS_WEEK,)}

    await PlanHorizonRunner(clock=Ticking(LATE_IN_THE_WEEK)).record_transitions(
        context, planned, now=LATE_IN_THE_WEEK
    )

    (one,) = await transitions_of(sessions, owner.tenant_id)
    assert one.feasible is False
    assert one.surface is VerdictSurface.MAINTAINER
    assert one.largest_gap_minutes == EXPECTED_GAP_MINUTES


async def test_the_counter_the_metric_job_reads_carries_the_surface_and_the_direction(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """``syncr_verdict_transitions_total`` moves on the series the maintainer can produce.

    Read out of the registry as a scraper reads it, so what is asserted is the exposition rather
    than a call.
    """
    await declared(sessions, owner.tenant_id)
    before = recorded_transitions(surface=VerdictSurface.MAINTAINER, feasible=False)

    # Healthy on the first tick; a floor the remainder cannot hold makes the second tick's probe
    # the writer of the discovery.
    await a_tick(context, Ticking(NOW))
    await declare_a_floor(sessions, owner.tenant_id, hours=Decimal(6))
    await a_tick(context, Ticking(LATE_IN_THE_WEEK))

    assert recorded_transitions(surface=VerdictSurface.MAINTAINER, feasible=False) == before + 1


async def test_the_rows_a_week_holds_are_counted_by_the_query_the_metric_job_will_use(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, context: WorkerContext
) -> None:
    """One row per transition and no more, counted in SQL rather than through the repository.

    The repository is what wrote them, so counting through it could agree with itself about a row
    that is not there.
    """
    await declared(sessions, owner.tenant_id)
    clock = Ticking(LATE_IN_THE_WEEK)

    await a_tick(context, clock)
    clock.advance(MAINTAINER_INTERVAL)
    await a_tick(context, clock)

    async with sessions() as session:
        counted = await session.scalar(
            select(func.count())
            .select_from(VerdictEvent)
            .where(
                VerdictEvent.tenant_id == owner.tenant_id, VerdictEvent.iso_week == str(THIS_WEEK)
            )
        )
    assert counted == 1
