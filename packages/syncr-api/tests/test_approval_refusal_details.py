"""The two refusals over a slot with nothing in it, and what makes them two rather than one.

A week that has never proposed anything and a week whose proposal an approval already took answer
one status and one problem type, so nothing a client reads mechanically can separate them. The
detail is what separates them, and the detail is text a person reads: the CLI prints it under the
title and the grid renders it beside a refresh. Telling a caller whose week has never held a
proposal that "that proposal has been replaced" is a refusal whose stated reason is false.

Both conditions are driven here, in one module and against one tenant, so neither detail can be
produced by the other's path: the same call is made three times against three states and the only
thing that varies is what the week holds.

The third case is what fixes which read decides this. A week whose first solve auto-applied a fill
holds a plan of record and has never proposed anything, so a read of the plan would answer
supersession for a week nothing was ever proposed to. The read is of the ASSENT.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from syncr_api.approvals.injection import build_approval_service
from syncr_api.approvals.service import EMPTY_SLOT_DETAIL, REPLACED_DETAIL
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.errors import Conflict
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import Scope
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_domain.identity import BindingRef
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import WEEK, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_domain.plan import PlanDocument

pytestmark = pytest.mark.integration

# Before the week begins, so nothing in it has been reached and the assent check has nothing to
# refuse for a reason other than the one under test.
BEFORE_THE_WEEK = datetime(2026, 2, 8, tzinfo=UTC)
AT_APPROVAL = datetime(2026, 2, 8, 12, 0, tzinfo=UTC)

GYM = BindingRef.for_habit(uuid4(), index=0)

BREAKDOWN: dict[str, Any] = {"deadline_risk": 0.0, "budget_deviation": 12.5}
FEASIBLE: dict[str, Any] = {"feasible": True, "shortfall_minutes": 0, "provenance": "solver"}

SLOT_VERSION = 41
WEIGHTS = 7


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


def principal_of(owner: UserRecord) -> Principal:
    return Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=frozenset(Scope))


def a_week(*blocks: Any) -> PlanDocument:
    return a_document(week=WEEK, blocks=blocks)


async def seed_slot(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, document: PlanDocument
) -> None:
    async with sessions() as session, session.begin():
        await PendingProposalRepository(session, owner.tenant_id).replace(
            document=stored_document(document),
            proposal_diff={"added": [], "removed": [], "moved": []},
            objective_breakdown=BREAKDOWN,
            verdict=FEASIBLE,
            weight_set_version=WEIGHTS,
            input_version=SLOT_VERSION,
            operation_id=uuid4(),
            created_at=BEFORE_THE_WEEK,
        )


async def seed_an_auto_applied_fill(
    sessions: async_sessionmaker[AsyncSession], owner: UserRecord, document: PlanDocument
) -> None:
    """A plan of record nobody assented to, which is what a week's first solve appends."""
    async with sessions() as session, session.begin():
        await PlanRepository(session, owner.tenant_id).append(
            document=stored_document(document),
            objective_breakdown=BREAKDOWN,
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=WEIGHTS,
            input_version=SLOT_VERSION,
            created_at=BEFORE_THE_WEEK,
        )


async def approve(sessions: async_sessionmaker[AsyncSession], owner: UserRecord) -> None:
    async with sessions() as session, session.begin():
        service = build_approval_service(session, owner.tenant_id, clock=lambda: AT_APPROVAL)
        await service.approve(principal_of(owner), str(WEEK))


async def refusal(sessions: async_sessionmaker[AsyncSession], owner: UserRecord) -> Conflict:
    """The conflict one approval raises, for a test that reads its words rather than its type."""
    with pytest.raises(Conflict) as raised:
        await approve(sessions, owner)
    return raised.value


async def statuses_of(sessions: async_sessionmaker[AsyncSession], owner: UserRecord) -> list[str]:
    async with sessions() as session:
        found = await session.scalars(
            select(PlanRevision.status)
            .where(PlanRevision.tenant_id == owner.tenant_id)
            .order_by(PlanRevision.created_at, PlanRevision.id)
        )
        return list(found)


class TestAnEmptySlotSaysWhichEmptinessItIs:
    async def test_a_slot_that_was_never_filled_and_one_an_approval_took_read_differently(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """One week, one caller, two states, two sentences.

        The first refusal is against a week that has proposed nothing. The second is against the
        same week after a proposal was made and approved, which is the only thing that empties a
        filled slot. A client that read the first sentence and re-read the week would find nothing
        waiting, and a client that read the second would find the plan it now holds.
        """
        never_filled = await refusal(sessions, owner)

        await seed_slot(sessions, owner, a_week(a_block_holding(GYM, between(9, 10))))
        await approve(sessions, owner)
        already_taken = await refusal(sessions, owner)

        assert never_filled.detail == EMPTY_SLOT_DETAIL
        assert already_taken.detail == REPLACED_DETAIL
        assert "is not proposing anything" in never_filled.detail
        assert "has been replaced" in already_taken.detail
        assert "has been replaced" not in never_filled.detail
        assert "is not proposing anything" not in already_taken.detail
        assert await statuses_of(sessions, owner) == ["approved"]

    async def test_neither_refusal_mints_a_problem_type_or_a_status_of_its_own(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Two details, one condition. The code a caller branches on may not have moved.

        A CLI decides its exit code from the type and falls back to the status, so a second type
        here would be a second exit code for one thing that went wrong.
        """
        never_filled = await refusal(sessions, owner)

        await seed_slot(sessions, owner, a_week(a_block_holding(GYM, between(9, 10))))
        await approve(sessions, owner)
        already_taken = await refusal(sessions, owner)

        assert never_filled.detail != already_taken.detail
        assert never_filled.type == already_taken.type == "syncr:conflict"
        assert never_filled.status == already_taken.status == 409

    async def test_a_week_whose_only_plan_is_a_fill_nobody_assented_to_still_names_emptiness(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The plan of record is not the evidence. Assent is.

        A week's first solve appends its plan rather than proposing it, so this week holds a
        revision and has never held a proposal. Reading the plan would answer supersession here,
        which is the same false reason in a new place.
        """
        await seed_an_auto_applied_fill(
            sessions, owner, a_week(a_block_holding(GYM, between(9, 10)))
        )

        refused = await refusal(sessions, owner)

        assert refused.detail == EMPTY_SLOT_DETAIL
        assert "is not proposing anything" in refused.detail
        assert "has been replaced" not in refused.detail
        assert await statuses_of(sessions, owner) == ["applied"]
