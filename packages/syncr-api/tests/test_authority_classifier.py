"""The authority rule: what auto-applies, what waits, what collides, and what is not classified.

Every test here builds two literal documents and calls the classifier. There is no database, no
repository and no fake, which is the property that makes the rule cheap to assert exhaustively:
blocks pair on the derived ``BlockId``, so "the same content" needs no lookup.

Five groups.

**The four diff classes**, each from a pair of documents that differ in exactly one way. A fill
lands in space no live block covered; an addition that displaces something is a proposal; a live
block the candidate drops is a removal; one block at two placements is a move.

**Auto-application is all or nothing.** A candidate holding a fill and a move is held whole, which
is what makes a weekly session of twelve pins append zero revisions and enqueue no projection.

**The past is not classified**, in every class and from both sides of a pair.

**The two conflict classes**, including the third overlap class nothing else in the model catches:
a derived buffer landing on a pinned block, attributed to the commitment that cast it.

**What the classification refuses to be**, so a producer cannot compose one that says a move only
filled empty space.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.plans.authority import Classification, classify
from syncr_api.plans.errors import ClassificationRejected
from syncr_api.plans.overlaps import DetectedConflict, detected_conflicts
from syncr_domain.identity import BindingKind, BindingRef, Origin, TransitLeg
from syncr_domain.proposals import BlockChange, ProposalDiff
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import Anchor, ShadowBlock
from tests.plan_documents import (
    CAREER,
    FITNESS,
    INTERVIEW,
    a_block,
    a_document,
    a_slot,
    a_window,
    at,
    between,
)

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval
    from syncr_domain.plan import Block, PlanDocument

# Before every placement the builders produce, so a classification sees a whole future week
# unless a test says otherwise.
BEFORE_THE_WEEK = datetime(2026, 2, 8, tzinfo=UTC)

GYM = BindingRef.for_habit(uuid4(), index=0)
LEETCODE = BindingRef.for_task(uuid4())
STANDUP = BindingRef.for_anchor(INTERVIEW)
PREP = BindingRef.for_anchor_prep(INTERVIEW)
TRANSIT = BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.OUT)


def a_week(*blocks: Block) -> PlanDocument:
    """A document holding exactly these blocks, with the figures a week needs."""
    return a_document(blocks=blocks)


def block(binding: BindingRef, interval: Interval, **overrides: object) -> Block:
    """One block of the content ``binding`` names, at ``interval``."""
    origins = {
        BindingKind.HABIT: Origin.HABIT,
        BindingKind.TASK: Origin.TASK,
        BindingKind.ANCHOR: Origin.ANCHOR,
        BindingKind.ANCHOR_PREP: Origin.PREP,
        BindingKind.ANCHOR_TRANSIT: Origin.TRANSIT,
    }
    return a_block(origins[binding.kind], binding=binding, interval=interval, **overrides)


def pinned(one: Block) -> Block:
    """``one`` as the user's own edit, which is what makes it immovable to the solver."""
    return replace(one, pinned=True, superseded_placement=between(20, 21), objective_delta=1.5)


def classified(live: PlanDocument | None, candidate: PlanDocument) -> Classification:
    return classify(live, candidate, now=BEFORE_THE_WEEK)


