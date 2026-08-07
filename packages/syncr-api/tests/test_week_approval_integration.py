"""The approval transaction against a real Postgres: what it writes, and what it refuses.

Every claim here is about rows, so none of it can be asserted against a fake. What one approval
writes is five things in one transaction, and four of them are separate tables.

Five groups.

**What an approval writes.** An ``approved`` revision carrying the slot's own document, the
concession the slot carried, the version bump, the cleared slot, and the enqueued projection.

**``PP3``, from its false side.** A failure at any step leaves the pending slot intact, so the
proposal is still approvable and nothing half-happened. Driven by making the last write raise.

**Two approvals racing one slot.** The ``DELETE`` is the claim, so exactly one of two concurrent
approvals appends a revision and the other is refused with the same conflict an already-replaced
slot answers. An ``Idempotency-Key`` cannot cover this: two clicks carrying two keys are two
requests.

**What approval refuses, which is ticket 1391's decision.** A document that would change the live
plan in a way its own diff never named, and a document that restates a part of the week that
elapsed after it was classified. Both leave the plan of record alone. The control beside them is a
proposal whose changes ARE the ones the diff named, which approves.

**``US-FEAS-05``: approval is never blocked by an infeasibility.** An infeasible week approves, and
the path reads no verdict at all, which is asserted against the module's own source: there is no
state a shortfall could put this route into.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from syncr_api.approvals.injection import build_approval_service
from syncr_api.approvals.service import ApprovalService
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.core.errors import Conflict
from syncr_api.core.principal import Principal
from syncr_api.core.scopes import Scope
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.candidates import as_document
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.stored_proposals import stored_proposal_diff
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import PROJECTION
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.models import Operation
from syncr_api.solving.repository import OperationRepository
from syncr_domain.identity import BindingRef
from syncr_domain.plan import AdjustmentKind, RevisionReason
from syncr_domain.proposals import BlockChange, ProposalDiff
from syncr_solver.inputs import WeekAdjustment
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import WEEK, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.approvals.service import ApprovedWeek
    from syncr_api.plans.records import PlanRevisionRecord, WeekAdjustmentRecord
    from syncr_domain.identifiers import TenantId
    from syncr_domain.plan import Block, PlanDocument

pytestmark = pytest.mark.integration

# Before the week begins, so nothing in it has been reached and every placement is still the
# product's to revise.
BEFORE_THE_WEEK = datetime(2026, 2, 8, tzinfo=UTC)
# Later the same day, which is when the approvals happen: a revision appended at the same instant as
# the one it supersedes leaves "the live plan" decided by a tie-break rather than by time.
AT_APPROVAL = datetime(2026, 2, 8, 12, 0, tzinfo=UTC)
# Mid-morning on the week's Monday, so a block at 09:00 has been reached and one at 17:00 has not.
MID_MORNING = datetime(2026, 2, 9, 10, 0, tzinfo=UTC)

GYM = BindingRef.for_habit(uuid4(), index=0)
LEETCODE = BindingRef.for_task(uuid4())

BREAKDOWN: dict[str, Any] = {"deadline_risk": 0.0, "budget_deviation": 12.5}
FEASIBLE: dict[str, Any] = {"feasible": True, "shortfall_minutes": 0, "provenance": "solver"}
# What the probe reports for a week that cannot hold its commitments. Approval never reads it.
INFEASIBLE: dict[str, Any] = {
    "feasible": False,
    "shortfall_minutes": 320,
    "provenance": "probe",
    "shortfalls": [{"kind": "floors_exceed_capacity", "minutes": 320}],
}

SLOT_VERSION = 41
WEIGHTS = 7
FITNESS = uuid4()


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


def a_week(*blocks: Block, **overrides: Any) -> PlanDocument:
    return a_document(week=WEEK, blocks=blocks, **overrides)


def a_moved(live: Block, candidate: Block) -> dict[str, Any]:
    """The stored diff of one proposal that moves one block, which is what the user was shown."""
    change = BlockChange.moved(live=live, candidate=candidate)
    return dict(stored_proposal_diff(ProposalDiff(moved=(change,))))


def a_breach(*, minutes: int = 80, adjustment_id: UUID | None = None) -> dict[str, object]:
    """A candidate concession riding in the slot, as the operation carries one."""
    return as_document(
        WeekAdjustment(
            adjustment_id=adjustment_id or uuid4(),
            kind=AdjustmentKind.BREACH_FLOOR,
            target_id=FITNESS,
            reductions={},
            delta_minutes=minutes,
        )
    )


async def seed_live_plan(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    document: PlanDocument,
    *,
    at: datetime = BEFORE_THE_WEEK,
) -> PlanRevisionRecord:
    async with sessions() as session, session.begin():
        return await PlanRepository(session, tenant_id).append(
            document=stored_document(document),
            objective_breakdown=BREAKDOWN,
            status="applied",
            reason="auto_applied_fill",
            weight_set_version=WEIGHTS,
            input_version=SLOT_VERSION,
            created_at=at,
        )


async def seed_slot(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    document: PlanDocument,
    *,
    diff: dict[str, Any] | None = None,
    verdict: dict[str, Any] | None = None,
    candidate: dict[str, object] | None = None,
    input_version: int = SLOT_VERSION,
) -> None:
    async with sessions() as session, session.begin():
        await PendingProposalRepository(session, tenant_id).replace(
            document=stored_document(document),
            proposal_diff=diff or {"added": [], "removed": [], "moved": []},
            objective_breakdown=BREAKDOWN,
            verdict=verdict or FEASIBLE,
            weight_set_version=WEIGHTS,
            input_version=input_version,
            operation_id=uuid4(),
            created_at=BEFORE_THE_WEEK,
            candidate_adjustment=candidate,
        )


async def approve(
    sessions: async_sessionmaker[AsyncSession],
    owner: UserRecord,
    *,
    at: datetime = AT_APPROVAL,
    week: str = str(WEEK),
) -> ApprovedWeek:
    async with sessions() as session, session.begin():
        service = build_approval_service(session, owner.tenant_id, clock=lambda: at)
        return await service.approve(principal_of(owner), week)


async def revisions_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> list[PlanRevision]:
    async with sessions() as session:
        found = await session.scalars(
            select(PlanRevision)
            .where(PlanRevision.tenant_id == tenant_id)
            .order_by(PlanRevision.created_at, PlanRevision.id)
        )
        return list(found)


async def slot_of(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> Any:
    async with sessions() as session:
        return await PendingProposalRepository(session, tenant_id).find(WEEK)


async def version_of(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> int | None:
    async with sessions() as session:
        return await WeekInputVersionRepository(session, tenant_id).current(WEEK)


async def concessions_of(
    sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId
) -> Sequence[WeekAdjustmentRecord]:
    async with sessions() as session:
        return await WeekAdjustmentRepository(session, tenant_id).for_week(WEEK)


async def projections_of(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> int:
    async with sessions() as session:
        held = await session.scalar(
            select(func.count())
            .select_from(Operation)
            .where(Operation.tenant_id == tenant_id, Operation.kind == PROJECTION)
        )
    return held or 0


class TestWhatOneApprovalWrites:
    async def test_the_approved_revision_carries_the_slots_own_document_and_its_provenance(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Read off the stored ROW rather than the returned value: what the plan of record holds is
        the whole question, and the columns that describe it are derived on the write."""
        live = a_week(a_block_holding(GYM, between(9, 10)))
        proposed = a_week(a_block_holding(GYM, between(17, 18)))
        previous = await seed_live_plan(sessions, owner.tenant_id, live)
        await seed_slot(
            sessions,
            owner.tenant_id,
            proposed,
            diff=a_moved(live.blocks[0], proposed.blocks[0]),
        )

        approved = await approve(sessions, owner)

        stored = await revisions_of(sessions, owner.tenant_id)
        assert [one.status for one in stored] == ["applied", "approved"]
        row = stored[-1]
        assert row.id == approved.revision.id
        assert row.reason == RevisionReason.USER_APPROVED.value
        assert row.approved_at == AT_APPROVAL
        assert row.iso_week == str(WEEK)
        assert [block["title"] for block in row.document["blocks"]] == ["habit · something"]
        assert row.document["blocks"][0]["interval"]["start"] == between(17, 18).start.isoformat()
        assert row.objective_breakdown == BREAKDOWN
        # The weights and the input version are the ones that PRODUCED the document, not the ones
        # in force at approval: PP5's "the revision records the version it was solved against".
        assert row.weight_set_version == WEIGHTS
        assert row.input_version == SLOT_VERSION
        assert row.supersedes_id == previous.id

    async def test_approving_clears_the_slot_so_the_same_proposal_cannot_be_approved_again(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        await seed_slot(sessions, owner.tenant_id, a_week())

        await approve(sessions, owner)

        assert await slot_of(sessions, owner.tenant_id) is None
        with pytest.raises(Conflict, match="has been replaced"):
            await approve(sessions, owner)
        assert len(await revisions_of(sessions, owner.tenant_id)) == 1

    async def test_approval_bumps_the_input_version(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Decision 31, ``V3``, ``PP6`` and a trigger-table row, and no story's criteria stated it.

        The bump is what a solve running concurrently reads: without it that solve's conditional
        write matches on a version the approval did not change. The race itself is driven in
        ``test_approval_during_a_solve.py``; this is the write.
        """
        await seed_slot(sessions, owner.tenant_id, a_week())
        async with sessions() as session, session.begin():
            await WeekInputVersionRepository(session, owner.tenant_id).bump(
                WEEK, at=BEFORE_THE_WEEK
            )
        held = await version_of(sessions, owner.tenant_id)

        approved = await approve(sessions, owner)

        assert held == 1
        assert await version_of(sessions, owner.tenant_id) == 2
        assert approved.input_version == 2
        # What the response says the plan was solved against is the slot's own version, which is
        # what makes a discrepancy visible rather than hidden.
        assert approved.revision.input_version == SLOT_VERSION

    async def test_approving_a_week_nothing_has_referenced_creates_its_version_row(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The bump is an upsert, so a week whose row does not exist yet gets one at 1 rather than
        # the approval failing on a missing row.
        await seed_slot(sessions, owner.tenant_id, a_week())

        approved = await approve(sessions, owner)

        assert approved.input_version == 1
        assert await version_of(sessions, owner.tenant_id) == 1

    async def test_approving_enqueues_exactly_one_projection_for_the_week(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        await seed_slot(sessions, owner.tenant_id, a_week())

        approved = await approve(sessions, owner)

        assert await projections_of(sessions, owner.tenant_id) == 1
        assert approved.projection.kind == PROJECTION
        assert approved.projection.iso_week == WEEK

    async def test_a_tradeoff_approval_persists_the_concession_and_records_which_act_it_was(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """``US-FEAS-07``'s first criterion: the concession and the revision are one transaction.

        The reason is decided by what the slot carries rather than by the caller, so a tradeoff
        approval cannot be recorded as an ordinary one.
        """
        await seed_slot(sessions, owner.tenant_id, a_week(), candidate=a_breach(minutes=80))

        approved = await approve(sessions, owner)

        assert approved.revision.reason == RevisionReason.TRADEOFF_APPROVED.value
        held = await concessions_of(sessions, owner.tenant_id)
        assert len(held) == 1
        assert held[0].kind == AdjustmentKind.BREACH_FLOOR.value
        assert held[0].target_id == FITNESS
        assert held[0].delta_minutes == 80
        assert held[0].iso_week == WEEK
        assert approved.adjustment is not None
        assert approved.adjustment.id == held[0].id

    async def test_an_ordinary_approval_persists_no_concession(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The false side of the same branch: a slot carrying no candidate leaves the concession
        # table empty, so a week never absorbs a concession nobody offered.
        await seed_slot(sessions, owner.tenant_id, a_week())

        approved = await approve(sessions, owner)

        assert approved.adjustment is None
        assert await concessions_of(sessions, owner.tenant_id) == []

    async def test_the_stored_concession_takes_the_identifier_the_approved_document_names(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The pairing the verdict panel and the history both read, asserted on the two rows.

        A solved document records the concessions it was solved under by identifier, and for a
        candidate that identifier is the one the request minted and the worker folded. A row created
        with a fresh one would leave the approved revision naming a concession the week does not
        hold, and the history would report the plan as solved under nothing.
        """
        conceded = uuid4()
        await seed_slot(
            sessions,
            owner.tenant_id,
            a_week(adjustments=(conceded,)),
            candidate=a_breach(adjustment_id=conceded),
        )

        approved = await approve(sessions, owner)

        held = await concessions_of(sessions, owner.tenant_id)
        assert [one.id for one in held] == [conceded]
        assert approved.revision.document["adjustments"] == [str(conceded)]


class TestApprovalIsOneTransaction:
    async def test_a_failure_at_the_last_step_leaves_the_pending_slot_intact(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """``PP3``. The projection is enqueued last, so a raise there is the whole transaction's.

        Nothing may be left behind: no revision, no concession, no bump, and above all a slot the
        user can still approve. A partial approval would leave a proposal whose document is already
        the plan of record.
        """
        await seed_slot(sessions, owner.tenant_id, a_week(), candidate=a_breach())

        with pytest.raises(RuntimeError, match="the projection queue is unavailable"):
            async with sessions() as session, session.begin():
                await _service_whose_projection_fails(session, owner.tenant_id).approve(
                    principal_of(owner), str(WEEK)
                )

        assert await slot_of(sessions, owner.tenant_id) is not None
        assert await revisions_of(sessions, owner.tenant_id) == []
        assert await concessions_of(sessions, owner.tenant_id) == []
        assert await version_of(sessions, owner.tenant_id) is None
        assert await projections_of(sessions, owner.tenant_id) == 0

    async def test_two_approvals_of_one_slot_append_one_revision(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Two clicks, two transactions, two different keys, and one slot, on a VIRGIN week.

        This week has no version row, so the lock above has nothing to take and the ``DELETE``'s own
        answer is the whole mechanism: whichever transaction deletes the row owns the approval, and
        the other blocks on it and then finds nothing to delete. Run concurrently rather than in
        sequence, because what is asserted is the lock rather than the read.

        The state production actually reaches is the test below, where the week has a version row
        and the loser is refused before it gets this far. Both are driven, because the service says
        which mechanism holds in which state and an unexercised half of that claim is a claim.
        """
        await seed_slot(sessions, owner.tenant_id, a_week())
        # The state this test is about, asserted rather than assumed: with no row there is nothing
        # for the lock to take, so the DELETE's answer is the whole mechanism.
        assert await version_of(sessions, owner.tenant_id) is None

        answers = await asyncio.gather(
            approve(sessions, owner), approve(sessions, owner), return_exceptions=True
        )

        refused = [one for one in answers if isinstance(one, Conflict)]
        assert len(refused) == 1, answers
        assert "has been replaced" in refused[0].detail
        assert len(await revisions_of(sessions, owner.tenant_id)) == 1
        assert await projections_of(sessions, owner.tenant_id) == 1

    async def test_two_approvals_of_a_week_that_holds_a_version_row_append_one_revision(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The same race in the state production reaches, where the LOCK is what resolves it.

        A week that holds a pending proposal always holds a live revision and therefore a version
        row: the slot has one writer, that writer cannot fill a slot on a week with no live plan
        (everything classifies as a fill there, so the proposal diff is empty), and a revision is
        never deleted. So this is the interleaving a user can produce, and the loser never reaches
        the DELETE: it waits on the version row and then reads a slot that is already gone.
        """
        live = a_week(a_block_holding(GYM, between(9, 10)))
        await seed_live_plan(sessions, owner.tenant_id, live)
        await seed_slot(sessions, owner.tenant_id, live)
        async with sessions() as session, session.begin():
            await WeekInputVersionRepository(session, owner.tenant_id).bump(
                WEEK, at=BEFORE_THE_WEEK
            )

        answers = await asyncio.gather(
            approve(sessions, owner), approve(sessions, owner), return_exceptions=True
        )

        refused = [one for one in answers if isinstance(one, Conflict)]
        assert len(refused) == 1, answers
        assert "has been replaced" in refused[0].detail
        stored = await revisions_of(sessions, owner.tenant_id)
        assert [one.status for one in stored] == ["applied", "approved"]
        assert await projections_of(sessions, owner.tenant_id) == 1
        # One bump, from the one approval that ran: the loser wrote nothing at all.
        assert await version_of(sessions, owner.tenant_id) == 2

    async def test_approving_a_week_whose_slot_is_empty_says_what_still_works(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        with pytest.raises(Conflict, match="reading the week again"):
            await approve(sessions, owner)

        assert await revisions_of(sessions, owner.tenant_id) == []


class TestWhatApprovalRefuses:
    async def test_a_proposal_the_live_plan_has_moved_past_is_refused_rather_than_dropping_the_fill(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """Ticket 1391's own sequence, and the answer this transaction takes.

        A task captured into a free gap auto-applies, so the live plan advances while the slot still
        holds a proposal computed before that block existed. Approving the slot would drop the block
        with nothing scheduled to put it back. The authority rule says syncr may never remove
        without assent, and the diff the user was shown does not mention it, so the approval is
        refused and the plan of record keeps the block.
        """
        live = a_week(a_block_holding(GYM, between(9, 10)))
        proposed = a_week(a_block_holding(GYM, between(17, 18)))
        await seed_live_plan(sessions, owner.tenant_id, live)
        await seed_slot(
            sessions, owner.tenant_id, proposed, diff=a_moved(live.blocks[0], proposed.blocks[0])
        )
        filled = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )
        await seed_live_plan(sessions, owner.tenant_id, filled, at=MID_MORNING)

        with pytest.raises(Conflict, match="without asking"):
            await approve(sessions, owner)

        stored = await revisions_of(sessions, owner.tenant_id)
        assert [one.status for one in stored] == ["applied", "applied"]
        assert len(stored[-1].document["blocks"]) == 2
        assert await slot_of(sessions, owner.tenant_id) is not None

    async def test_the_refusal_names_the_block_the_proposal_never_mentioned(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # A refusal a user reads has to say which block it is about, or "something changed" is the
        # whole message. The title comes from the live plan's own block.
        live = a_week(a_block_holding(GYM, between(9, 10)))
        await seed_live_plan(sessions, owner.tenant_id, live)
        await seed_slot(sessions, owner.tenant_id, a_week())

        with pytest.raises(Conflict, match="habit · something changed"):
            await approve(sessions, owner)

    async def test_a_proposal_whose_only_changes_are_the_ones_it_showed_is_approved(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The control for the two refusals above. Without it both could be passing because every
        # approval is refused.
        live = a_week(a_block_holding(GYM, between(9, 10)))
        proposed = a_week(a_block_holding(GYM, between(17, 18)))
        await seed_live_plan(sessions, owner.tenant_id, live)
        await seed_slot(
            sessions, owner.tenant_id, proposed, diff=a_moved(live.blocks[0], proposed.blocks[0])
        )

        approved = await approve(sessions, owner)

        assert approved.revision.status == "approved"

    async def test_a_proposal_that_showed_a_move_may_not_drop_the_block_instead(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """What was shown has to name the block AND leave it where the document does.

        A diff saying "this moves to Thursday evening" is not assent to the block going away, so the
        exemption pairs on the block and the placement the change leaves it at rather than on the
        block alone. Unreachable through the shipped writer, because the adoption refuses a diff
        whose changes do not pair with the document it is stored under; asserted anyway, because
        this guard's whole job is to trust no earlier comparison.
        """
        live = a_week(a_block_holding(GYM, between(9, 10)))
        elsewhere = a_block_holding(GYM, between(17, 18))
        await seed_live_plan(sessions, owner.tenant_id, live)
        await seed_slot(
            sessions,
            owner.tenant_id,
            a_week(),
            diff=a_moved(live.blocks[0], elsewhere),
        )

        with pytest.raises(Conflict, match="without asking"):
            await approve(sessions, owner)

        assert [one.status for one in await revisions_of(sessions, owner.tenant_id)] == ["applied"]

    async def test_a_proposal_that_restates_a_block_the_week_has_since_reached_is_refused(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """The second gap review 39 found: the classification compared the past AS IT STOOD THEN.

        The proposal moves a 09:00 block to 17:00 and was classified before 09:00, when moving it
        was a change the product could still make. By 10:00 the block has run, so the document
        being written states a past the week did not live, and approval compares again against its
        own instant rather than trusting a comparison made an hour earlier.
        """
        live = a_week(a_block_holding(GYM, between(9, 10)))
        proposed = a_week(a_block_holding(GYM, between(17, 18)))
        await seed_live_plan(sessions, owner.tenant_id, live)
        await seed_slot(
            sessions, owner.tenant_id, proposed, diff=a_moved(live.blocks[0], proposed.blocks[0])
        )

        with pytest.raises(Conflict, match="has been lived"):
            await approve(sessions, owner, at=MID_MORNING)

        stored = await revisions_of(sessions, owner.tenant_id)
        assert [one.status for one in stored] == ["applied"]
        assert (
            stored[0].document["blocks"][0]["interval"]["start"] == between(9, 10).start.isoformat()
        )
        assert await slot_of(sessions, owner.tenant_id) is not None


class TestApprovalIsNeverBlockedByAnInfeasibility:
    async def test_an_infeasible_week_approves(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        """``US-FEAS-05``: syncr informs, it does not govern.

        The slot's verdict says the week cannot hold its commitments and names a gap. Approval
        appends the revision anyway: infeasibility is a notice at panel volume, and there is no
        blocking state anywhere for it to reach.
        """
        await seed_slot(sessions, owner.tenant_id, a_week(), verdict=INFEASIBLE)

        approved = await approve(sessions, owner)

        assert approved.revision.status == "approved"
        assert len(await revisions_of(sessions, owner.tenant_id)) == 1

    async def test_the_approval_path_reads_no_verdict_at_all(self, source_root: Path) -> None:
        # The structural half, and the one that cannot rot: a path that never reads a verdict has
        # no branch a shortfall could take. Asserted on the source, because what has to hold is
        # that the read is ABSENT rather than that one week approved.
        source = (source_root / "approvals" / "service.py").read_text(encoding="utf-8")

        # Every mention of a verdict in this module is prose in a docstring, and what has to be
        # absent is a READ, so the docstrings and comments are removed before the words are looked
        # for. Without that the rule would be asserting something about how the module is written.
        statements = _statements_of(source)

        for reading in ("verdict", "feasible", "shortfall", "probe"):
            assert reading not in statements, reading


def _statements_of(source: str) -> str:
    """The module with every docstring and comment gone, which is what it DOES."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body.pop(0)
    # `unparse` renders the tree rather than the text, so comments are gone with the docstrings.
    return ast.unparse(tree)


class _ProjectionQueueThatFails(OperationLifecycle):
    """The last write of the transaction, raising, so the four before it have to roll back."""

    async def enqueue(self, **_: Any) -> Any:
        message = "the projection queue is unavailable"
        raise RuntimeError(message)


def _service_whose_projection_fails(session: AsyncSession, tenant_id: TenantId) -> ApprovalService:
    return ApprovalService(
        revisions=PlanRepository(session, tenant_id),
        proposals=PendingProposalRepository(session, tenant_id),
        adjustments=WeekAdjustmentRepository(session, tenant_id),
        versions=WeekInputVersionRepository(session, tenant_id),
        operations=_ProjectionQueueThatFails(
            OperationRepository(session, tenant_id), lambda: BEFORE_THE_WEEK
        ),
        clock=lambda: BEFORE_THE_WEEK,
    )
