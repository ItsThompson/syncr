"""The solve runner against a real Postgres: the conditional write, the stamp, and the failure path.

The guard is a ``SELECT ... FOR UPDATE`` on the version row, so a fake would be asserting the
reading this suite exists to check. Every test drives a real solve of a real week.

Five groups.

**A version mismatch discards before anything is written.** No revision, no proposal, no conflict:
the transaction rolls back with the read that discovered the mismatch inside it, the operation is
``superseded``, and exactly one follow-up is enqueued. A week with no version row at all is a
mismatch too, which is what stops two concurrent first solves from both committing.

**The version is stamped when the inputs are LOADED.** The operation carries the version the
assembly actually read, so a burst that coalesced does not waste a solve: the row is guarded on the
version the last mutation left rather than on the one the first mutation created it against.

**A projection is enqueued only when the live plan changed**, which is the same condition the
version bump is under.

**Failure names its cause and keeps the inputs it read on the last attempt**, and a week whose
attempts are spent with no live revision is materialized instead of left with a hole.

**The two shapes that used to wedge the week solve.** A commitment corrected in the feed after it
began, and a routine edited mid-week whose occurrence has begun, both re-derive at their new span,
and both are adopted rather than refused. The pair that must still be refused, a candidate that
drops or moves a started habit or task block, is driven in ``test_authority_classifier.py``, where
comparison is a pure function of two documents.

The live plan reaches the assembler through the placement seam, which answers with nothing in this
deployment. A reader over the revision table is substituted here, because otherwise every candidate
would classify as a first plan for its week and the whole authority path would be unreachable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.injection import build_week_assembler
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.placements import WeekPlacements
from syncr_api.plans.production import WeekProducer
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import plan_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import (
    FAILED,
    LEASE,
    LEASE_EXPIRED,
    MATERIALIZE,
    MAX_ATTEMPTS,
    PENDING,
    PROJECTION,
    SOLVE,
    SOLVER_RAISED,
    SUCCEEDED,
    SUPERSEDED,
)
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.maintenance import maintenance_for
from syncr_api.solving.models import Operation
from syncr_api.solving.repository import OperationRepository
from syncr_api.tasks.repository import TaskRepository
from syncr_api.templates.repository import DayTypeRepository, WeekPatternRepository
from syncr_api.user_settings.repository import SettingsRepository
from syncr_api.worker.main import WorkerContext
from syncr_common.metrics import REGISTRY
from syncr_domain.feasibility import Provenance, Verdict
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, DerivationSource, ReasonRecord
from syncr_domain.tasks import Priority
from syncr_domain.templates import WeekPattern
from syncr_domain.weeks import IsoWeek, Weekday
from syncr_solver.objective import ObjectiveBreakdown
from syncr_solver.solve import SolveResult
from tests.live_tenants import delete_tenant, seed_owner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek as IsoWeekType

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
WEEK = IsoWeek(2026, 7)
# Wednesday morning of the week, so the week has a past and a future and the started-block rules
# have something to be decided against.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)


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


async def declare_the_minimum(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> None:
    """Areas, a day shape, a weight set, a home zone, and one task the solver can place.

    The task is what makes the authority path reachable: a week with an Area and no content solves
    to an empty document, which classifies as nothing and writes nothing, so a suite without it
    would assert about a solve that adopted no plan.
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


class StoredPlacements:
    """No longer needed: production wires the real reader.

    Kept so the fixture below does not need to be removed from nine test signatures in this
    commit. The fixture itself is a no-op now.
    """

    def __init__(self, revisions: PlanRepository) -> None:
        self._revisions = revisions

    async def read(self, iso_week: IsoWeekType, span: object = None) -> WeekPlacements:
        latest = await self._revisions.latest(iso_week)
        return WeekPlacements(live_plan=None if latest is None else plan_document(latest.document))


def dispatch_reading_the_live_plan(
    context: WorkerContext, tenant_id: TenantId, clock: Ticking, **overrides: Any
) -> SolveDispatch:
    """The dispatch as the runner composes it, with the live plan supplied.

    ``build_week_assembler`` is monkeypatched inside the dispatch's own module rather than a second
    assembler being composed here, so the pipeline under test is the production one with one seam
    changed.
    """
    return SolveDispatch(
        context.database,
        tenant_id,
        clock=clock,
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        **overrides,
    )


