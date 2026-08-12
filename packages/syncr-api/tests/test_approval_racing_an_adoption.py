"""An approval racing an adoption, over two connections: the window the lock closes.

The approval decides its refusal from the live plan it read, so it has to hold the live plan while
it decides. Without that hold there is a window -- read the slot, read the live plan, deserialise
two documents, re-classify, append -- in which the solve dispatch's conditional write can commit an
``applied`` revision that the comparison cannot see. The approved document then drops the block that
revision added, **and nothing puts it back**: approval requests no solve, and the solve that
appended the fill has already reported ``succeeded``. This race reaches that end through a read
rather than through version lag.

What closes it is the week's version row, taken ``FOR UPDATE`` before anything is read, which is the
row the conditional write already locks.

Two tests, one per side of the interleaving, both sequenced by events rather than by sleeping so the
order is stated rather than hoped for:

```
 the approval first    lock -> read -> (the adoption tries and waits) -> write -> commit
                       the adoption then finds its version moved and writes nothing

 the adoption first    append -> bump -> commit
                       the approval then SEES the fill and is refused
```

The adoption is composed here from the two statements the dispatch's guarded write performs, in its
order: ``holds_version`` and then the append. Driving a whole solve to get one ``applied`` revision
would put the solver's own placement decisions between the assertion and what it is about.

The invariants asserted are over rows and hold whichever racer wins: no revision drops a block its
predecessor held unless something said so, and no two revisions claim one predecessor.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from syncr_api.approvals.service import ApprovalService
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.errors import Conflict
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import Scope
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.repository import OperationRepository
from syncr_domain.identity import BindingRef
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import WEEK, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.identifiers import TenantId
    from syncr_domain.plan import Block, PlanDocument
    from syncr_domain.weeks import IsoWeek

pytestmark = pytest.mark.integration

# Before the week begins, so nothing in it has been reached and the past rule is not what refuses.
BEFORE_THE_WEEK = datetime(2026, 2, 8, tzinfo=UTC)
AT_APPROVAL = datetime(2026, 2, 8, 12, 0, tzinfo=UTC)

GYM = BindingRef.for_habit(uuid4(), index=0)
CAPTURED = BindingRef.for_task(uuid4())

BREAKDOWN: dict[str, Any] = {"deadline_risk": 0.0, "budget_deviation": 0.0}
A_VERDICT: dict[str, Any] = {"feasible": True, "shortfall_minutes": 0, "provenance": "solver"}
SLOT_VERSION = 1
WEIGHTS = 3

# How long the approval waits for the adoption to commit inside its window before going on. Only
# reached when the lock holds the adoption out, which is the case this exists to observe: without
# the lock the adoption commits in single-digit milliseconds.
WINDOW = 1.0


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


def a_week(*blocks: Block) -> PlanDocument:
    return a_document(week=WEEK, blocks=blocks)


THE_LIVE_PLAN = a_week(a_block_holding(GYM, between(9, 10)))
# What a task captured into a free gap auto-applies: the live plan plus one block and nothing moved,
# which is the only shape the authority rule lets through without asking.
THE_FILL = a_week(a_block_holding(GYM, between(9, 10)), a_block_holding(CAPTURED, between(14, 15)))


class YieldsAfterReadingTheLivePlan(PlanRepository):
    """The live-plan read, with the window it opens made observable.

    Announces that it has answered and then waits for the racing adoption to commit, which is the
    interleaving the guard has to survive. When the version lock holds that adoption out the wait
    times out, and the timeout is the observation: the caller's ``committed`` event stays clear.
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: TenantId,
        *,
        has_read: asyncio.Event,
        committed: asyncio.Event,
    ) -> None:
        super().__init__(session, tenant_id)
        self._has_read = has_read
        self._committed = committed

    async def latest(self, iso_week: IsoWeek) -> Any:
        found = await super().latest(iso_week)
        self._has_read.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._committed.wait(), timeout=WINDOW)
        return found


def a_service_yielding_after_the_read(
    session: AsyncSession,
    tenant_id: TenantId,
    *,
    has_read: asyncio.Event,
    committed: asyncio.Event,
) -> ApprovalService:
    """The production service with one collaborator replaced by the seam above."""
    return ApprovalService(
        revisions=YieldsAfterReadingTheLivePlan(
            session, tenant_id, has_read=has_read, committed=committed
        ),
        proposals=PendingProposalRepository(session, tenant_id),
        adjustments=WeekAdjustmentRepository(session, tenant_id),
        versions=WeekInputVersionRepository(session, tenant_id),
        operations=OperationLifecycle(OperationRepository(session, tenant_id), lambda: AT_APPROVAL),
        clock=lambda: AT_APPROVAL,
    )


