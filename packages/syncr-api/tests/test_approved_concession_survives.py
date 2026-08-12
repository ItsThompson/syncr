"""An approved concession survives: the gap it quoted closes, the next week is clean, once only.

An approved concession, driven through the APPROVAL rather than through a
candidate.
The fold's own suite asserts the direction of each kind against a candidate the assembler is handed;
what nothing asserted is the same observation once the concession is a stored ROW that an approval
wrote, which is the path a user's week actually takes.

Neither ``S9`` nor ``S26`` checked the verdict afterwards, which is why
``breach_floor`` could have shipped not doing what the panel said it did.

Three claims, and each is about rows rather than functions.

**The shortfall the panel quoted has closed by at least what the row concedes**, per kind. The
concession is read back out of the concession table by a real repository inside an otherwise-fake
assembly, so the arithmetic runs over the column the approval wrote rather than over the value it
was handed.

**The concession does not carry into the following week.** It is week-scoped, so the same assembly
one week later resolves the floor it was never conceded.

**Approving the same tradeoff twice does not double its effect**, and the unique index on
``(week, kind, target)`` is what makes that true rather than the upsert having been written
correctly. The second approval REPLACES the first, and the replaced row keeps its own identifier,
which is the decision the concession table states and the reason the history reports that concession
as REPLACED rather than as revoked: it is still in force, under a name the second revision does not
use. So the pairing is asserted through the history read as well as the figure.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from syncr_api.approvals.injection import build_approval_service
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import Scope
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.candidates import as_document
from syncr_api.plans.injection import build_week_service
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_domain.feasibility import ShortfallKind, probe
from syncr_domain.fixtures import elastic_sleep
from syncr_domain.plan import AdjustmentKind
from tests.assembly_fakes import WEEK
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import a_document
from tests.tradeoff_weeks import a_week_every_kind_can_be_offered_in, an_offered, minutes_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.records import WeekAdjustmentRecord
    from syncr_api.plans.week_views import WeekRevisions
    from syncr_domain.identifiers import TenantId
    from syncr_solver.inputs import SolveInputs, WeekAdjustment

pytestmark = pytest.mark.integration

# The instant the shared week is assembled and probed at, which is the fixture's own.
NOW = elastic_sleep.NOW
NEXT_WEEK = WEEK.following()

# The gap every kind is offered against in this week. Load-bearing rather than incidental: nothing
# after the deadline can absorb a floor here, so the whole reservation is charged before it and a
# breach lowers the competition by the whole of what it concedes. Relax that and the figure becomes
# an upper bound, which `test_tradeoff_folding` draws.
QUOTED_AGAINST = ShortfallKind.DEADLINE_CAPACITY

BREAKDOWN: dict[str, Any] = {"deadline_risk": 0.0, "budget_deviation": 0.0}
A_VERDICT: dict[str, Any] = {"feasible": False, "shortfall_minutes": 320, "provenance": "probe"}


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


async def approve_the_offer(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    owner: UserRecord,
    candidate: WeekAdjustment,
    *,
    at: Any = NOW,
    solved_under: tuple[UUID, ...] | None = None,
) -> None:
    """Put a proposal carrying ``candidate`` in the week's slot, then approve it for real.

    The document is empty of blocks and names the concession the solve was run under, which is the
    pair the worker writes: what this suite measures is the concession's effect on the NEXT
    assembly, and a fabricated plan would put the authority rule between the two.

    ``solved_under`` states the whole list of identifiers the document names, for a solve that read
    stored concessions as well as its own candidate. It defaults to the candidate alone.
    """
    async with sessions() as session, session.begin():
        await PendingProposalRepository(session, tenant_id).replace(
            document=stored_document(
                a_document(
                    week=WEEK,
                    blocks=(),
                    adjustments=solved_under or (candidate.adjustment_id,),
                )
            ),
            proposal_diff={"added": [], "removed": [], "moved": []},
            objective_breakdown=BREAKDOWN,
            verdict=A_VERDICT,
            weight_set_version=1,
            input_version=1,
            operation_id=uuid4(),
            created_at=NOW,
            candidate_adjustment=as_document(candidate),
        )
    async with sessions() as session, session.begin():
        service = build_approval_service(session, tenant_id, clock=lambda: at)
        await service.approve(
            Principal(tenant_id=tenant_id, user_id=owner.id, scopes=frozenset(Scope)), str(WEEK)
        )


async def assembled_reading_the_stored_concessions(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, week: Any = WEEK
) -> SolveInputs:
    """The shared week, with the concession seam wired to the REAL table.

    One seam changed and every other one the fixture's own, which is what makes the measurement
    about the stored row: the same week, resolved twice, differing only by what the approval wrote.
    """
    async with sessions() as session:
        assembler = a_week_every_kind_can_be_offered_in(
            adjustments=WeekAdjustmentRepository(session, tenant_id)
        )
        return await assembler.assemble(week, NOW)


async def concessions_held(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, *, week: Any = WEEK
) -> Sequence[WeekAdjustmentRecord]:
    async with sessions() as session:
        return await WeekAdjustmentRepository(session, tenant_id).for_week(week)


async def the_history(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId, owner: UserRecord
) -> WeekRevisions:
    """The week's revision history as the route answers with it, newest first.

    Read through the week service rather than composed here, so what is asserted is the answer a
    client gets: the rows an approval wrote, paired against the concessions the week holds now.
    """
    async with sessions() as session:
        service = build_week_service(session, tenant_id, clock=lambda: NOW)
        return await service.revisions(
            Principal(tenant_id=tenant_id, user_id=owner.id, scopes=frozenset(Scope)), str(WEEK)
        )


class TestTheGapAnApprovedTradeoffQuoted:
    @pytest.mark.parametrize("kind", list(AdjustmentKind))
    async def test_the_shortfall_closes_by_at_least_what_the_approved_concession_states(
        self,
        kind: AdjustmentKind,
        sessions: async_sessionmaker[AsyncSession],
        owner: UserRecord,
    ) -> None:
        """The end-to-end observation, per kind, over the row an approval wrote.

        The user clicks a tradeoff, approves the proposal it produced, and the figure the panel
        quoted must move by at least what it promised. The gap is asserted to be the only one of
        its kind first, so the measurement cannot silently take a different deadline's shortfall
        than the one the offer was computed against.
        """
        _, before, offer = await an_offered(kind)
        quoted = probe(before.for_probe())
        candidate = offer.as_candidate(adjustment_id=uuid4())

        await approve_the_offer(sessions, owner.tenant_id, owner, candidate)

        gaps = [one for one in quoted.shortfalls if one.kind is QUOTED_AGAINST]
        assert len(gaps) == 1
        assert offer.recovers > 0
        after = await assembled_reading_the_stored_concessions(sessions, owner.tenant_id)
        # The concession reached the assembly as a stored row rather than as an argument.
        assert [one.adjustment_id for one in after.adjustments] == [candidate.adjustment_id]
        left = minutes_of(probe(after.for_probe()), QUOTED_AGAINST)
        assert gaps[0].minutes - left >= offer.recovers

    @pytest.mark.parametrize("kind", list(AdjustmentKind))
    async def test_the_next_solve_of_that_week_honors_it_without_being_asked_again(
        self,
        kind: AdjustmentKind,
        sessions: async_sessionmaker[AsyncSession],
        owner: UserRecord,
    ) -> None:
        # The half of the rule storage answers: the assembly reads
        # the row, so every later solve of the week is scored under the concession with no second
        # approval anywhere. Which resolved fields each kind moves is the fold's own suite.
        _, before, offer = await an_offered(kind)
        candidate = offer.as_candidate(adjustment_id=uuid4())

        await approve_the_offer(sessions, owner.tenant_id, owner, candidate)

        after = await assembled_reading_the_stored_concessions(sessions, owner.tenant_id)
        assert _resolved(before) != _resolved(after)
        assert [one.kind for one in after.adjustments] == [kind]

    async def test_the_concession_does_not_carry_into_the_following_week(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """A decision taken for one hard week is not a policy.

        The row names its week, so the following week's assembly resolves the floor it was never
        conceded. Asserted over the figure rather than over the absence of a row, because what the
        user would feel is the floor.
        """
        _, before, offer = await an_offered(AdjustmentKind.BREACH_FLOOR)
        candidate = offer.as_candidate(adjustment_id=uuid4())

        await approve_the_offer(sessions, owner.tenant_id, owner, candidate)

        this_week = await assembled_reading_the_stored_concessions(sessions, owner.tenant_id)
        following = await assembled_reading_the_stored_concessions(
            sessions, owner.tenant_id, week=NEXT_WEEK
        )
        assert await concessions_held(sessions, owner.tenant_id, week=NEXT_WEEK) == []
        assert following.adjustments == ()
        assert _floors(following) == _floors(before)
        assert _floors(this_week) != _floors(before)


class TestApprovingTheSameTradeoffTwice:
    async def test_the_second_approval_replaces_the_first_rather_than_compounding_it(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The unique index is what enforces this, not the upsert having been written correctly.

        Two proposals of one kind and one target, approved one after the other. The week ends with
        one concession whose figure is the second one's, and the floor is lower by that figure
        rather than by the sum. The replaced row keeps its own identifier, which is the concession
        table's stated choice: every earlier document names it, and a fresh identifier would leave
        those documents naming a row nothing holds.

        **The history is asserted as a pairing rather than as a figure.** The second revision names
        an identifier nothing holds, and what it reports is that the concession was REPLACED: still
        in force, under the name the first revision uses. The first revision names the row and
        reports nothing missing. A count alone could not tell that state from a revocation.
        """
        _, before, offer = await an_offered(AdjustmentKind.BREACH_FLOOR)
        first = offer.as_candidate(adjustment_id=uuid4())
        second = offer.as_candidate(adjustment_id=uuid4())

        await approve_the_offer(sessions, owner.tenant_id, owner, first)
        await approve_the_offer(
            sessions,
            owner.tenant_id,
            owner,
            second,
            at=NOW + timedelta(minutes=5),
            # The second solve read the stored concession and folded its own candidate on top, so
            # its document names both. That is the shape the worker writes for this interleaving.
            solved_under=(first.adjustment_id, second.adjustment_id),
        )

        held = await concessions_held(sessions, owner.tenant_id)
        assert len(held) == 1
        assert held[0].id == first.adjustment_id
        assert held[0].delta_minutes == second.delta_minutes
        replacing, granting = (await the_history(sessions, owner.tenant_id, owner)).revisions
        assert [one.id for one in replacing.adjustments] == [first.adjustment_id]
        assert (replacing.unnamed.revoked, replacing.unnamed.replaced) == (0, 1)
        assert (granting.unnamed.revoked, granting.unnamed.replaced) == (0, 0)
        after = await assembled_reading_the_stored_concessions(sessions, owner.tenant_id)
        conceded = (
            _floors(before)[offer.tradeoff.target_id] - _floors(after)[offer.tradeoff.target_id]
        )
        assert conceded == offer.recovers
        assert conceded != offer.recovers * 2


def _floors(inputs: SolveInputs) -> dict[Any, int]:
    return {one.area_id: one.floor_minutes for one in inputs.areas}


def _resolved(inputs: SolveInputs) -> tuple[Any, ...]:
    """The four resolutions a concession of any kind moves, as one comparable value."""
    return (
        _floors(inputs),
        tuple((one.title, one.remaining_minutes, one.deadline) for one in inputs.eligible_tasks),
        tuple((one.labels, one.remaining_minutes) for one in inputs.deadline_demands),
        tuple(one.interval for one in inputs.frame),
    )