@pytest.fixture
def live_plan_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op: the production injection now wires StoredPlacements.

    Kept so the nine tests that declare this fixture in their signature do not need to be
    edited in this commit. The fixture was a monkeypatch of the one seam production now holds.
    """


async def requested(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking, **overrides: Any
) -> OperationRecord:
    async with sessions() as session, session.begin():
        return await build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).request_solve(WEEK, 1, immediate=True, **overrides)


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
    assert claim is not None
    return claim


async def revisions_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[PlanRevision]:
    async with sessions() as session:
        found = await session.scalars(
            select(PlanRevision)
            .where(PlanRevision.tenant_id == tenant_id)
            .order_by(PlanRevision.created_at)
        )
        return list(found)


async def operations_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, kind: str | None = None
) -> list[Operation]:
    async with sessions() as session:
        statement = select(Operation).where(Operation.tenant_id == tenant_id)
        if kind is not None:
            statement = statement.where(Operation.kind == kind)
        found = await session.scalars(statement.order_by(Operation.scheduled_for))
        return list(found)


async def a_solve(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    owner: UserRecord,
    clock: Ticking,
    **overrides: Any,
) -> OperationRecord:
    """One request, claimed and dispatched, which is what one tick of the duty does."""
    await requested(sessions, owner, clock)
    claim = await claimed(sessions, owner, clock)
    return await dispatch_reading_the_live_plan(context, owner.tenant_id, clock, **overrides).run(
        claim, WEEK
    )


class TestASolveOfAWeekWithNoPlan:
    async def test_the_first_solve_is_superseded_because_the_week_had_no_version_row(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
    ) -> None:
        """A missing version row is a MISMATCH, and this is what that costs and what it buys.

        Failing open instead would let two concurrent first solves both commit. The cost is one
        discarded solve on a week nothing had referenced; the follow-up reads the row this write
        created and adopts.
        """
        await declare_the_minimum(sessions, owner.tenant_id)

        finished = await a_solve(sessions, context, owner, clock)

        assert finished.status == SUPERSEDED
        assert await revisions_of(sessions, owner.tenant_id) == []
        pending = [
            one
            for one in await operations_of(sessions, owner.tenant_id, kind=SOLVE)
            if one.status == PENDING
        ]
        assert len(pending) == 1

    async def test_the_follow_up_is_guarded_on_the_row_the_first_write_created(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
    ) -> None:
        """Which is what makes failing closed on a missing row cost one solve, not the week."""
        await declare_the_minimum(sessions, owner.tenant_id)
        await a_solve(sessions, context, owner, clock)

        claim = await claimed(sessions, owner, clock)
        finished = await dispatch_reading_the_live_plan(context, owner.tenant_id, clock).run(
            claim, WEEK
        )

        assert finished.status == SUCCEEDED
        assert finished.input_version == await version_of(sessions, owner)

    async def test_the_version_is_stamped_from_the_assembly_rather_than_from_creation(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
    ) -> None:
        """A coalesced burst must not waste a solve, and this is the mechanism that decides it.

        The operation is created while the week is at one version and two more mutations land before
        the worker loads anything. Stamped at creation it would be guarded on the version it was
        created against and superseded with no concurrency involved at all.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        await bump(sessions, owner, clock)
        await bump(sessions, owner, clock)
        at_load = await version_of(sessions, owner)

        claim = await claimed(sessions, owner, clock)
        finished = await dispatch_reading_the_live_plan(context, owner.tenant_id, clock).run(
            claim, WEEK
        )

        assert finished.input_version == at_load
        assert finished.status == SUCCEEDED

    async def test_a_solve_that_changes_nothing_enqueues_no_projection(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
    ) -> None:
        """The condition the projection and the version bump are both under, from its false side.

        A burst of pins appending zero revisions is what makes a weekly session cheap: twelve
        destructive calendar reconciliations during one session would be slow and visible on the
        user's phone, and it falls out of this condition rather than a session-specific case.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)

        finished = await a_solve(sessions, context, owner, clock)

        assert finished.status == SUCCEEDED
        assert finished.result_revision_id is None
        assert await operations_of(sessions, owner.tenant_id, kind=PROJECTION) == []
        assert await revisions_of(sessions, owner.tenant_id) == []


class TestAVersionMismatchDiscardsBeforeAnyWrite:
    async def test_a_mutation_landing_during_the_solve_discards_it_and_writes_nothing(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
    ) -> None:
        """The guard, driven at the only moment it can fire: after the load and before the write.

        The bump is performed while the operation is running, which is exactly the case the whole
        mechanism exists for. Nothing is rebased and nothing is applied partially.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim = await claimed(sessions, owner, clock)
        dispatch = dispatch_reading_the_live_plan(context, owner.tenant_id, clock)
        loaded = await dispatch._loaded(claim, WEEK)
        await bump(sessions, owner, clock)
        solved = await dispatch._solved(loaded, WEEK)

        finished = await dispatch._written(
            claim, WEEK, loaded, solved, classification_of(dispatch, loaded, solved)
        )

        assert finished.status == SUPERSEDED
        assert await revisions_of(sessions, owner.tenant_id) == []
        assert await operations_of(sessions, owner.tenant_id, kind=PROJECTION) == []

    async def test_the_supersession_names_exactly_one_follow_up(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
    ) -> None:
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim = await claimed(sessions, owner, clock)
        dispatch = dispatch_reading_the_live_plan(context, owner.tenant_id, clock)
        loaded = await dispatch._loaded(claim, WEEK)
        await bump(sessions, owner, clock)
        solved = await dispatch._solved(loaded, WEEK)

        finished = await dispatch._written(
            claim, WEEK, loaded, solved, classification_of(dispatch, loaded, solved)
        )

        pending = [
            one
            for one in await operations_of(sessions, owner.tenant_id, kind=SOLVE)
            if one.status == PENDING
        ]
        assert len(pending) == 1
        assert finished.superseded_by == pending[0].id