async def seed(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> None:
    """The live plan, a proposal that changes nothing about it, and a version row at 1.

    The slot's document IS the live plan and its diff is empty, so the approval asks for no change
    at all: any block missing from the approved revision was dropped by this race rather than by the
    proposal.
    """
    async with sessions() as session, session.begin():
        await PlanRepository(session, tenant_id).append(
            document=stored_document(THE_LIVE_PLAN),
            objective_breakdown=BREAKDOWN,
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=WEIGHTS,
            input_version=SLOT_VERSION,
            created_at=BEFORE_THE_WEEK,
        )
        await PendingProposalRepository(session, tenant_id).replace(
            document=stored_document(THE_LIVE_PLAN),
            proposal_diff={"added": [], "removed": [], "moved": []},
            objective_breakdown=BREAKDOWN,
            verdict=A_VERDICT,
            weight_set_version=WEIGHTS,
            input_version=SLOT_VERSION,
            operation_id=uuid4(),
            created_at=BEFORE_THE_WEEK,
        )
        await WeekInputVersionRepository(session, tenant_id).bump(WEEK, at=BEFORE_THE_WEEK)


async def approve_yielding_after_the_read(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    *,
    has_read: asyncio.Event,
    committed: asyncio.Event,
) -> object:
    """One approval, over its own connection, announcing the window it opens."""
    async with sessions() as session, session.begin():
        service = a_service_yielding_after_the_read(
            session, owner.tenant_id, has_read=has_read, committed=committed
        )
        return await service.approve(
            Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset(Scope)),
            str(WEEK),
        )


async def adopt_a_fill(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    *,
    when: asyncio.Event | None = None,
    done: asyncio.Event | None = None,
    attempted: asyncio.Event | None = None,
) -> bool:
    """The dispatch's guarded write, composed from the two statements it performs in its order.

    Answers whether the fill was adopted. ``holds_version`` is what takes the version row, so this
    is the transaction the approval has to be serialized against, and a mismatch is the dispatch's
    own supersession: it writes nothing at all.
    """
    if when is not None:
        await when.wait()
    async with sessions() as session, session.begin():
        if attempted is not None:
            attempted.set()
        versions = WeekInputVersionRepository(session, tenant_id)
        if not await versions.holds_version(WEEK, SLOT_VERSION, at=BEFORE_THE_WEEK):
            return False
        await PlanRepository(session, tenant_id).append(
            document=stored_document(THE_FILL),
            objective_breakdown=BREAKDOWN,
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=WEIGHTS,
            input_version=SLOT_VERSION,
            created_at=datetime(2026, 2, 8, 11, 0, tzinfo=UTC),
        )
        await versions.bump(WEEK, at=BEFORE_THE_WEEK)
    if done is not None:
        done.set()
    return True


async def revisions_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> Sequence[PlanRevision]:
    async with sessions() as session:
        found = await session.scalars(
            select(PlanRevision)
            .where(PlanRevision.tenant_id == tenant_id)
            .order_by(PlanRevision.created_at, PlanRevision.id)
        )
        return list(found)


def blocks_of(revision: PlanRevision) -> set[str]:
    return {block["title"] for block in revision.document["blocks"]}


def unassented_drops(landed: Sequence[PlanRevision]) -> set[str]:
    """Blocks the product applied on its own that the plan of record no longer holds.

    The proposal in this fixture changes nothing, so every such block was dropped by the race. Read
    over the rows rather than over what either racer returned, because the plan of record is the
    claim.
    """
    applied = [one for one in landed if one.status == "applied"]
    if not applied:
        return set()
    return blocks_of(applied[-1]) - blocks_of(landed[-1])


def forked_predecessors(landed: Sequence[PlanRevision]) -> list[str]:
    """Revisions claimed as a predecessor more than once, which is a chain that branched.

    Cosmetic today, because nothing walks the chain, and a symptom of exactly the interleaving
    above: two writers both read the same revision as the newest one.
    """
    claimed = [str(one.supersedes_id) for one in landed if one.supersedes_id is not None]
    return sorted({one for one in claimed if claimed.count(one) > 1})


class TestAnApprovalRacingAnAdoption:
    async def test_the_adoption_cannot_commit_inside_the_approvals_window(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The lock, observed rather than inferred: the racer is held out of the window itself.

        The approval takes the version row before it reads, so the adoption's own
        ``SELECT ... FOR UPDATE`` waits. It then finds the version this approval bumped and writes
        nothing, which is the dispatch's ordinary supersession.
        """
        await seed(sessions, owner.tenant_id)
        has_read = asyncio.Event()
        committed = asyncio.Event()

        approving = asyncio.create_task(
            approve_yielding_after_the_read(sessions, owner, has_read=has_read, committed=committed)
        )
        adopting = asyncio.create_task(
            adopt_a_fill(sessions, owner.tenant_id, when=has_read, done=committed)
        )
        approved = await approving

        # The observation: the adoption could not commit while the approval held the row.
        assert not committed.is_set()
        assert await adopting is False
        assert approved is not None
        landed = await revisions_of(sessions, owner.tenant_id)
        assert [one.status for one in landed] == ["applied", "approved"]
        assert unassented_drops(landed) == set()
        assert forked_predecessors(landed) == []

    async def test_an_adoption_that_wins_the_lock_is_seen_and_the_approval_is_refused(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The other side of the same interleaving, and the control on the test above.

        With the fill committed before the approval reads, the comparison sees it and refuses: the
        block stays in the plan of record. Without this, the test above could be passing because
        nothing in the fixture produces a fill at all.
        """
        await seed(sessions, owner.tenant_id)

        assert await adopt_a_fill(sessions, owner.tenant_id) is True
        with pytest.raises(Conflict, match="without asking"):
            await approve_yielding_after_the_read(
                sessions, owner, has_read=asyncio.Event(), committed=asyncio.Event()
            )

        landed = await revisions_of(sessions, owner.tenant_id)
        assert [one.status for one in landed] == ["applied", "applied"]
        assert unassented_drops(landed) == set()
        assert blocks_of(landed[-1]) == {block.title for block in THE_FILL.blocks}
