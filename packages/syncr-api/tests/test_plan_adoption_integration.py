"""What a classification writes, against a real Postgres: a revision, a slot, or nothing.

The authority rule is asserted from literals one module over. This asserts the consequence, and it
needs a real database because every claim is about rows: how many revisions a week holds, whether a
slot was replaced in place, and whether anything at all was written.

Four groups.

**The three outcomes.** A fill-only candidate appends one ``applied`` revision and replaces no
slot; anything that moves or drops appends nothing and replaces the slot; a candidate that changes
nothing writes neither.

**A candidate that fills and moves is held whole**, which is what makes the weekly session's own
arithmetic come out: twelve pins append zero revisions and therefore enqueue no projection.

**The conflicts are raised as part of the same adoption**, and only the ones that are news.

**What the write refuses**, so a caller cannot append a revision claiming the user assented, or
store a diff under a week whose blocks its changes cannot be paired against.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from syncr_api.anchors.commitments import AnchorCommitments
from syncr_api.core.db import create_db_engine, create_sessionmaker
from syncr_api.plans.adoption import AUTO_APPLIED_REASONS, Candidate, PlanAdoption
from syncr_api.plans.authority import Classification, classify
from syncr_api.plans.conflicts import PlanConflictRepository
from syncr_api.plans.errors import ClassificationRejected, RevisionRejected
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.overlaps import DetectedConflict
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_proposals import ADDED, MOVED, REMOVED
from syncr_domain.identity import BindingRef
from syncr_domain.plan import RevisionReason
from syncr_domain.proposals import BlockChange, ProposalDiff
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import delete_tenant, seed_owner
from tests.plan_documents import WEEK, a_block_holding, a_document, between

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from syncr_api.accounts.records import UserRecord
    from syncr_api.plans.adoption import Adopted
    from syncr_api.plans.config import RevisionReason as StoredReason
    from syncr_domain.identifiers import TenantId
    from syncr_domain.plan import Block, PlanDocument

pytestmark = pytest.mark.integration

BEFORE_THE_WEEK = datetime(2026, 2, 8, tzinfo=UTC)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
# Mid-morning on the week's Monday, so a block at 08:00 has been reached and one at 14:00 has not.
MID_MORNING = datetime(2026, 2, 9, 10, 0, tzinfo=UTC)

GYM = BindingRef.for_habit(uuid4(), index=0)
LEETCODE = BindingRef.for_task(uuid4())
STANDUP = BindingRef.for_anchor(uuid4())

BREAKDOWN = {"deadline_risk": 0.0, "budget_deviation": 12.5}
A_VERDICT: dict[str, Any] = {"feasible": True, "shortfall_minutes": 0, "provenance": "solver"}
WEIGHT_SET_VERSION = 1

A_FILL: StoredReason = "auto_applied_fill"

# Every reason a revision may carry that this write may NOT append under, derived from the one
# vocabulary rather than listed a second time beside the pair the module allows.
NOT_AN_AUTO_APPLICATION = {reason.value for reason in RevisionReason} - AUTO_APPLIED_REASONS


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


def a_week(*blocks: Block, week: IsoWeek = WEEK) -> PlanDocument:
    return a_document(week=week, blocks=blocks)


def a_candidate(document: PlanDocument, **overrides: Any) -> Candidate:
    fields: dict[str, Any] = {
        "document": document,
        "objective_breakdown": BREAKDOWN,
        "verdict": A_VERDICT,
        "weight_set_version": WEIGHT_SET_VERSION,
        "input_version": 41,
        "operation_id": uuid4(),
    }
    return Candidate(**(fields | overrides))


def classified(live: PlanDocument | None, candidate: PlanDocument) -> Classification:
    return classify(live, candidate, now=BEFORE_THE_WEEK)


async def adopt(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: TenantId,
    classification: Classification,
    plan: Candidate,
    *,
    reason: StoredReason = A_FILL,
    at: datetime = NOW,
) -> Adopted:
    async with sessions() as session, session.begin():
        adoption = PlanAdoption(
            revisions=PlanRepository(session, tenant_id),
            pending=PendingProposalRepository(session, tenant_id),
            conflicts=PlanConflictRepository(session, tenant_id),
            # The production implementation, not a fake: it is what `solving.dispatch` wires, and
            # this suite plants no anchor rows, so a conflict it raises records no commitment --
            # which is exactly the state an anchor deleted before the commit leaves.
            commitments=AnchorCommitments(session, tenant_id),
        )
        return await adoption.adopt(classification, plan, reason=reason, at=at)


async def revisions_held(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> int:
    async with sessions() as session:
        held = await session.scalar(
            select(func.count())
            .select_from(PlanRevision)
            .where(PlanRevision.tenant_id == tenant_id)
        )
    return held or 0


async def proposal_held(sessions: async_sessionmaker[AsyncSession], tenant_id: TenantId) -> Any:
    async with sessions() as session:
        return await PendingProposalRepository(session, tenant_id).find(WEEK)


class TestWhatEachClassificationWrites:
    async def test_a_fill_only_candidate_appends_one_applied_revision(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )

        adopted = await adopt(
            sessions, owner.tenant_id, classified(live, candidate), a_candidate(candidate)
        )

        assert adopted.revision is not None
        assert adopted.revision.status == "applied"
        assert adopted.revision.reason == A_FILL
        assert adopted.revision.input_version == 41
        assert adopted.revision.approved_at is None
        assert adopted.changed_the_live_plan()
        assert await revisions_held(sessions, owner.tenant_id) == 1
        assert await proposal_held(sessions, owner.tenant_id) is None

    async def test_the_appended_revision_carries_the_whole_candidate_document(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )

        adopted = await adopt(
            sessions, owner.tenant_id, classified(live, candidate), a_candidate(candidate)
        )

        assert adopted.revision is not None
        assert len(adopted.revision.document["blocks"]) == 2
        assert adopted.revision.objective_breakdown == BREAKDOWN

    async def test_a_candidate_that_moves_a_block_replaces_the_slot_and_appends_nothing(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(a_block_holding(GYM, between(17, 18)))

        adopted = await adopt(
            sessions, owner.tenant_id, classified(live, candidate), a_candidate(candidate)
        )

        assert adopted.revision is None
        assert not adopted.changed_the_live_plan()
        assert await revisions_held(sessions, owner.tenant_id) == 0
        assert adopted.proposal is not None
        assert len(adopted.proposal.proposal_diff[MOVED]) == 1
        assert adopted.proposal.proposal_diff[ADDED] == []
        assert adopted.proposal.verdict == A_VERDICT

    async def test_the_slot_records_the_weights_that_produced_the_document_in_it(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # Approval appends a revision FROM this row, and a revision states which weights produced
        # its document. Read off the same load the document came from, so the two cannot name
        # different sets, and not the set in force at approval, which the user may have changed
        # since. Asserted on the stored ROW rather than on the value passed in.
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(a_block_holding(GYM, between(17, 18)))

        await adopt(
            sessions,
            owner.tenant_id,
            classified(live, candidate),
            a_candidate(candidate, weight_set_version=9),
        )

        stored = await proposal_held(sessions, owner.tenant_id)
        assert stored is not None
        assert stored.weight_set_version == 9

    async def test_a_second_proposal_replaces_the_first_in_place(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        first = a_week(a_block_holding(GYM, between(17, 18)))
        second = a_week()

        await adopt(sessions, owner.tenant_id, classified(live, first), a_candidate(first))
        await adopt(sessions, owner.tenant_id, classified(live, second), a_candidate(second))

        held = await proposal_held(sessions, owner.tenant_id)
        assert held is not None
        assert len(held.proposal_diff[REMOVED]) == 1
        assert held.proposal_diff[MOVED] == []

    async def test_a_candidate_that_changes_nothing_writes_nothing_at_all(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))

        adopted = await adopt(sessions, owner.tenant_id, classified(live, live), a_candidate(live))

        assert (adopted.revision, adopted.proposal, adopted.raised) == (None, None, ())
        assert not adopted.changed_the_live_plan()
        assert await revisions_held(sessions, owner.tenant_id) == 0
        assert await proposal_held(sessions, owner.tenant_id) is None

    async def test_a_week_with_no_live_plan_is_filled_and_appended(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        candidate = a_week(a_block_holding(GYM, between(9, 10)))

        adopted = await adopt(
            sessions, owner.tenant_id, classified(None, candidate), a_candidate(candidate)
        )

        assert adopted.revision is not None
        assert await revisions_held(sessions, owner.tenant_id) == 1

    async def test_an_anchor_delta_that_only_freed_space_appends_under_its_own_reason(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week()
        candidate = a_week(a_block_holding(LEETCODE, between(14, 15)))

        adopted = await adopt(
            sessions,
            owner.tenant_id,
            classified(live, candidate),
            a_candidate(candidate),
            reason="anchor_delta",
        )

        assert adopted.revision is not None
        assert adopted.revision.reason == "anchor_delta"


class TestAutoApplicationIsAllOrNothing:
    async def test_a_candidate_that_fills_and_moves_appends_nothing_and_waits_whole(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(17, 18)), a_block_holding(LEETCODE, between(14, 15))
        )
        classification = classified(live, candidate)

        adopted = await adopt(sessions, owner.tenant_id, classification, a_candidate(candidate))

        assert len(classification.auto_applicable) == 1
        assert adopted.revision is None
        assert await revisions_held(sessions, owner.tenant_id) == 0
        assert adopted.proposal is not None
        assert len(adopted.proposal.document["blocks"]) == 2

    async def test_twelve_pins_append_zero_live_revisions(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The weekly session's own arithmetic: the user pins, every diff therefore holds a move,
        # so nothing auto-applies, so no revision is appended and no projection is enqueued.
        held = [
            a_block_holding(BindingRef.for_habit(uuid4(), index=index), between(index, index + 0.5))
            for index in range(12)
        ]
        live = a_week(*held)
        dragged = list(held)

        for index in range(12):
            dragged[index] = replace(dragged[index], interval=between(index + 12, index + 12.5))
            candidate = a_week(*dragged)

            adopted = await adopt(
                sessions, owner.tenant_id, classified(live, candidate), a_candidate(candidate)
            )

            assert adopted.revision is None, index
            assert not adopted.changed_the_live_plan(), index

        assert await revisions_held(sessions, owner.tenant_id) == 0
        held_proposal = await proposal_held(sessions, owner.tenant_id)
        assert held_proposal is not None
        assert len(held_proposal.proposal_diff[MOVED]) == 12


class TestTheConflictsAreRaisedWithIt:
    async def test_a_commitment_over_a_planned_block_is_raised_by_the_adoption(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(STANDUP, between(9.5, 10.5))
        )

        adopted = await adopt(
            sessions, owner.tenant_id, classified(live, candidate), a_candidate(candidate)
        )

        assert [conflict.anchor_id for conflict in adopted.raised] == [STANDUP.entity_id]
        assert adopted.raised[0].binding == GYM

    async def test_the_same_collision_on_a_second_solve_is_not_raised_again(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(STANDUP, between(9.5, 10.5))
        )
        await adopt(sessions, owner.tenant_id, classified(live, candidate), a_candidate(candidate))

        again = await adopt(
            sessions, owner.tenant_id, classified(live, candidate), a_candidate(candidate)
        )

        assert again.raised == ()
        async with sessions() as session:
            assert len(await PlanConflictRepository(session, owner.tenant_id).list_all()) == 1


class TestWhatTheWriteRefuses:
    @pytest.mark.parametrize("reason", sorted(NOT_AN_AUTO_APPLICATION))
    async def test_a_reason_that_is_not_an_auto_application_is_refused(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord, reason: str
    ) -> None:
        # The complement is DERIVED from the vocabulary rather than listed here, so a seventh
        # reason arrives as a case this test drives instead of as one nobody wrote down.
        live = a_week()
        candidate = a_week(a_block_holding(LEETCODE, between(14, 15)))

        with pytest.raises(RevisionRejected, match="the other reasons name an approval"):
            await adopt(
                sessions,
                owner.tenant_id,
                classified(live, candidate),
                a_candidate(candidate),
                reason=reason,  # type: ignore[arg-type]
            )

        assert await revisions_held(sessions, owner.tenant_id) == 0

    def test_the_complement_names_the_four_reasons_that_are_not_an_adoption(self) -> None:
        # The floor beside the derivation: an empty complement would make the parametrize above
        # drive nothing while reading as a passing test.
        assert {
            "user_approved",
            "tradeoff_approved",
            "materialized",
            "horizon_advanced",
        } == NOT_AN_AUTO_APPLICATION

    async def test_a_classification_wanting_a_block_the_candidate_does_not_hold_is_refused(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The pairing check the write can perform alone: a classification of one candidate written
        # over another's document would store a diff nothing in the plan matches.
        arriving = a_block_holding(LEETCODE, between(14, 15))
        classification = Classification(auto_applicable=(BlockChange.added(arriving),))

        with pytest.raises(RevisionRejected, match="does not hold it there"):
            await adopt(sessions, owner.tenant_id, classification, a_candidate(a_week()))

        assert await revisions_held(sessions, owner.tenant_id) == 0

    async def test_a_classification_wanting_a_block_at_another_placement_is_refused(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        arriving = a_block_holding(LEETCODE, between(14, 15))
        classification = Classification(
            proposal_diff=ProposalDiff(
                moved=(
                    BlockChange.moved(
                        live=replace(arriving, interval=between(9, 10)), candidate=arriving
                    ),
                ),
            )
        )
        elsewhere = a_week(replace(arriving, interval=between(17, 18)))

        with pytest.raises(RevisionRejected, match="does not hold it there"):
            await adopt(sessions, owner.tenant_id, classification, a_candidate(elsewhere))

        assert await proposal_held(sessions, owner.tenant_id) is None

    async def test_a_classification_dropping_a_block_the_candidate_still_holds_is_refused(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        kept = a_block_holding(GYM, between(9, 10))
        classification = Classification(
            proposal_diff=ProposalDiff(removed=(BlockChange.removed(kept),))
        )

        with pytest.raises(RevisionRejected, match="still holds it"):
            await adopt(sessions, owner.tenant_id, classification, a_candidate(a_week(kept)))

    async def test_a_classification_of_another_week_is_refused(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        elsewhere = IsoWeek(2026, 9)
        moved = a_block_holding(GYM, between(9, 10, week=elsewhere), week=elsewhere)
        classification = Classification(
            proposal_diff=ProposalDiff(removed=(BlockChange.removed(moved),))
        )

        with pytest.raises(RevisionRejected, match="2026-W09 was paired with a candidate"):
            await adopt(sessions, owner.tenant_id, classification, a_candidate(a_week()))

        assert await proposal_held(sessions, owner.tenant_id) is None

    async def test_a_conflict_of_another_week_is_refused_too(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        classification = Classification(
            conflicts=(
                DetectedConflict(
                    anchor_id=uuid4(),
                    iso_week=IsoWeek(2026, 9),
                    binding=GYM,
                    overlap=between(9, 10),
                ),
            )
        )

        with pytest.raises(RevisionRejected, match="2026-W09"):
            await adopt(sessions, owner.tenant_id, classification, a_candidate(a_week()))

        async with sessions() as session:
            assert await PlanConflictRepository(session, owner.tenant_id).list_all() == ()


class TestThePastMayNotBeRewrittenByAWrite:
    """The write's own side of the past rule, asserted by counting rows.

    The classifier refuses the pair, so no `Classification` describing a rewritten past can be
    built by the one function that builds them. These two assert the consequence at the table: the
    revision that would have carried the rewritten document is never appended.
    """

    async def test_a_fill_beside_a_dropped_started_block_appends_nothing(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        started = a_block_holding(GYM, between(8, 9))
        live = a_week(started)
        candidate = a_week(a_block_holding(LEETCODE, between(14, 15)))

        with pytest.raises(ClassificationRejected, match="dropped"):
            await adopt(
                sessions,
                owner.tenant_id,
                classify(live, candidate, now=MID_MORNING),
                a_candidate(candidate),
            )

        assert await revisions_held(sessions, owner.tenant_id) == 0
        assert await proposal_held(sessions, owner.tenant_id) is None

    async def test_a_fill_beside_a_moved_started_block_appends_nothing(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        started = a_block_holding(GYM, between(8, 9))
        live = a_week(started)
        candidate = a_week(
            replace(started, interval=between(6, 7)), a_block_holding(LEETCODE, between(14, 15))
        )

        with pytest.raises(ClassificationRejected, match="moved"):
            await adopt(
                sessions,
                owner.tenant_id,
                classify(live, candidate, now=MID_MORNING),
                a_candidate(candidate),
            )

        assert await revisions_held(sessions, owner.tenant_id) == 0

    async def test_a_candidate_that_keeps_the_past_appends_its_fill(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The positive control: the same shape with the started block left where the week had it.
        started = a_block_holding(GYM, between(8, 9))
        live = a_week(started)
        candidate = a_week(started, a_block_holding(LEETCODE, between(14, 15)))

        adopted = await adopt(
            sessions,
            owner.tenant_id,
            classify(live, candidate, now=MID_MORNING),
            a_candidate(candidate),
        )

        assert adopted.revision is not None
        assert len(adopted.revision.document["blocks"]) == 2
        assert await revisions_held(sessions, owner.tenant_id) == 1


class TestTheSlotIsNotClearedWhenTheLivePlanAdvances:
    async def test_a_pending_proposal_survives_a_later_fill(
        self, sessions: async_sessionmaker[AsyncSession], owner: UserRecord
    ) -> None:
        # The user approves what they can see, and the approved revision records the input version
        # it was solved against, so a stale slot is visible rather than silently discarded.
        live = a_week(a_block_holding(GYM, between(9, 10)))
        wanted = a_week(a_block_holding(GYM, between(17, 18)))
        await adopt(sessions, owner.tenant_id, classified(live, wanted), a_candidate(wanted))

        filled = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )
        adopted = await adopt(
            sessions, owner.tenant_id, classified(live, filled), a_candidate(filled)
        )

        assert adopted.revision is not None
        held = await proposal_held(sessions, owner.tenant_id)
        assert held is not None
        assert len(held.proposal_diff[MOVED]) == 1