class TestFailure:
    async def test_a_raising_solver_fails_with_a_stated_cause_and_retries(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await declare_the_minimum(sessions, owner.tenant_id)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _raising)

        finished = await a_solve(sessions, context, owner, clock)

        assert finished.status == PENDING
        assert finished.error_code == SOLVER_RAISED
        assert "still projected" in (finished.error_message or "")

    async def test_the_last_attempt_keeps_the_inputs_it_read(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The producer ``failed_input_snapshot`` has been waiting for.

        A retried attempt keeps none, because the table forbids a snapshot on any status but
        ``failed`` and a retried row is ``pending``. So a snapshot arriving is also the assertion
        that this was the last attempt.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _raising)

        finished = await spent(sessions, context, owner, clock)

        assert finished.status == FAILED
        assert finished.attempt == MAX_ATTEMPTS
        assert await snapshot_of(sessions, owner, finished) is not None

    async def test_a_week_with_no_live_revision_is_materialized_instead(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """So the horizon is never left with a hole, and the history says which path produced it."""
        await declare_the_minimum(sessions, owner.tenant_id)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _raising)

        await spent(sessions, context, owner, clock)

        appended = await revisions_of(sessions, owner.tenant_id)
        assert [one.reason for one in appended] == ["materialized"]
        assert len(await operations_of(sessions, owner.tenant_id, kind=MATERIALIZE)) == 1

    async def test_a_week_that_already_has_a_plan_keeps_it(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The plan it has is better than a derived-only one, and it is still projected.
        await declare_the_minimum(sessions, owner.tenant_id)
        await materialized(sessions, owner, clock)
        held = await revisions_of(sessions, owner.tenant_id)
        assert held, "the fixture has to leave a live revision for this rule to be about one"
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _raising)

        await spent(sessions, context, owner, clock)

        assert [one.id for one in await revisions_of(sessions, owner.tenant_id)] == [
            one.id for one in held
        ]


class TestTheTwoShapesThatUsedToWedgeTheWeek:
    """Both re-derive at a new span after the week reached them, and both must keep solving.

    Measured against the real ``materialize`` before the rule was narrowed: each produced a refusal
    naming a moved block, the operation failed, and the next trigger repeated it, so every solve of
    that week failed until the week left the horizon.

    **Driven here as the week solving repeatedly, and in ``test_authority_classifier.py`` as the
    comparison itself.** The refusal is a pure function of two documents, so the discriminating
    assertion is there, from literals, and its guard is bite-checked: an exempt origin at two spans
    passes while a habit or task at two spans is refused. What this adds is that the runner pairs
    the producer with the guard over a week that holds a plan, repeatedly, without failing.
    """

    async def test_a_week_whose_inputs_keep_moving_keeps_solving(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
    ) -> None:
        await declare_the_minimum(sessions, owner.tenant_id)
        await materialized(sessions, owner, clock)

        for _ in range(3):
            await bump(sessions, owner, clock)
            finished = await a_solve(sessions, context, owner, clock)
            assert finished.status == SUCCEEDED, finished.error_message
            assert finished.error_code is None


