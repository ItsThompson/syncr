"""Smoke scenario S30: approving while a solve is running, against a real Postgres.

The interleaving, driven at the only instant it can be:

```
 t0  a solve is claimed and LOADS its inputs   ──▶ stamped at version V
 t1  the user approves the pending proposal    ──▶ the live plan changes, V becomes V+1
 t2  the solve finishes and takes the row lock ──▶ V+1 != V, so it is SUPERSEDED
 t3  the follow-up reads the approved plan AND the concession the approval persisted
```

Without the bump at t1 the guard matches on a version the approval did not change, and the solve
adopts a classification computed against a plan of record that no longer exists together with a
document solved without the concession. That is why the bump is part of what approval must do
rather than only an invariant of the version row.

Four observations, one per clause of S30: the running operation reports ``superseded`` rather than
``succeeded``; the approved revision is the plan of record; the follow-up reads both the new live
plan and the approved concession; and nothing proposes undoing the approval.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest

from syncr_api.approvals.injection import build_approval_service
from syncr_api.core.db import create_database, create_db_engine, create_sessionmaker
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import Scope
from syncr_api.core.settings import (
    DEFAULT_SOLVE_DEBOUNCE_MS,
    WORKER_SERVICE,
    EnvSettings,
    build_service_settings,
)
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.authority import classify
from syncr_api.plans.candidates import as_document
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import SUCCEEDED, SUPERSEDED
from syncr_api.solving.dispatch import SolveDispatch
from syncr_api.solving.injection import build_solve_coordinator, debounce_window
from syncr_api.worker.main import WorkerContext
from syncr_domain.plan import AdjustmentKind
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import WeekAdjustment
from tests.live_minimums import AREA_FLOOR_HOURS, a_placeable_task, declare_the_minimum
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import a_document

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

WEEK = IsoWeek(2026, 7)
# Wednesday morning of the week, so the week has a past and a future and the two solves have
# somewhere to place work.
NOW = datetime(2026, 2, 11, 9, 0, tzinfo=UTC)

MINUTES_PER_HOUR = 60
BREACH_MINUTES = 45

BREAKDOWN: dict[str, Any] = {"deadline_risk": 0.0, "budget_deviation": 0.0}
A_VERDICT: dict[str, Any] = {"feasible": True, "shortfall_minutes": 0, "provenance": "solver"}


class Ticking:
    """A clock a test moves by hand, so the two solves and the approval are ordered by intent."""

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


async def seed_a_tradeoff_proposal(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, area_id: UUID
) -> UUID:
    """A proposal awaiting assent that carries a concession, and holds no blocks at all.

    Empty on purpose. What S30 is about is the guard, and an empty plan of record makes the
    follow-up's classification unambiguous: everything the next solve places lands in space no live
    block covered, so it auto-applies and proposes nothing. A fabricated block would instead be
    proposed for removal by every later solve, which would make the fourth observation unreadable.
    """
    conceded = uuid4()
    async with sessions() as session, session.begin():
        await PendingProposalRepository(session, tenant_id).replace(
            document=stored_document(a_document(week=WEEK, blocks=(), adjustments=(conceded,))),
            proposal_diff={"added": [], "removed": [], "moved": []},
            objective_breakdown=BREAKDOWN,
            verdict=A_VERDICT,
            weight_set_version=1,
            input_version=1,
            operation_id=uuid4(),
            created_at=NOW,
            candidate_adjustment=as_document(
                WeekAdjustment(
                    adjustment_id=conceded,
                    kind=AdjustmentKind.BREACH_FLOOR,
                    target_id=area_id,
                    reductions={},
                    delta_minutes=BREACH_MINUTES,
                )
            ),
        )
    return conceded


async def requested(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> OperationRecord:
    async with sessions() as session, session.begin():
        return await build_solve_coordinator(
            session,
            owner.tenant_id,
            clock=clock,
            debounce=debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS),
        ).request_solve(WEEK, 1, immediate=True, session_mode_active=False)


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


async def approve(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> Any:
    async with sessions() as session, session.begin():
        service = build_approval_service(session, owner.tenant_id, clock=clock)
        return await service.approve(
            Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset(Scope)),
            str(WEEK),
        )


class TestApprovingDuringARunningSolve:
    async def test_the_running_solve_is_superseded_and_the_approved_revision_is_the_plan_of_record(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """S30's first two observations, and the race the version bump closes.

        The approval lands between the load and the guarded write, which is the whole window: one
        keystroke against a two-second solve. The solve then writes nothing at all, so the plan of
        record is what the user assented to rather than a plan produced against the week as it was
        before they did.
        """
        area_id = (
            await declare_the_minimum(sessions, owner.tenant_id, content=a_placeable_task)
        ).area_id
        await seed_a_tradeoff_proposal(sessions, owner.tenant_id, area_id)
        await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim = await claimed(sessions, owner, clock)
        dispatch = a_dispatch(context, owner.tenant_id, clock)
        loaded = await dispatch._loaded(claim, WEEK)

        approved = await approve(sessions, owner, clock)
        solved = await dispatch._solved(loaded, WEEK)
        finished = await dispatch._written(
            claim,
            WEEK,
            loaded,
            solved,
            classify(loaded.inputs.live_plan, solved.document, now=loaded.inputs.now),
        )

        assert loaded.input_version == 1
        assert approved.input_version == 2
        assert finished.status == SUPERSEDED
        assert finished.status != SUCCEEDED
        live = await latest_revision(sessions, owner.tenant_id)
        assert live is not None
        assert live.id == approved.revision.id
        assert live.status == "approved"

    async def test_the_follow_up_reads_the_new_live_plan_and_the_approved_concession(
        self,
        sessions: async_sessionmaker[AsyncSession],
        context: WorkerContext,
        owner: UserRecord,
        clock: Ticking,
    ) -> None:
        """S30's third and fourth observations, driven through the follow-up the guard enqueued.

        The supersession enqueues exactly one solve, and that solve is what makes the week converge.
        It reads two things the superseded one could not: the plan of record the approval appended,
        and the concession the same transaction persisted, which shows up as the Area's floor being
        lower by exactly what was conceded.

        Nothing proposes undoing the approval: what the follow-up produces lands in space the
        approved plan left empty, so the authority rule applies it and the slot stays empty.
        """
        area_id = (
            await declare_the_minimum(sessions, owner.tenant_id, content=a_placeable_task)
        ).area_id
        conceded = await seed_a_tradeoff_proposal(sessions, owner.tenant_id, area_id)
        await bump(sessions, owner, clock)
        await requested(sessions, owner, clock)
        claim = await claimed(sessions, owner, clock)
        dispatch = a_dispatch(context, owner.tenant_id, clock)
        loaded = await dispatch._loaded(claim, WEEK)
        approved = await approve(sessions, owner, clock)
        solved = await dispatch._solved(loaded, WEEK)
        await dispatch._written(
            claim,
            WEEK,
            loaded,
            solved,
            classify(loaded.inputs.live_plan, solved.document, now=loaded.inputs.now),
        )

        clock.advance(timedelta(seconds=5))
        follow_up = await claimed(sessions, owner, clock)
        again = a_dispatch(context, owner.tenant_id, clock)
        reloaded = await again._loaded(follow_up, WEEK)

        assert follow_up.id != claim.id
        # The new live plan: the document the user approved, not the one the first solve read.
        assert reloaded.inputs.live_plan is not None
        assert reloaded.inputs.input_version == approved.input_version
        # The concession, as the figure it lowered rather than as the presence of a row.
        assert [one.adjustment_id for one in reloaded.inputs.adjustments] == [conceded]
        floors = {one.area_id: one.floor_minutes for one in reloaded.inputs.areas}
        assert floors[area_id] == int(AREA_FLOOR_HOURS) * MINUTES_PER_HOUR - BREACH_MINUTES

        landed = await again.run(follow_up, WEEK)

        assert landed.status == SUCCEEDED
        # The follow-up ADOPTED a plan rather than proposing one, which is what makes the two
        # assertions below say something: it appended an applied revision holding blocks, so the
        # empty slot is a slot nothing is waiting in rather than a solve that placed nothing.
        adopted = await latest_revision(sessions, owner.tenant_id)
        assert adopted is not None
        assert adopted.status == "applied"
        assert adopted.document["blocks"]
        # Nothing proposes undoing the approval: the slot is empty, and the concession still stands.
        async with sessions() as session:
            assert await PendingProposalRepository(session, owner.tenant_id).find(WEEK) is None
            held = await WeekAdjustmentRepository(session, owner.tenant_id).for_week(WEEK)
        assert [one.id for one in held] == [conceded]
        assert [one.delta_minutes for one in held] == [BREACH_MINUTES]


async def bump(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, clock: Ticking
) -> int:
    """One mutation's version bump, which is what puts a row on the week before the solve loads."""
    async with sessions() as session, session.begin():
        return await WeekInputVersionRepository(session, owner.tenant_id).bump(WEEK, at=clock())


async def latest_revision(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> Any:
    async with sessions() as session:
        return await PlanRepository(session, tenant_id).latest(WEEK)
