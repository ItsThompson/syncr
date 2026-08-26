"""A tradeoff request landing on a week whose solve is already running, against a real Postgres.

The window is the whole point and it is not narrow in practice: a solve is roughly a second and a
half, and a reader clicks a tradeoff while looking at the week the solve is about. So a request
arriving between the instant a solve loads its inputs and the instant it writes is the ordinary case
rather than a contrived one.

The two interleavings, each driven at the only instant it exists:

```
 t0  a solve is claimed and LOADS its inputs   ──▶ stamped at version V, and it SOLVES: one block
 t1a a tradeoff request closes the row          ──▶ superseded, naming the replacement it created
 t2a the solve finishes and steps its own row   ──▶ the step applies to nothing, so the whole write
                                                   transaction rolls back: no revision, no verdict
                                                   transition, no version bump, no projection

 t1b the solve finishes first                   ──▶ succeeded, and everything above is written
 t2b the tradeoff request closes the row        ──▶ the close applies to nothing, and the honest
                                                   answer is the replacement rather than a conflict
```

**The absences in the first order mean nothing on their own.** A solve that never began writes no
revision either. So every case here states what the running solve had already done -- it assembled
the week at a version the guard still matches, and it produced a document holding a block -- and the
control is the SAME interleaving with the request left out, where all four writes land. Only the
pair distinguishes a write that was discarded from a write that was never reachable.

**What the wire answers is asserted where a real request lives**,
``test_concession_routes_integration.py``: a request behind a running solve answers ``202`` with the
replacement, and one behind a solve that has already succeeded answers ``202`` too. This module owns
the transaction, which no request path can show.

The last class crosses the two instruments a discarded solve could be counted on, because they mean
two different events: a row skipped before any work, and a whole write thrown away.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select

from syncr_api.core.db import create_database, create_db_engine, create_sessionmaker
from syncr_api.core.settings import (
    DEFAULT_SOLVE_DEBOUNCE_MS,
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.plans.authority import classify
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.verdict_events import VerdictEventRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import (
    NON_TERMINAL_STATUSES,
    PENDING,
    PROJECTION,
    RUNNING,
    SOLVE,
    SUCCEEDED,
    SUPERSEDED,
)
from syncr_api.solving.coordinator import SolveCoordinator
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.models import Operation
from syncr_api.solving.outcomes import Superseded
from syncr_api.solving.repository import OperationRepository
from syncr_api.worker.main import WorkerContext
from syncr_common.metrics import REGISTRY
from syncr_domain.weeks import IsoWeek
from tests.live_minimums import a_placeable_task, declare_the_minimum
from tests.live_tenants import delete_tenant, seed_owner
from tests.test_solve_coordinator import StaleQueue
from tests.test_solve_runner_integration import _placing_one_block

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.records import PlanRevisionRecord, VerdictEventRecord
    from syncr_api.solving.dispatch import Loaded
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId
    from syncr_solver.solve import SolveResult

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
WEEK = IsoWeek(2026, 7)
# Wednesday morning of the week, so the week has a past and a future and the solver has somewhere to
# place work.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)

# The concession the request carries. Its figures come from the enumeration in production; what the
# coordinator does with it is decided by its presence, so a document of the right shape is enough.
A_CANDIDATE = {
    "adjustmentId": "6b0f52c8-7f8f-4a4e-8f5a-70e1a1c4d2e7",
    "kind": "breach_floor",
    "targetId": "8d4f1b6a-2c9e-4f0b-9d3a-5e6f7a8b9c0d",
    "reductions": {},
    "deltaMinutes": 60,
}


class Ticking:
    """A clock a test moves by hand, so the solve and the request are ordered by intent."""

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


@pytest.fixture
def solver_places_one_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """A solver answering with one block, which is what makes the write reachable at all.

    A week declared with an Area and one task solves to an empty document, which classifies as
    nothing and appends no revision: without this the control would assert about a solve that had
    nothing to write either way, and the discarded case would be indistinguishable from it.
    """
    monkeypatch.setattr("syncr_api.solving.dispatch.solve", _placing_one_block)


def a_coordinator(session: AsyncSession, owner: UserRecord, clock: Ticking) -> SolveCoordinator:
    return build_solve_coordinator(
        session,
        owner.tenant_id,
        clock=clock,
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
    )


def a_dispatch(context: WorkerContext, tenant_id: TenantId, clock: Ticking) -> SolveDispatch:
    return SolveDispatch(
        context.database,
        tenant_id,
        clock=clock,
        debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
    )


async def bump(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> int:
    """The version row the week arrives at the solve with, as an earlier mutation left it."""
    async with sessions() as session, session.begin():
        return await WeekInputVersionRepository(session, owner.tenant_id).bump(WEEK, at=clock())


async def version_of(sessions: async_sessionmaker[AsyncSession], owner: UserRecord) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, owner.tenant_id).current(WEEK)


async def holds(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, version: int, clock: Ticking
) -> bool:
    """Whether the week is still at ``version``: the statement the write is guarded on."""
    async with sessions() as session, session.begin():
        return await WeekInputVersionRepository(session, owner.tenant_id).holds_version(
            WEEK, version, at=clock()
        )


async def requested(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking, **overrides: Any
) -> OperationRecord:
    async with sessions() as session, session.begin():
        return await a_coordinator(session, owner, clock).request_solve(
            WEEK, 1, immediate=True, session_mode_active=False, **overrides
        )


async def claimed(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> OperationRecord:
    async with sessions() as session, session.begin():
        claim = await a_coordinator(session, owner, clock).claim_next()
    assert claim is not None, "the coordinator had no due operation to claim"
    return claim


async def revisions_of(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> list[PlanRevisionRecord]:
    async with sessions() as session:
        return await PlanRepository(session, owner.tenant_id).history(WEEK)


async def transitions_of(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> list[VerdictEventRecord]:
    async with sessions() as session:
        return await VerdictEventRepository(session, owner.tenant_id).for_week(WEEK)


async def operations_of(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, *, kind: str | None = None
) -> list[Operation]:
    async with sessions() as session:
        statement = select(Operation).where(Operation.tenant_id == owner.tenant_id)
        if kind is not None:
            statement = statement.where(Operation.kind == kind)
        found = await session.scalars(statement.order_by(Operation.scheduled_for))
        return list(found)


async def non_terminal_solves(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord
) -> list[Operation]:
    """Every solve of the week the partial unique index still counts.

    Read from the status set rather than by naming ``pending``, because what the index enforces is
    one non-terminal row: a case filtered to pending would report the invariant held while a running
    row sat beside the replacement.
    """
    return [
        one
        for one in await operations_of(sessions, owner, kind=SOLVE)
        if one.status in NON_TERMINAL_STATUSES
    ]


async def a_solve_that_has_loaded_and_run(
    sessions: async_sessionmaker[AsyncSession],
    context: WorkerContext,
    owner: UserRecord,
    clock: Ticking,
) -> tuple[OperationRecord, SolveDispatch, Loaded, SolveResult]:
    """A solve claimed, its inputs assembled, and the plan it produced: everything but the write.

    This is the state both orders interleave with, and it is what makes the absences afterwards mean
    something: the week was assembled at a version the guard still matches, and the solver answered
    with a document holding a block, so the write is reachable and its own control performs it.
    """
    claim = await claimed(sessions, owner, clock)
    dispatch = a_dispatch(context, owner.tenant_id, clock)
    loaded = await dispatch._loaded(claim, WEEK)
    solved = await dispatch._solved(loaded, WEEK)
    assert solved.document.blocks, "the substituted solver placed nothing, so no write is reachable"
    assert await holds(sessions, owner, loaded.input_version, clock) is True
    return claim, dispatch, loaded, solved


async def written(
    dispatch: SolveDispatch, claim: OperationRecord, loaded: Loaded, solved: SolveResult
) -> OperationRecord:
    """The write transaction, guard and all, exactly as ``run()`` reaches it."""
    return await dispatch._written(
        claim,
        WEEK,
        loaded,
        solved,
        classify(loaded.inputs.live_plan, solved.document, now=loaded.inputs.now),
    )


def _sample(family: str) -> float:
    """One counter, read as a scraper reads it rather than through a private attribute."""
    return REGISTRY.get_sample_value(family) or 0.0


class TestTheRequestClosesTheRowFirst:
    async def test_the_solves_write_transaction_rolls_back_whole(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        solver_places_one_block: None,
    ) -> None:
        """The four writes an adoption performs, none of which survives a row taken from under it.

        The version guard is NOT what stops this write: ``holds_version`` is asserted true after the
        request lands, because a request persists nothing and bumps nothing. What stops it is the
        operation's own terminal step applying to no row, which is the last statement of the
        transaction the other three writes are in.
        """
        await declare_the_minimum(sessions, owner.tenant_id, content=a_placeable_task)
        held = await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim, dispatch, loaded, solved = await a_solve_that_has_loaded_and_run(
            sessions, context, owner, clock
        )

        replacement = await requested(sessions, owner, clock, candidate=A_CANDIDATE)

        assert await holds(sessions, owner, loaded.input_version, clock) is True
        finished = await written(dispatch, claim, loaded, solved)

        assert finished.status == SUPERSEDED
        assert finished.superseded_by == replacement.id
        assert await revisions_of(sessions, owner) == []
        assert await transitions_of(sessions, owner) == []
        assert await version_of(sessions, owner) == held
        assert await operations_of(sessions, owner, kind=PROJECTION) == []

    async def test_the_same_solve_writes_all_four_when_no_request_arrives(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        solver_places_one_block: None,
    ) -> None:
        """The control, and what it rules out.

        Every assertion above is an absence, and a solve that never reached its write satisfies all
        of them. This is the same week, the same claim and the same document with the request left
        out: the revision is appended, the transition is written, the version moves and the
        projection is enqueued. So the four absences above are a write that was discarded rather
        than a write that was never reachable.
        """
        await declare_the_minimum(sessions, owner.tenant_id, content=a_placeable_task)
        held = await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim, dispatch, loaded, solved = await a_solve_that_has_loaded_and_run(
            sessions, context, owner, clock
        )

        finished = await written(dispatch, claim, loaded, solved)

        assert finished.status == SUCCEEDED
        assert len(await revisions_of(sessions, owner)) == 1
        assert len(await transitions_of(sessions, owner)) == 1
        assert await version_of(sessions, owner) == held + 1
        assert len(await operations_of(sessions, owner, kind=PROJECTION)) == 1

    async def test_the_week_is_left_holding_exactly_one_non_terminal_solve(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        solver_places_one_block: None,
    ) -> None:
        """The invariant the whole component exists for, after the exchange.

        The discarded solve enqueues no follow-up of its own, which is the half a second row would
        break: the replacement IS the follow-up, and it carries the concession the request asked
        about.
        """
        await declare_the_minimum(sessions, owner.tenant_id, content=a_placeable_task)
        await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim, dispatch, loaded, solved = await a_solve_that_has_loaded_and_run(
            sessions, context, owner, clock
        )
        replacement = await requested(sessions, owner, clock, candidate=A_CANDIDATE)

        await written(dispatch, claim, loaded, solved)

        left = await non_terminal_solves(sessions, owner)
        assert [one.id for one in left] == [replacement.id]
        assert [one.status for one in left] == [PENDING]
        assert [one.candidate_adjustment for one in left] == [A_CANDIDATE]


class TestTheWorkerCommitsFirst:
    async def test_the_request_answers_with_a_replacement_rather_than_a_conflict(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        solver_places_one_block: None,
    ) -> None:
        """The other order, and the answer that makes it honest.

        The solve committed everything it had, so nothing is in flight and there is nothing to
        supersede. The request therefore creates its own operation and the reader is told to follow
        it, which is the same answer they get on a quiet week.
        """
        await declare_the_minimum(sessions, owner.tenant_id, content=a_placeable_task)
        held = await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim, dispatch, loaded, solved = await a_solve_that_has_loaded_and_run(
            sessions, context, owner, clock
        )
        landed = await written(dispatch, claim, loaded, solved)

        replacement = await requested(sessions, owner, clock, candidate=A_CANDIDATE)

        assert landed.status == SUCCEEDED
        assert landed.superseded_by is None
        assert replacement.candidate_adjustment == A_CANDIDATE
        assert len(await revisions_of(sessions, owner)) == 1
        assert await version_of(sessions, owner) == held + 1
        assert [one.id for one in await non_terminal_solves(sessions, owner)] == [replacement.id]

    async def test_a_commit_inside_the_request_s_own_window_answers_the_same_way(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        solver_places_one_block: None,
    ) -> None:
        """The narrow form of this order: the row is read as running and closed after it commits.

        That window cannot be opened from outside one call, because the request reads the row and
        closes it in two statements of one transaction and a second session's commit is visible to
        the second of them. So the read is a real read, the commit is a real write transaction, and
        what is driven is the branch the real race reaches: the close applying to no row.

        Left to raise, this is a 500 on a request that changed nothing and a reader told the product
        broke when what happened is that their answer arrived.
        """
        await declare_the_minimum(sessions, owner.tenant_id, content=a_placeable_task)
        await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim, dispatch, loaded, solved = await a_solve_that_has_loaded_and_run(
            sessions, context, owner, clock
        )

        async with sessions() as session, session.begin():
            requesting = a_coordinator(session, owner, clock)
            in_flight = await OperationRepository(session, owner.tenant_id).in_flight(
                WEEK, kind=SOLVE
            )
            assert in_flight is not None
            assert in_flight.status == RUNNING
            landed = await written(dispatch, claim, loaded, solved)
            replacement = await requesting._for_a_candidate(
                WEEK, in_flight, A_CANDIDATE, at_version=1, session_mode_active=False
            )

        assert landed.status == SUCCEEDED
        assert landed.superseded_by is None
        assert replacement.candidate_adjustment == A_CANDIDATE
        assert len(await revisions_of(sessions, owner)) == 1
        assert [one.id for one in await non_terminal_solves(sessions, owner)] == [replacement.id]


class TestTheTwoRacesAreCountedApart:
    """One instrument per event, because the two have different consequences and different repairs.

    A claim race is a row skipped before any work: the winner is doing it. A solve taken from under
    its own write assembled a week, ran a solve and threw the result away. An operator reading one
    number for both cannot tell a busy editing session from a worker losing its leases.
    """

    async def test_a_solve_taken_from_under_its_write_moves_its_own_counter_alone(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
        solver_places_one_block: None,
    ) -> None:
        await declare_the_minimum(sessions, owner.tenant_id, content=a_placeable_task)
        await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim, dispatch, loaded, solved = await a_solve_that_has_loaded_and_run(
            sessions, context, owner, clock
        )
        await requested(sessions, owner, clock, candidate=A_CANDIDATE)
        taken_over = _sample("syncr_solve_taken_over_total")
        claim_races = _sample("syncr_solve_claim_races_lost_total")

        await written(dispatch, claim, loaded, solved)

        assert _sample("syncr_solve_taken_over_total") == taken_over + 1.0
        assert _sample("syncr_solve_claim_races_lost_total") == claim_races

    async def test_a_lost_claim_race_moves_its_own_counter_alone(
        self,
        sessions: async_sessionmaker[AsyncSession],
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        # The other edge, on the same pair of readings. The scan's own window cannot be opened from
        # outside the coordinator, so the queue stands for a row that moved inside it and what runs
        # is the branch a real lost race reaches.
        created = await requested(sessions, owner, clock)
        async with sessions() as session, session.begin():
            await OperationLifecycle(OperationRepository(session, owner.tenant_id), clock).finish(
                created.id, Superseded()
            )
        taken_over = _sample("syncr_solve_taken_over_total")
        claim_races = _sample("syncr_solve_claim_races_lost_total")

        async with sessions() as session, session.begin():
            operations = OperationRepository(session, owner.tenant_id)
            scanning = SolveCoordinator(
                operations=operations,
                queue=StaleQueue((created,)),
                lifecycle=OperationLifecycle(operations, clock),
                clock=clock,
                debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
            )
            assert await scanning.claim_next() is None

        assert _sample("syncr_solve_claim_races_lost_total") == claim_races + 1.0
        assert _sample("syncr_solve_taken_over_total") == taken_over