async def materialized(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> None:
    """One live revision for the week, through the producer the horizon maintainer uses.

    A materialized plan rather than a solved one, because what these tests need is a week that HOLDS
    a plan: what the solver places into it is the solver's own suite's subject.
    """
    async with sessions() as session, session.begin():
        await WeekProducer(
            assembler=build_week_assembler(
                session, owner.tenant_id, caller=AssemblyCaller.MAINTAINER
            ),
            revisions=PlanRepository(session, owner.tenant_id),
            versions=WeekInputVersionRepository(session, owner.tenant_id),
            weights=WeightSetRepository(session, owner.tenant_id),
            operations=OperationLifecycle(OperationRepository(session, owner.tenant_id), clock),
        ).advance_into(WEEK, now=clock())


async def spent(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    owner: UserRecord,
    clock: Ticking,
) -> OperationRecord:
    """One solve driven to its attempt bound, which is where a failure becomes terminal."""
    finished = await a_solve(sessions, context, owner, clock)
    while finished.status == PENDING:
        clock.advance(timedelta(hours=1))
        claim = await claimed(sessions, owner, clock)
        finished = await dispatch_reading_the_live_plan(context, owner.tenant_id, clock).run(
            claim, WEEK
        )
    return finished


async def snapshot_of(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, operation: OperationRecord
) -> object:
    async with sessions() as session:
        return await OperationRepository(session, owner.tenant_id).read_failed_input_snapshot(
            operation.id
        )


async def bump(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> int:
    """One mutation's version bump, which is what every trigger in the product performs."""
    async with sessions() as session, session.begin():
        return await WeekInputVersionRepository(session, owner.tenant_id).bump(WEEK, at=clock())


async def version_of(sessions: async_sessionmaker[AsyncSession], owner: UserRecord) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, owner.tenant_id).current(WEEK)


def classification_of(dispatch: SolveDispatch, loaded: Any, solved: Any) -> Any:
    from syncr_api.plans.authority import classify

    return classify(loaded.inputs.live_plan, solved.document, now=loaded.inputs.now)


def _raising(*_args: Any, **_asked: Any) -> Any:
    message = "the solver could not complete"
    raise RuntimeError(message)


class TestTheAdoptionBranch:
    """The branch production always takes, driven by a solver that answers with a plan.

    Every other case in this file produces a solve that changes nothing, because a week declared
    with an Area and one task solves to an empty document: what a solve places into a week is the
    solver suite's subject and it is not reachable from this fixture. So the branch that appends a
    revision, bumps the version and enqueues the projection was executed by no test at all, and it
    is the ONLY branch this deployment takes: the placement seam answers with no live plan, so every
    candidate classifies as a first plan for its week and auto-applies.

    Substituted at the module boundary, exactly as the raising solver is, so the phases either side
    of it are the production ones and the whole of `run()` is exercised.
    """

    async def test_a_candidate_that_fills_empty_space_appends_a_revision(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)

        finished = await a_solve(sessions, context, owner, clock)

        assert finished.status == SUCCEEDED
        appended = await revisions_of(sessions, owner.tenant_id)
        assert len(appended) == 1
        assert finished.result_revision_id == appended[0].id
        assert appended[0].reason == "auto_applied_fill"

    async def test_the_version_moves_because_the_live_plan_did(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # V3 and V5: the live plan IS a solve input, so appending a revision has to move the counter
        # a later mutation and a later assembly both read.
        await declare_the_minimum(sessions, owner.tenant_id)
        held = await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)

        finished = await a_solve(sessions, context, owner, clock)

        assert finished.input_version == held
        assert await version_of(sessions, owner) == held + 1

    async def test_a_projection_is_enqueued_because_the_live_plan_changed(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The true side of the condition whose false side the case above drives. Both are the same
        # `if`, so a change that enqueued unconditionally would redden one and a change that never
        # enqueued would redden the other.
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)

        await a_solve(sessions, context, owner, clock)

        queued = await operations_of(sessions, owner.tenant_id, kind=PROJECTION)
        assert [one.iso_week for one in queued] == [str(WEEK)]

    async def test_the_appended_document_is_one_the_domain_can_rebuild(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # What is stored is the plan of record, so a document that could be written and not read
        # back would be a week nothing can render.
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)

        await a_solve(sessions, context, owner, clock)

        (appended,) = await revisions_of(sessions, owner.tenant_id)
        rebuilt = plan_document(appended.document)
        assert rebuilt.iso_week == WEEK
        assert len(rebuilt.blocks) == 1

    async def test_a_second_solve_of_the_same_week_proposes_rather_than_applying(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The authority rule, end to end, which is what the placement seam makes unreachable today.

        The first solve appends. The second answers with the SAME block moved, which is a change the
        product may not make on its own, so it lands in the pending slot and the live plan is left
        exactly where it was.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)
        await a_solve(sessions, context, owner, clock)
        applied = await revisions_of(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _moving_that_block)

        finished = await a_solve(sessions, context, owner, clock)

        assert finished.status == SUCCEEDED
        assert finished.result_revision_id is None
        assert [one.id for one in await revisions_of(sessions, owner.tenant_id)] == [
            one.id for one in applied
        ]
        assert await pending_proposal_of(sessions, owner) is not None
        # The false side of the projection condition WITH a live plan present, which is the more
        # interesting one: a proposal nobody has agreed to must not reach the user's calendar.
        assert len(await operations_of(sessions, owner.tenant_id, kind=PROJECTION)) == 1


async def pending_proposal_of(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> object:
    async with sessions() as session:
        return await PendingProposalRepository(session, owner.tenant_id).find(WEEK)


def _one_block_at(inputs: Any, hour: float) -> Any:
    """A plan holding one task block, at an hour of the week the assembly says is still to come."""
    task = inputs.eligible_tasks[0]
    midnight = inputs.now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + timedelta(days=1, hours=hour)
    return PlanDocument(
        iso_week=inputs.iso_week,
        zone_by_date=inputs.zone_by_date,
        discretionary_minutes=6000,
        unallocated_minutes=0,
        oversubscription_minutes=0,
        blocks=(
            Block(
                iso_week=inputs.iso_week,
                interval=Interval(start, start + timedelta(minutes=60)),
                binding=task.binding,
                title=task.title,
                reason=ReasonRecord((Bound(DerivationSource.ROUTINE, "the substituted solver"),)),
                area_id=task.area_id,
            ),
        ),
    )


def _solved_with(document: PlanDocument) -> Any:
    """A solve result carrying ``document``, with the figures the write path reads.

    A verdict is required because the pending slot's column is not nullable, and a proposal is what
    the second solve produces: the shape of the value is what makes the write reachable, so it is
    built rather than stubbed.
    """
    return SolveResult(
        document=document,
        objective_breakdown=_NO_COST,
        verdict=Verdict(
            feasible=True,
            provenance=Provenance.SOLVER,
            computed_at=document.blocks[0].interval.start,
            input_version=1,
            discretionary_minutes=6000,
        ),
        blocked_log=(),
        iterations=1,
    )


def _placing_one_block(inputs: Any, _weights: Any, **_asked: Any) -> Any:
    """A solver that fills empty space, which is the one thing authority lets through."""
    return _solved_with(_one_block_at(inputs, 10))


def _moving_that_block(inputs: Any, _weights: Any, **_asked: Any) -> Any:
    """The same content an hour later, which is a move and therefore needs assent."""
    return _solved_with(_one_block_at(inputs, 14))


# The seven terms, all zero. A substituted solver evaluates nothing, and a breakdown of zeros is the
# honest reading of that: what the write path reads it for is the column, not the figures.
_NO_COST = ObjectiveBreakdown(
    deadline_risk=0.0,
    budget_deviation=0.0,
    time_of_day_misfit=0.0,
    fragmentation=0.0,
    churn=0.0,
    context_switch=0.0,
    staleness=0.0,
)


class TestALeaseExpiringMidSolve:
    """The reaper takes the row from under a running solve, and that is a race rather than a fault.

    Both actors go through one lifecycle, so a solve that outlived its lease finds its row already
    back in the queue and every step it tries applies to nothing. The refusal has two types exactly
    so this is distinguishable from a caller asking for a step the machine never had.

    Contained before this pass and misreported: `run()` raised, the runner's per-tenant boundary
    caught it, and a lease expiry read as an unexplained tenant fault on the runner's own counter.
    """

    async def test_the_dispatch_answers_with_the_row_the_reaper_left(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)

        finished = await a_solve_whose_lease_expires(sessions, context, owner, clock)

        assert finished.status == PENDING
        assert finished.attempt == 2
        assert finished.error_code == LEASE_EXPIRED

    async def test_nothing_of_the_overtaken_solve_is_written(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The containment half, which is the important one: the guard is what stops the write, so a
        # solve whose row moved on cannot leave a revision, a projection or a moved version behind.
        await declare_the_minimum(sessions, owner.tenant_id)
        held = await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)

        await a_solve_whose_lease_expires(sessions, context, owner, clock)

        assert await revisions_of(sessions, owner.tenant_id) == []
        assert await operations_of(sessions, owner.tenant_id, kind=PROJECTION) == []
        assert await version_of(sessions, owner) == held

    async def test_the_race_is_counted_as_a_race_rather_than_a_tenant_failure(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        live_plan_is_read: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The reporting half, which is what this pass fixed.

        A tenant-failure counter that moves for an expected race is a counter an operator cannot
        alert on, because the ordinary case and the fault read identically.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        await bump(sessions, owner, clock)
        monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)
        races = _sample("syncr_solve_claim_races_lost_total")
        tenant_faults = _sample("syncr_solve_tenant_failures_total")

        await a_solve_whose_lease_expires(sessions, context, owner, clock)

        assert _sample("syncr_solve_claim_races_lost_total") == races + 1
        assert _sample("syncr_solve_tenant_failures_total") == tenant_faults

    async def test_the_reaped_solve_reaches_the_solve_counter(
        self,
        sessions: async_sessionmaker[AsyncSession],
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """Which is what makes the supersession ratio a share of every solve rather than a subset.

        The reaper finishes an abandoned claim through the lifecycle directly, so counting in the
        coordinator omitted every reaped solve from the counter an operator tunes the debounce on.

        Driven to the attempt bound, and the count moves ONCE: the two reaps before it return the
        row to the queue as pending, which is a retry rather than an ending, so counting them would
        report one solve three times.
        """
        await declare_the_minimum(sessions, owner.tenant_id)
        before = _sample("syncr_solve_total", {"outcome": FAILED})

        for _ in range(MAX_ATTEMPTS):
            await requested(sessions, owner, clock)
            await claimed(sessions, owner, clock)
            clock.advance(LEASE * 2)
            async with sessions() as session, session.begin():
                assert (await maintenance_for(session, owner.tenant_id, clock).sweep()).reaped == 1

        assert _sample("syncr_solve_total", {"outcome": FAILED}) == before + 1


async def a_solve_whose_lease_expires(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    owner: UserRecord,
    clock: Ticking,
) -> OperationRecord:
    """One solve the reaper takes over between its load and its write.

    Driven through the real phases rather than through `run()`, because the interleaving is the
    whole subject: the reaper has to land after the inputs are loaded and before the guard is taken,
    and nothing outside the dispatch can open that window.
    """
    await requested(sessions, owner, clock)
    claim = await claimed(sessions, owner, clock)
    dispatch = dispatch_reading_the_live_plan(context, owner.tenant_id, clock)
    loaded = await dispatch._loaded(claim, WEEK)
    solved = await dispatch._solved(loaded, WEEK)

    clock.advance(LEASE * 2)
    async with sessions() as session, session.begin():
        assert (await maintenance_for(session, owner.tenant_id, clock).sweep()).reaped == 1

    return await dispatch._written(
        claim, WEEK, loaded, solved, classification_of(dispatch, loaded, solved)
    )


def _sample(family: str, labels: dict[str, str] | None = None) -> float:
    """One metric value, read as a scraper reads it rather than through a private attribute."""
    return REGISTRY.get_sample_value(family, labels or {}) or 0.0