class TestWhatAutoApplies:
    def test_a_block_landing_where_no_live_block_was_fills_empty_space(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(9, 10)), block(LEETCODE, between(14, 15)))

        classification = classified(live, candidate)

        assert [change.block_id for change in classification.auto_applicable] == [
            block(LEETCODE, between(14, 15)).id
        ]
        assert classification.proposal_diff.is_empty()
        assert classification.applies_immediately()

    def test_a_fill_states_where_it_lands_and_replaces_nothing(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(9, 10)), block(LEETCODE, between(14, 15)))

        (fill,) = classified(live, candidate).auto_applicable

        assert fill.after == between(14, 15)
        assert fill.before is None

    def test_a_week_with_no_live_plan_is_filled_entirely(self) -> None:
        candidate = a_week(block(GYM, between(9, 10)), block(LEETCODE, between(14, 15)))

        classification = classified(None, candidate)

        assert len(classification.auto_applicable) == 2
        assert classification.proposal_diff.is_empty()
        assert classification.conflicts == ()

    def test_a_block_abutting_a_live_block_fills_empty_space(self) -> None:
        """Half-open spans: 10:00 to 11:00 covers no minute 09:00 to 10:00 covered."""
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(9, 10)), block(LEETCODE, between(10, 11)))

        assert classified(live, candidate).applies_immediately()

    def test_filling_a_slot_the_solver_could_not_fill_displaces_nothing(self) -> None:
        """An empty slot is a gap with a reason, not a block, so binding one late is a fill."""
        live = a_document(blocks=(block(GYM, between(9, 10)),), empty_slots=(a_slot(),))
        candidate = a_document(
            blocks=(block(GYM, between(9, 10)), block(LEETCODE, between(19, 20))), empty_slots=()
        )

        assert a_slot().interval == between(19, 20)
        assert classified(live, candidate).applies_immediately()

    def test_a_block_placed_inside_a_live_forbidden_window_fills_empty_space(self) -> None:
        """A window explains that nothing is there, and another Area may still be placed in one."""
        live = a_document(blocks=(block(GYM, between(9, 10)),), forbidden_windows=(a_window(),))
        candidate = a_document(
            blocks=(block(GYM, between(9, 10)), block(LEETCODE, between(17, 18)))
        )

        assert a_window().interval.overlaps(between(17, 18))
        assert classified(live, candidate).applies_immediately()


class TestWhatWaitsForAssent:
    def test_a_new_block_that_displaces_a_live_block_is_proposed(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(9, 10)), block(LEETCODE, between(9.5, 11)))

        classification = classified(live, candidate)

        assert classification.auto_applicable == ()
        assert [change.after for change in classification.proposal_diff.added] == [between(9.5, 11)]
        assert not classification.applies_immediately()

    def test_a_live_block_the_candidate_drops_is_proposed_as_a_removal(self) -> None:
        live = a_week(block(GYM, between(9, 10)), block(LEETCODE, between(14, 15)))
        candidate = a_week(block(GYM, between(9, 10)))

        (removal,) = classified(live, candidate).proposal_diff.removed

        assert removal.block_id == block(LEETCODE, between(14, 15)).id
        assert (removal.before, removal.after) == (between(14, 15), None)

    def test_one_block_at_two_placements_is_proposed_as_a_move(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(17, 18)))

        (move,) = classified(live, candidate).proposal_diff.moved

        assert (move.before, move.after) == (between(9, 10), between(17, 18))
        assert move.block_id == block(GYM, between(9, 10)).id

    def test_a_block_the_candidate_leaves_alone_is_in_no_class(self) -> None:
        live = a_week(block(GYM, between(9, 10)))

        classification = classified(live, a_week(block(GYM, between(9, 10))))

        assert classification.is_empty()

    def test_a_solve_that_changes_nothing_leaves_no_trace(self) -> None:
        live = a_week(block(GYM, between(9, 10)), block(LEETCODE, between(14, 15)))

        assert classified(live, live).is_empty()
        assert not classified(live, live).applies_immediately()

    def test_a_moved_block_is_not_read_as_a_removal_plus_an_addition(self) -> None:
        """The pairing is on the derived id, which a changed placement does not change."""
        live = a_week(block(GYM, between(9, 10)))

        classification = classified(live, a_week(block(GYM, between(17, 18))))

        assert (classification.proposal_diff.added, classification.proposal_diff.removed) == (
            (),
            (),
        )
        assert len(classification.proposal_diff.moved) == 1


class TestAutoApplicationIsAllOrNothing:
    def test_a_candidate_that_fills_and_moves_is_held_whole(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(17, 18)), block(LEETCODE, between(14, 15)))

        classification = classified(live, candidate)

        assert len(classification.auto_applicable) == 1
        assert len(classification.proposal_diff.moved) == 1
        assert not classification.applies_immediately()

    def test_a_candidate_that_fills_and_drops_is_held_whole(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(LEETCODE, between(14, 15)))

        assert not classified(live, candidate).applies_immediately()

    def test_twelve_pins_append_nothing_because_every_diff_holds_a_move(self) -> None:
        """The weekly session's own arithmetic: no revision, so no projection either."""
        live = a_week(*(block(_a_habit(index), between(index, index + 0.5)) for index in range(12)))
        candidate = live
        for index in range(12):
            candidate = _dragged(candidate, to=between(index + 12, index + 12.5), index=index)
            classification = classified(live, candidate)

            assert not classification.applies_immediately()
            assert len(classification.proposal_diff.moved) == index + 1


