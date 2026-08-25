"""The first solve of a week that is half lived, driven end to end through the api's own path.

The reproduction this file replaces: before binding learned to leave a slot the week had already
reached unbound, the binding phase filled every template slot at its declared span whatever the
clock said, so a solve of the current week placed chosen blocks onto days the week had lived. The
past rule refused the candidate, the lifecycle retried it, and the operation failed on EVERY
attempt until the week left the horizon -- permanently, for a week the user still lives in. The
seed harness carried that refusal as a tolerated outcome (ticket 1570) because nothing could be
done about it inside the solve.

What changed is upstream of this suite -- the solver leaves such a slot unbound with
``EmptySlotReason.ELAPSED``, and the packer clips its gaps to ``now`` -- so what is asserted here
is the composed result over the production pipeline: the horizon runner materializes the current
week, the worker solves it, the operation reaches ``succeeded``, and the days still ahead hold
content. The success must not read as a loosening, so the same file drives the refusal the failure
code exists for: a candidate that drops, moves or invents a started SOLVER-placed block is still
refused with ``past_disagreement`` on every attempt.

The solver is substituted only where a case needs a stated candidate document, exactly as
``test_solve_runner_integration.py`` substitutes it; everything either side of ``solve`` --
assembler, placement seam, authority rule, lifecycle, repositories -- is the production wiring
over a real Postgres.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from syncr_api.areas.repository import AreaRepository
from syncr_api.core.db import create_database, create_db_engine, create_sessionmaker
from syncr_api.core.settings import (
    DEFAULT_SOLVE_DEBOUNCE_MS,
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.horizon.runner import PlanHorizonRunner
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import plan_document
from syncr_api.solving.config import FAILED, PAST_DISAGREEMENT, PENDING, SUCCEEDED
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.declarations import SlotEntry
from syncr_api.templates.repository import (
    DayTypeRepository,
    TemplateRepository,
    WeekPatternRepository,
)
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.worker.main import WorkerContext
from syncr_domain.feasibility import Provenance, Verdict
from syncr_domain.gaps import EmptySlotReason
from syncr_domain.identity import Origin, is_placed_by_the_solver
from syncr_domain.intervals import Interval, has_started
from syncr_domain.tasks import Priority
from syncr_domain.templates import EntrySpan, WeekPattern
from syncr_domain.weeks import IsoWeek, Weekday
from syncr_solver.objective import ObjectiveBreakdown
from syncr_solver.solve import SolveResult
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import a_block, between

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.records import PlanRevisionRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import AreaId, TenantId
    from syncr_domain.plan import Block, PlanDocument

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
# Wednesday mid-morning: two weekdays of the week are lived and five days are still ahead. London
# is on UTC in February, so the wall times a declaration names are the instants these tests read.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)
# The current week is resolved in the home zone, so it derives from the local date, not the UTC one.
WEEK = IsoWeek.containing(NOW.astimezone(ZoneInfo(LONDON)).date())
# When the past-guard cases need a started block, the clock moves here: the Wednesday slot the
# first solve bound has begun, and the Friday slot has not.
THURSDAY = NOW + timedelta(days=1)

# The one shape every weekday carries: one Career slot at ten o'clock, an hour long, no band.
SLOT_SPAN = EntrySpan(target_time=time(10, 0), duration_minutes=60, flex_band_minutes=0)


class Ticking:
    """A clock a test moves by hand."""

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


async def declare_the_week(sessions: async_sessionmaker[AsyncSession], owner: UserRecord) -> AreaId:
    """One Area with work to place, a slot for it on every day, and the weight set solving reads.

    The task's estimate is deliberately larger than the five slots still ahead can bind, so no day
    ahead of the clock goes short for want of eligible content: what the lived days cost the week
    shows up as unplaced minutes, never as an empty afternoon saying the Area had nothing.
    """
    async with sessions() as session, session.begin():
        settings = SettingsRepository(session, owner.tenant_id)
        locked = await settings.lock(created_at=NOW)
        await settings.write(
            visible_hours=locked.visible_hours,
            day_start=locked.day_start,
            day_end=locked.day_end,
            review_cadence=locked.review_cadence,
            home_zone=LONDON,
        )
        area = await AreaRepository(session, owner.tenant_id).create(
            parent_id=None,
            name="Career",
            pigment_index=1,
            budget_percent=Decimal(30),
            floor_hours=Decimal(3),
            created_at=NOW,
        )
        day_type = await DayTypeRepository(session, owner.tenant_id).create(
            name="Weekday", created_at=NOW
        )
        template = await TemplateRepository(session, owner.tenant_id).create(
            day_type_id=day_type.id, name="Weekday", created_at=NOW
        )
        await TemplateRepository(session, owner.tenant_id).create_entry(
            template_id=template.id,
            span=SLOT_SPAN,
            content=SlotEntry(span=SLOT_SPAN, area_id=area.id).content(),
        )
        await WeekPatternRepository(session, owner.tenant_id).replace(
            WeekPattern(dict.fromkeys(Weekday, day_type.id))
        )
        await TaskRepository(session, owner.tenant_id).create(
            area_id=area.id,
            project_id=None,
            title="Interview preparation",
            estimate_minutes=15 * 60,
            deadline=None,
            priority=Priority.NORMAL,
            min_chunk_minutes=30,
            splittable=True,
            created_at=NOW,
        )
        await WeightSetRepository(session, owner.tenant_id).seed_hand_tuned(at=NOW)
    return area.id


async def materialize_the_current_week(
    context: WorkerContext,
    clock: Ticking,
    tenant_id: TenantId,
) -> tuple[IsoWeek, ...]:
    """Duty 1 of the horizon runner, over every tenant, at the frozen instant.

    The maintainer plans each week inside the horizon that holds no plan, which for a fresh tenant
    is all of them starting with the current one.
    """
    planned = await PlanHorizonRunner(clock=clock).plan(context, now=clock())
    return planned.weeks.get(tenant_id, ())


async def a_materialized_week(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    owner: UserRecord,
    clock: Ticking,
) -> AreaId:
    """The declared week, and its current week materialized through the runner.

    The clock then moves a minute, because in production the solve follows the horizon pass rather
    than sharing its instant. Two revisions appended at one ``created_at`` would leave
    "latest" to the id tie-break, whose uuid order is random: the plan of record could read back
    as either the materialized plan or the solved one, per run.
    """
    area_id = await declare_the_week(sessions, owner)
    resolved = await materialize_the_current_week(context, clock, owner.tenant_id)
    assert WEEK in resolved
    clock.advance(timedelta(minutes=1))
    return area_id


async def a_solve(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    owner: UserRecord,
    clock: Ticking,
) -> OperationRecord:
    """One request, claimed and dispatched, which is what one tick of the duty does."""
    async with sessions() as session, session.begin():
        await build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).request_solve(WEEK, 1, immediate=True)
    async with sessions() as session, session.begin():
        claim = await build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).claim_next()
    assert claim is not None
    dispatch = SolveDispatch(
        context.database,
        owner.tenant_id,
        clock=clock,
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
    )
    return await dispatch.run(claim, WEEK)


async def spent(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    owner: UserRecord,
    clock: Ticking,
) -> OperationRecord:
    """One solve driven to its attempt bound, which is where a permanent refusal comes to rest."""
    finished = await a_solve(sessions, context, owner, clock)
    while finished.status == PENDING:
        clock.advance(timedelta(hours=1))
        finished = await a_solve(sessions, context, owner, clock)
    return finished


async def the_plan_of_record(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> tuple[PlanDocument, PlanRevisionRecord]:
    """The week's plan of record, rebuilt, beside the row that stores it."""
    async with sessions() as session:
        revision = await PlanRepository(session, owner.tenant_id).latest(WEEK)
        assert revision is not None, f"{WEEK} holds no plan"
        return plan_document(revision.document), revision