class TestThePastIsNotClassified:
    def test_a_new_block_that_has_started_is_in_no_class(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(9, 10)), block(LEETCODE, between(14, 15)))

        classification = classify(live, candidate, now=at(14))

        assert classification.is_empty()

    def test_a_live_block_that_has_started_is_never_proposed_as_a_removal(self) -> None:
        live = a_week(block(GYM, between(9, 10)))

        classification = classify(live, a_week(), now=at(9))

        assert classification.is_empty()

    def test_a_block_that_has_started_is_never_proposed_as_a_move(self) -> None:
        live = a_week(block(GYM, between(9, 10)))

        classification = classify(live, a_week(block(GYM, between(17, 18))), now=at(9.5))

        assert classification.is_empty()

    def test_a_candidate_that_would_move_a_block_into_the_past_is_not_classified(self) -> None:
        live = a_week(block(GYM, between(17, 18)))

        classification = classify(live, a_week(block(GYM, between(9, 10))), now=at(12))

        assert classification.is_empty()

    def test_a_block_starting_exactly_now_has_started(self) -> None:
        live = a_week(block(GYM, between(9, 10)))

        assert classify(live, a_week(), now=at(9)).is_empty()
        assert not classify(live, a_week(), now=at(8.75)).is_empty()


class TestWhatCollides:
    def test_a_commitment_over_a_planned_block_is_a_conflict(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(9, 10)), block(STANDUP, between(9.5, 10.5)))

        classification = classified(live, candidate)
        (conflict,) = classification.conflicts

        assert conflict.anchor_id == INTERVIEW
        assert conflict.block_id == block(GYM, between(9, 10)).id
        assert conflict.overlap == between(9.5, 10)

    def test_an_arriving_commitment_needs_assent_to_displace_as_well_as_raising_the_conflict(
        self,
    ) -> None:
        """Two classes, two questions: the notice is what must be resolved, and nothing moved."""
        live = a_week(block(GYM, between(9, 10)))
        candidate = a_week(block(GYM, between(9, 10)), block(STANDUP, between(9.5, 10.5)))

        classification = classified(live, candidate)

        assert [change.block_id for change in classification.proposal_diff.added] == [
            block(STANDUP, between(9.5, 10.5)).id
        ]
        assert len(classification.conflicts) == 1
        assert classification.auto_applicable == ()

    def test_a_derived_block_over_a_pinned_block_is_a_conflict_named_for_the_commitment(
        self,
    ) -> None:
        """The third overlap class: both immovable, and the solver created neither."""
        live = a_week(pinned(block(GYM, between(15, 16))))
        candidate = a_week(pinned(block(GYM, between(15, 16))), block(TRANSIT, between(15.5, 16)))

        classification = classified(live, candidate)
        (conflict,) = classification.conflicts

        assert conflict.anchor_id == INTERVIEW
        assert conflict.block_id == block(GYM, between(15, 16)).id
        assert [change.block_id for change in classification.proposal_diff.added] == [
            block(TRANSIT, between(15.5, 16)).id
        ]

    def test_a_derived_block_over_an_unpinned_block_is_a_proposal_rather_than_a_conflict(
        self,
    ) -> None:
        """The geometry is immediate; the adoption still obeys the authority rule."""
        live = a_week(block(GYM, between(15, 16)))
        candidate = a_week(block(GYM, between(15, 16)), block(TRANSIT, between(15.5, 16)))

        classification = classified(live, candidate)

        assert classification.conflicts == ()
        assert len(classification.proposal_diff.added) == 1
        assert classification.auto_applicable == ()

    def test_a_commitment_over_another_commitment_is_not_a_conflict(self) -> None:
        other = BindingRef.for_anchor(uuid4())
        live = a_week(block(STANDUP, between(9, 10)))
        candidate = a_week(block(STANDUP, between(9, 10)), block(other, between(9.5, 10.5)))

        assert classified(live, candidate).conflicts == ()

    def test_a_conflict_is_raised_once_per_commitment_and_block(self) -> None:
        """A commitment reaching one block itself and through a buffer asks one question."""
        live = a_week(pinned(block(GYM, between(9, 12))))

        found = detected_conflicts(
            live,
            anchors=(Anchor(anchor_id=INTERVIEW, interval=between(11, 12), title="Standup"),),
            derived=(
                ShadowBlock(
                    binding=TRANSIT, interval=between(9.5, 10), area_id=FITNESS, title="Leave"
                ),
            ),
            now=BEFORE_THE_WEEK,
        )

        assert found == (
            DetectedConflict(
                anchor_id=INTERVIEW,
                block_id=block(GYM, between(9, 12)).id,
                overlap=between(9.5, 10),
            ),
        )

    def test_a_buffer_pinned_elsewhere_does_not_collide_with_its_own_fresh_geometry(self) -> None:
        live = a_week(pinned(block(TRANSIT, between(15, 16))))

        found = detected_conflicts(
            live,
            derived=(
                ShadowBlock(
                    binding=TRANSIT, interval=between(15.5, 16), area_id=CAREER, title="Leave"
                ),
            ),
            now=BEFORE_THE_WEEK,
        )

        assert found == ()

    def test_a_commitment_that_has_started_still_conflicts_with_a_future_block(self) -> None:
        """The block is what a resolution acts on, so the commitment's own start decides nothing."""
        live = a_week(block(GYM, between(16, 17)))

        found = detected_conflicts(
            live,
            anchors=(Anchor(anchor_id=INTERVIEW, interval=between(10, 18), title="Standup"),),
            now=at(12),
        )

        assert [conflict.block_id for conflict in found] == [block(GYM, between(16, 17)).id]

    def test_nothing_collides_with_a_block_that_has_started(self) -> None:
        live = a_week(block(GYM, between(9, 12)))

        found = detected_conflicts(
            live,
            anchors=(Anchor(anchor_id=INTERVIEW, interval=between(11, 12), title="Standup"),),
            now=at(10),
        )

        assert found == ()

    def test_a_week_with_no_live_plan_collides_with_nothing(self) -> None:
        found = detected_conflicts(
            None,
            anchors=(Anchor(anchor_id=INTERVIEW, interval=between(11, 12), title="Standup"),),
            now=BEFORE_THE_WEEK,
        )

        assert found == ()


class TestTheClassificationIsAValue:
    def test_the_same_pair_classifies_the_same_way_whatever_order_it_was_read_in(self) -> None:
        """Each class takes its order from a different document, so both are read reversed."""
        held = [block(_a_habit(index), between(index, index + 0.5)) for index in range(6)]
        arriving = [block(_a_habit(index), between(index + 12, index + 12.5)) for index in range(6)]

        assert classified(a_week(*held), a_week(*held, *arriving)) == classified(
            a_week(*reversed(held)), a_week(*reversed(arriving), *held)
        )
        assert classified(a_week(*held), a_week()) == classified(a_week(*reversed(held)), a_week())

    def test_the_classes_are_ordered_by_placement(self) -> None:
        live = a_week()
        candidate = a_week(block(LEETCODE, between(14, 15)), block(GYM, between(9, 10)))

        placements = [change.after for change in classified(live, candidate).auto_applicable]

        assert placements == [between(9, 10), between(14, 15)]

    def test_two_documents_of_different_weeks_are_refused(self) -> None:
        live = a_week(block(GYM, between(9, 10)))
        elsewhere = a_document(week=IsoWeek(2026, 9), blocks=())

        with pytest.raises(ClassificationRejected, match="2026-W07 and 2026-W09"):
            classified(live, elsewhere)

    def test_a_change_that_replaced_a_placement_may_not_auto_apply(self) -> None:
        displacing = BlockChange.added(block(LEETCODE, between(14, 15)))

        with pytest.raises(ClassificationRejected, match="applies without asking"):
            Classification(auto_applicable=(replace(displacing, before=between(9, 10)),))

    def test_an_empty_classification_applies_nothing(self) -> None:
        empty = Classification()

        assert empty.is_empty()
        assert not empty.applies_immediately()
        assert empty.proposal_diff == ProposalDiff()


def _a_habit(index: int) -> BindingRef:
    return BindingRef.for_habit(uuid4(), index=index)


def _dragged(document: PlanDocument, *, to: Interval, index: int) -> PlanDocument:
    """``document`` with one of its blocks moved, which is what a pin during a session produces."""
    blocks = list(document.blocks)
    blocks[index] = replace(blocks[index], interval=to)
    return replace(document, blocks=tuple(blocks))