async def revision_reasons(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> list[str]:
    """Every reason the week's revisions were appended under, oldest first."""
    async with sessions() as session:
        found = await session.scalars(
            select(PlanRevision)
            .where(PlanRevision.tenant_id == owner.tenant_id)
            .order_by(PlanRevision.created_at)
        )
        return [one.reason for one in found]


def the_future_slot_spans() -> tuple[Interval, ...]:
    """The declared slot spans the frozen clock had not reached: Wednesday through Sunday at ten."""
    monday = datetime.combine(WEEK.monday(), datetime.min.time(), tzinfo=UTC)
    return tuple(
        Interval(
            monday + timedelta(days=day, hours=SLOT_SPAN.target_time.hour),
            monday + timedelta(days=day, hours=SLOT_SPAN.target_time.hour + 1),
        )
        for day in range(2, 7)
    )


def the_lived_dates() -> set[Any]:
    """Monday and Tuesday of the week, which the frozen clock had already reached."""
    return {WEEK.monday(), WEEK.dates()[1]}


def holds_content(document: PlanDocument) -> bool:
    """Whether every slot ahead of the clock is bound: its span appears among the blocks."""
    placed = {block.interval for block in document.blocks}
    return all(span in placed for span in the_future_slot_spans())


def a_started_solver_block(document: PlanDocument, *, now: datetime) -> Block:
    """One block the solve chose that the week has since reached."""
    started = [
        block
        for block in document.blocks
        if has_started(block.interval, now) and is_placed_by_the_solver(block.origin)
    ]
    assert started, (
        "the fixture has to leave a started solver-placed block for the guard to bite on; the "
        f"plan holds: {[(str(one.origin), str(one.interval)) for one in document.blocks]}"
    )
    return started[0]


def without(block: Block, document: PlanDocument) -> tuple[Block, ...]:
    return tuple(one for one in document.blocks if one.id != block.id)


# The seven terms, all zero: a substituted solver evaluates nothing, and what the classification
# reads off the result is the document, never the figures.
_NO_COST = ObjectiveBreakdown(
    deadline_risk=0.0,
    budget_deviation=0.0,
    time_of_day_misfit=0.0,
    fragmentation=0.0,
    churn=0.0,
    context_switch=0.0,
    staleness=0.0,
)


def _solved_with(document: PlanDocument) -> Any:
    return SolveResult(
        document=document,
        objective_breakdown=_NO_COST,
        verdict=Verdict(
            feasible=True,
            provenance=Provenance.SOLVER,
            computed_at=document.blocks[0].interval.start if document.blocks else NOW,
            input_version=1,
            discretionary_minutes=6000,
        ),
        blocked_log=(),
        iterations=0,
    )


def _dropped(document: PlanDocument, started: Block, _area_id: AreaId) -> PlanDocument:
    """The same week minus the started block, as if the solve had never placed it."""
    return replace(document, blocks=without(started, document))


def _moved(document: PlanDocument, started: Block, _area_id: AreaId) -> PlanDocument:
    """The started block two hours later, which is a placement only the user may ask for."""
    shifted = Interval(
        started.interval.start + timedelta(hours=2),
        started.interval.end + timedelta(hours=2),
    )
    return replace(
        document, blocks=(replace(started, interval=shifted), *without(started, document))
    )


def _invented(document: PlanDocument, _started: Block, area_id: AreaId) -> PlanDocument:
    """One more chosen block, on Monday morning: time the week lived that no plan places."""
    invented = a_block(origin=Origin.TASK, interval=between(10, 11, day=0))
    return replace(document, blocks=(*document.blocks, replace(invented, area_id=area_id)))


class TestTheFirstSolveOfTheCurrentWeek:
    async def test_the_horizon_runner_materializes_the_current_week(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """Duty 1 resolves the week the clock is standing in, and its plan says who produced it."""
        await declare_the_week(sessions, owner)

        resolved = await materialize_the_current_week(context, clock, owner.tenant_id)

        assert WEEK in resolved
        # The runner contains a week's fault behind a tally, so a silent assembly failure would
        # look exactly like a week that needed no plan. Read the rows rather than trust the tally:
        # the whole fresh horizon is planned, and every row says the runner, not a solve, wrote it.
        reasons = await revision_reasons(sessions, owner)
        assert reasons and set(reasons) == {"horizon_advanced"}

    async def test_the_operation_reaches_succeeded(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """The whole point, on the first attempt: a half-lived week is no longer unwedgeable."""
        await a_materialized_week(sessions, context, owner, clock)

        finished = await a_solve(sessions, context, owner, clock)

        assert finished.status == SUCCEEDED, finished.error_message
        assert finished.error_code is None
        _, revision = await the_plan_of_record(sessions, owner)
        assert finished.result_revision_id == revision.id

    async def test_the_weeks_slots_from_now_onward_hold_content(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """Success is not the week arriving empty: every day still ahead carries its bound slot."""
        await a_materialized_week(sessions, context, owner, clock)

        finished = await a_solve(sessions, context, owner, clock)

        assert finished.status == SUCCEEDED
        document, _ = await the_plan_of_record(sessions, owner)
        unbound = [str(slot.interval) for slot in document.empty_slots]
        assert holds_content(document), (
            f"a slot the week has not reached was left unbound: {unbound}"
        )

    async def test_a_slot_on_a_lived_day_is_its_own_reason_not_a_backlog_answer(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """The carried answer to input 1570, read off the adopted plan.

        A slot on a day already lived gets its own member of ``EmptySlotReason`` rather than
        borrowing ``not_solved``: nobody declined to look at the backlog there, the clock decided
        it. Its gutter label is the one wording that says the time has passed.
        """
        await a_materialized_week(sessions, context, owner, clock)
        await a_solve(sessions, context, owner, clock)

        document, _ = await the_plan_of_record(sessions, owner)
        lived = [
            slot for slot in document.empty_slots if slot.interval.start.date() in the_lived_dates()
        ]
        assert [slot.reason for slot in lived] == [
            EmptySlotReason.ELAPSED,
            EmptySlotReason.ELAPSED,
        ]
        assert not any(slot.reason is EmptySlotReason.NOT_SOLVED for slot in document.empty_slots)


class TestThePastGuardIsNotLoosened:
    """The refusal the success must not retire.

    Each case answers with a stated candidate that restates a started block the first solve chose,
    which is the shape a misbehaving solve can actually produce. The lifecycle retries a failed
    attempt, so a refusal that reaches terminal status is one that survived EVERY attempt -- the
    same reading the reproduction was stated in.
    """

    @pytest.mark.parametrize(
        "restates", [_dropped, _moved, _invented], ids=["drops", "moves", "invents"]
    )
    async def test_a_candidate_restating_a_started_block_is_refused_on_every_attempt(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        monkeypatch: pytest.MonkeyPatch,
        restates: Any,
    ) -> None:
        area_id = await a_materialized_week(sessions, context, owner, clock)
        finished = await a_solve(sessions, context, owner, clock)
        assert finished.status == SUCCEEDED, finished.error_message
        document, revision = await the_plan_of_record(sessions, owner)

        clock.advance(THURSDAY - clock.at)
        started = a_started_solver_block(document, now=clock.at)
        monkeypatch.setattr(
            "syncr_api.solving.dispatch.solve",
            lambda *_args, **_asked: _solved_with(restates(document, started, area_id)),
        )

        final = await spent(sessions, context, owner, clock)

        assert final.status == FAILED
        assert final.error_code == PAST_DISAGREEMENT
        after, latest = await the_plan_of_record(sessions, owner)
        # The refusal left the plan of record exactly where the successful solve put it, and the
        # days still ahead still hold their content: the guard protects, it does not unwind.
        assert latest.id == revision.id
        assert holds_content(after)
