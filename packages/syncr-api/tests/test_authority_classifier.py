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
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from syncr_api.plans.authority import Classification, classify
from syncr_api.plans.errors import ClassificationRejected
from syncr_api.plans.overlaps import DetectedConflict, detected_conflicts
from syncr_api.plans.settled import IDS_IN_A_REFUSAL
from syncr_domain.identity import BindingRef, TransitLeg
from syncr_domain.proposals import BlockChange, ProposalDiff
from syncr_domain.weeks import IsoWeek
from syncr_solver.inputs import Anchor, ShadowBlock
from tests.plan_documents import (
    CAREER,
    FITNESS,
    INTERVIEW,
    WEEK,
    a_block_holding,
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
SLEEP = BindingRef.for_routine(uuid4(), on=WEEK.monday())
LECTURE = BindingRef.for_template_entry(uuid4(), on=WEEK.monday())


def a_week(*blocks: Block) -> PlanDocument:
    """A document holding exactly these blocks, with the figures a week needs."""
    return a_document(blocks=blocks)


def pinned(one: Block) -> Block:
    """``one`` as the user's own edit, which is what makes it immovable to the solver."""
    return replace(one, pinned=True, superseded_placement=between(20, 21), objective_delta=1.5)


def classified(live: PlanDocument | None, candidate: PlanDocument) -> Classification:
    return classify(live, candidate, now=BEFORE_THE_WEEK)


class TestWhatAutoApplies:
    def test_a_block_landing_where_no_live_block_was_fills_empty_space(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )

        classification = classified(live, candidate)

        assert [change.block_id for change in classification.auto_applicable] == [
            a_block_holding(LEETCODE, between(14, 15)).id
        ]
        assert classification.proposal_diff.is_empty()
        assert classification.applies_immediately()

    def test_a_fill_states_where_it_lands_and_replaces_nothing(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )

        (fill,) = classified(live, candidate).auto_applicable

        assert fill.after == between(14, 15)
        assert fill.before is None

    def test_a_week_with_no_live_plan_is_filled_entirely(self) -> None:
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )

        classification = classified(None, candidate)

        assert len(classification.auto_applicable) == 2
        assert classification.proposal_diff.is_empty()
        assert classification.conflicts == ()

    def test_a_block_abutting_a_live_block_fills_empty_space(self) -> None:
        """Half-open spans: 10:00 to 11:00 covers no minute 09:00 to 10:00 covered."""
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(10, 11))
        )

        assert classified(live, candidate).applies_immediately()

    def test_filling_a_slot_the_solver_could_not_fill_displaces_nothing(self) -> None:
        """An empty slot is a gap with a reason, not a block, so binding one late is a fill."""
        live = a_document(blocks=(a_block_holding(GYM, between(9, 10)),), empty_slots=(a_slot(),))
        candidate = a_document(
            blocks=(
                a_block_holding(GYM, between(9, 10)),
                a_block_holding(LEETCODE, between(19, 20)),
            ),
            empty_slots=(),
        )

        assert a_slot().interval == between(19, 20)
        assert classified(live, candidate).applies_immediately()

    def test_a_block_placed_inside_a_live_forbidden_window_fills_empty_space(self) -> None:
        """A window explains that nothing is there, and another Area may still be placed in one."""
        live = a_document(
            blocks=(a_block_holding(GYM, between(9, 10)),), forbidden_windows=(a_window(),)
        )
        candidate = a_document(
            blocks=(
                a_block_holding(GYM, between(9, 10)),
                a_block_holding(LEETCODE, between(17, 18)),
            )
        )

        assert a_window().interval.overlaps(between(17, 18))
        assert classified(live, candidate).applies_immediately()


class TestWhatWaitsForAssent:
    def test_a_new_block_that_displaces_a_live_block_is_proposed(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(9.5, 11))
        )

        classification = classified(live, candidate)

        assert classification.auto_applicable == ()
        assert [change.after for change in classification.proposal_diff.added] == [between(9.5, 11)]
        assert not classification.applies_immediately()

    def test_a_live_block_the_candidate_drops_is_proposed_as_a_removal(self) -> None:
        live = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )
        candidate = a_week(a_block_holding(GYM, between(9, 10)))

        (removal,) = classified(live, candidate).proposal_diff.removed

        assert removal.block_id == a_block_holding(LEETCODE, between(14, 15)).id
        assert (removal.before, removal.after) == (between(14, 15), None)

    def test_one_block_at_two_placements_is_proposed_as_a_move(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(a_block_holding(GYM, between(17, 18)))

        (move,) = classified(live, candidate).proposal_diff.moved

        assert (move.before, move.after) == (between(9, 10), between(17, 18))
        assert move.block_id == a_block_holding(GYM, between(9, 10)).id

    def test_a_block_the_candidate_leaves_alone_is_in_no_class(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))

        classification = classified(live, a_week(a_block_holding(GYM, between(9, 10))))

        assert classification.is_empty()

    def test_a_solve_that_changes_nothing_leaves_no_trace(self) -> None:
        live = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(LEETCODE, between(14, 15))
        )

        assert classified(live, live).is_empty()
        assert not classified(live, live).applies_immediately()

    def test_a_moved_block_is_not_read_as_a_removal_plus_an_addition(self) -> None:
        """The pairing is on the derived id, which a changed placement does not change."""
        live = a_week(a_block_holding(GYM, between(9, 10)))

        classification = classified(live, a_week(a_block_holding(GYM, between(17, 18))))

        assert (classification.proposal_diff.added, classification.proposal_diff.removed) == (
            (),
            (),
        )
        assert len(classification.proposal_diff.moved) == 1


class TestAutoApplicationIsAllOrNothing:
    def test_a_candidate_that_fills_and_moves_is_held_whole(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(17, 18)), a_block_holding(LEETCODE, between(14, 15))
        )

        classification = classified(live, candidate)

        assert len(classification.auto_applicable) == 1
        assert len(classification.proposal_diff.moved) == 1
        assert not classification.applies_immediately()

    def test_a_candidate_that_fills_and_drops_is_held_whole(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(a_block_holding(LEETCODE, between(14, 15)))

        assert not classified(live, candidate).applies_immediately()

    def test_twelve_pins_append_nothing_because_every_diff_holds_a_move(self) -> None:
        """The weekly session's own arithmetic: no revision, so no projection either."""
        live = a_week(
            *(a_block_holding(_a_habit(index), between(index, index + 0.5)) for index in range(12))
        )
        candidate = live
        for index in range(12):
            candidate = _dragged(candidate, to=between(index + 12, index + 12.5), index=index)
            classification = classified(live, candidate)

            assert not classification.applies_immediately()
            assert len(classification.proposal_diff.moved) == index + 1


class TestThePastIsNotClassified:
    def test_a_block_the_week_has_reached_is_in_no_class_when_both_documents_agree(self) -> None:
        # The block is in both documents at one placement, so nothing is
        # proposed about it, while the fill beside it is classified normally.
        started = a_block_holding(GYM, between(9, 10))
        live = a_week(started)
        candidate = a_week(started, a_block_holding(LEETCODE, between(14, 15)))

        classification = classify(live, candidate, now=at(9.5))

        assert [change.after for change in classification.auto_applicable] == [between(14, 15)]
        assert classification.proposal_diff.is_empty()
        assert classification.applies_immediately()

    def test_a_new_block_that_has_started_is_in_no_class(self) -> None:
        # The candidate places it in the past and the live plan holds it there too, so there is
        # nothing to auto-apply: a fill is space the week has not spent yet.
        started = a_block_holding(LEETCODE, between(14, 15))
        live = a_week(a_block_holding(GYM, between(9, 10)), started)
        candidate = a_week(a_block_holding(GYM, between(9, 10)), started)

        assert classify(live, candidate, now=at(14)).is_empty()

    def test_a_started_block_is_in_no_class_even_when_it_is_pinned(self) -> None:
        # Which is what keeps this module out of the question of what authority means over a block
        # that has started and is pinned: such a block is not classified at all.
        held = pinned(a_block_holding(GYM, between(9, 10)))
        live = a_week(held)

        assert classify(live, a_week(held), now=at(9.5)).is_empty()

    def test_a_block_starting_exactly_now_has_started(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))

        with pytest.raises(ClassificationRejected, match="dropped"):
            classify(live, a_week(), now=at(9))
        assert len(classify(live, a_week(), now=at(8.75)).proposal_diff.removed) == 1


class TestThePastMayNotBeRestated:
    """The guard the three classes cannot be, because what persists is the document.

    Each case below partitions into nothing the classes can see -- zero removals, zero moves -- and
    would replace the plan of record with a week whose past happened differently. The fill in three
    of them is what makes the write reachable: without it the classification would be empty and
    nothing would be appended.
    """

    def test_a_candidate_that_drops_a_started_block_while_filling_a_gap_is_refused(self) -> None:
        live = a_week(a_block_holding(GYM, between(8, 9)))
        candidate = a_week(a_block_holding(LEETCODE, between(14, 15)))

        with pytest.raises(ClassificationRejected, match="places a block the week has already"):
            classify(live, candidate, now=at(10))

    def test_a_candidate_that_moves_a_started_block_while_filling_a_gap_is_refused(self) -> None:
        started = a_block_holding(GYM, between(8, 9))
        live = a_week(started)
        candidate = a_week(
            replace(started, interval=between(6, 7)), a_block_holding(LEETCODE, between(14, 15))
        )

        with pytest.raises(ClassificationRejected, match="moved"):
            classify(live, candidate, now=at(10))

    def test_a_candidate_that_invents_a_block_in_the_past_is_refused(self) -> None:
        live = a_week(a_block_holding(GYM, between(8, 9)))
        candidate = a_week(
            a_block_holding(GYM, between(8, 9)), a_block_holding(LEETCODE, between(6, 7))
        )

        with pytest.raises(ClassificationRejected, match="invented"):
            classify(live, candidate, now=at(10))

    def test_a_candidate_that_moves_a_future_block_into_the_past_is_refused(self) -> None:
        live = a_week(a_block_holding(GYM, between(17, 18)))

        with pytest.raises(ClassificationRejected, match="invented"):
            classify(live, a_week(a_block_holding(GYM, between(9, 10))), now=at(12))

    def test_a_rewritten_past_is_refused_even_with_nothing_else_in_the_diff(self) -> None:
        # Previously this classified as empty, which wrote nothing and said nothing. A candidate
        # that disagrees with the past is a producer defect, and a defect that writes nothing is
        # still one worth failing the solve over.
        live = a_week(a_block_holding(GYM, between(8, 9)))

        with pytest.raises(ClassificationRejected):
            classify(live, a_week(), now=at(10))

    def test_the_refusal_names_the_blocks_it_disagrees_about_and_bounds_the_list(self) -> None:
        held = [a_block_holding(_a_habit(index), between(index, index + 0.5)) for index in range(6)]
        live = a_week(*held)

        overflow = len(held) - IDS_IN_A_REFUSAL
        with pytest.raises(ClassificationRejected, match=f"and {overflow} more") as refused:
            classify(live, a_week(), now=at(12))

        named = [one for one in held if one.id in str(refused.value)]
        assert len(named) == IDS_IN_A_REFUSAL

    def test_a_week_with_no_live_plan_may_state_a_past_of_its_own(self) -> None:
        # The first plan for a week that is half elapsed. There is no previous plan of record to
        # rewrite, so its elapsed days are the week as this plan describes it, and only the part of
        # it the week has not reached is a fill.
        candidate = a_week(
            a_block_holding(GYM, between(8, 9)), a_block_holding(LEETCODE, between(14, 15))
        )

        classification = classify(None, candidate, now=at(10))

        assert [change.after for change in classification.auto_applicable] == [between(14, 15)]
        assert classification.proposal_diff.is_empty()

    def test_a_pair_that_agrees_about_the_past_is_classified_normally(self) -> None:
        # The positive control for every refusal above: the guard fires on a disagreement, not on
        # the presence of a started block.
        started = a_block_holding(GYM, between(8, 9))
        live = a_week(started)
        candidate = a_week(started, a_block_holding(LEETCODE, between(14, 15)))

        assert classify(live, candidate, now=at(10)).applies_immediately()

    @pytest.mark.parametrize(
        "restated",
        [{"area_id": FITNESS}, {"title": "Gym \u00b7 Pull"}],
        ids=["re-filed into another Area", "renamed"],
    )
    def test_a_started_blocks_content_may_drift_because_refusing_it_would_wedge_the_week(
        self, restated: dict[str, Any]
    ) -> None:
        # Deliberately outside the rule, and asserted so nobody widens it by accident. A task
        # renamed or re-filed into another Area on Wednesday would otherwise stop every solve of
        # that week for the rest of it, which is worse than the drift. What the drift costs is that
        # an elapsed hour can be re-attributed.
        started = a_block_holding(GYM, between(8, 9))
        live = a_week(started)
        candidate = a_week(replace(started, **restated), a_block_holding(LEETCODE, between(14, 15)))

        assert classify(live, candidate, now=at(10)).applies_immediately()

    @pytest.mark.parametrize("span", [between(8, 9.5), between(8, 8.5)], ids=["longer", "shorter"])
    def test_a_started_blocks_duration_is_inside_the_rule(self, span: Interval) -> None:
        # The other side of the same boundary: the comparison is interval equality, so a span that
        # ends elsewhere is a placement the week did not hold.
        started = a_block_holding(GYM, between(8, 9))
        live = a_week(started)

        with pytest.raises(ClassificationRejected, match="moved"):
            classify(live, a_week(replace(started, interval=span)), now=at(10))


class TestTheRuleBindsWhatTheSolveChoseAndNothingElse:
    """The narrowing by origin, driven from both sides of the split.

    The rule is stated over the two origins whose placement the solve chooses. A block whose time a
    declaration or an import fixes is re-derived at its CURRENT span on every solve, whether or not
    the week has reached it, so binding those origins refused two ordinary upstream events and
    wedged the week: every solve of it failed until it left the horizon.

    ``plans/settled.py`` carries the decision, the two shapes, and the two answers not taken.
    """

    def test_a_commitment_corrected_after_it_began_does_not_refuse_the_candidate(self) -> None:
        # The user extended a meeting that was in progress. The feed now says 07:30-08:30, the
        # live plan holds 07:00-08:00, and the candidate carries the corrected span because
        # derivation restates a fact rather than repeating a decision.
        live = a_week(a_block_holding(STANDUP, between(7, 8)))
        candidate = a_week(
            a_block_holding(STANDUP, between(7.5, 8.5)), a_block_holding(LEETCODE, between(14, 15))
        )

        assert classify(live, candidate, now=at(9)).applies_immediately()

    def test_a_routine_edited_mid_week_whose_occurrence_has_begun_does_not_refuse_it(self) -> None:
        # Sleep shortened from 23:00-07:00 to 23:00-06:30 while the occurrence was running.
        live = a_week(a_block_holding(SLEEP, between(-1, 7)))
        candidate = a_week(
            a_block_holding(SLEEP, between(-1, 6.5)), a_block_holding(LEETCODE, between(14, 15))
        )

        assert classify(live, candidate, now=at(9)).applies_immediately()

    @pytest.mark.parametrize(
        "binding",
        [STANDUP, PREP, TRANSIT, SLEEP, LECTURE],
        ids=["a commitment", "its prep", "its transit", "a routine", "a concrete entry"],
    )
    def test_no_origin_whose_time_its_source_fixes_is_bound(self, binding: BindingRef) -> None:
        # The whole half of the split, so a sixth such origin is covered by the same rule rather
        # than by whichever of these five a later reader thought to check.
        live = a_week(a_block_holding(binding, between(8, 9)))
        candidate = a_week(a_block_holding(LEETCODE, between(14, 15)))

        assert classify(live, candidate, now=at(10)).applies_immediately()

    @pytest.mark.parametrize("binding", [GYM, LEETCODE], ids=["a due occurrence", "backlog work"])
    def test_what_the_solve_placed_is_still_bound_in_both_directions(
        self, binding: BindingRef
    ) -> None:
        # The control for the parametrization above: the narrowing removed the wedge and kept the
        # shape the rule exists for, which is a solve dropping or moving its own elapsed placement.
        started = a_block_holding(binding, between(8, 9))
        live = a_week(started)

        with pytest.raises(ClassificationRejected, match="dropped"):
            classify(live, a_week(a_block_holding(GYM, between(14, 15))), now=at(10))
        with pytest.raises(ClassificationRejected, match="moved"):
            classify(live, a_week(replace(started, interval=between(6, 7))), now=at(10))

    def test_an_exempt_origin_in_the_past_is_still_in_no_output_class(self) -> None:
        # What the exemption does NOT do: the corrected span is carried by the document, and the
        # classification reports nothing about it, so no revision claims to have moved anything.
        live = a_week(a_block_holding(STANDUP, between(7, 8)))
        candidate = a_week(a_block_holding(STANDUP, between(7.5, 8.5)))

        assert classify(live, candidate, now=at(9)).is_empty()


class TestWhatCollides:
    def test_a_commitment_over_a_planned_block_is_a_conflict(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(STANDUP, between(9.5, 10.5))
        )

        classification = classified(live, candidate)
        (conflict,) = classification.conflicts

        assert conflict.anchor_id == INTERVIEW
        assert conflict.block_id == a_block_holding(GYM, between(9, 10)).id
        assert conflict.overlap == between(9.5, 10)

    def test_an_arriving_commitment_needs_assent_to_displace_as_well_as_raising_the_conflict(
        self,
    ) -> None:
        """Two classes, two questions: the notice is what must be resolved, and nothing moved."""
        live = a_week(a_block_holding(GYM, between(9, 10)))
        candidate = a_week(
            a_block_holding(GYM, between(9, 10)), a_block_holding(STANDUP, between(9.5, 10.5))
        )

        classification = classified(live, candidate)

        assert [change.block_id for change in classification.proposal_diff.added] == [
            a_block_holding(STANDUP, between(9.5, 10.5)).id
        ]
        assert len(classification.conflicts) == 1
        assert classification.auto_applicable == ()

    def test_a_derived_block_over_a_pinned_block_is_a_conflict_named_for_the_commitment(
        self,
    ) -> None:
        """The third overlap class: both immovable, and the solver created neither."""
        live = a_week(pinned(a_block_holding(GYM, between(15, 16))))
        candidate = a_week(
            pinned(a_block_holding(GYM, between(15, 16))),
            a_block_holding(TRANSIT, between(15.5, 16)),
        )

        classification = classified(live, candidate)
        (conflict,) = classification.conflicts

        assert conflict.anchor_id == INTERVIEW
        assert conflict.block_id == a_block_holding(GYM, between(15, 16)).id
        assert [change.block_id for change in classification.proposal_diff.added] == [
            a_block_holding(TRANSIT, between(15.5, 16)).id
        ]

    def test_a_derived_block_over_an_unpinned_block_is_a_proposal_rather_than_a_conflict(
        self,
    ) -> None:
        """The geometry is immediate; the adoption still obeys the authority rule."""
        live = a_week(a_block_holding(GYM, between(15, 16)))
        candidate = a_week(
            a_block_holding(GYM, between(15, 16)), a_block_holding(TRANSIT, between(15.5, 16))
        )

        classification = classified(live, candidate)

        assert classification.conflicts == ()
        assert len(classification.proposal_diff.added) == 1
        assert classification.auto_applicable == ()

    def test_a_commitment_over_another_commitment_is_not_a_conflict(self) -> None:
        other = BindingRef.for_anchor(uuid4())
        live = a_week(a_block_holding(STANDUP, between(9, 10)))
        candidate = a_week(
            a_block_holding(STANDUP, between(9, 10)), a_block_holding(other, between(9.5, 10.5))
        )

        assert classified(live, candidate).conflicts == ()

    def test_a_conflict_is_raised_once_per_commitment_and_block(self) -> None:
        """A commitment reaching one block itself and through a buffer asks one question."""
        live = a_week(pinned(a_block_holding(GYM, between(9, 12))))

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
                anchor_id=INTERVIEW, iso_week=WEEK, binding=GYM, overlap=between(9.5, 10)
            ),
        )
        assert found[0].block_id == a_block_holding(GYM, between(9, 12)).id

    def test_a_buffer_pinned_elsewhere_does_not_collide_with_its_own_fresh_geometry(self) -> None:
        live = a_week(pinned(a_block_holding(TRANSIT, between(15, 16))))

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
        live = a_week(a_block_holding(GYM, between(16, 17)))

        found = detected_conflicts(
            live,
            anchors=(Anchor(anchor_id=INTERVIEW, interval=between(10, 18), title="Standup"),),
            now=at(12),
        )

        assert [conflict.block_id for conflict in found] == [
            a_block_holding(GYM, between(16, 17)).id
        ]

    def test_nothing_collides_with_a_block_that_has_started(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 12)))

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
        held = [a_block_holding(_a_habit(index), between(index, index + 0.5)) for index in range(6)]
        arriving = [
            a_block_holding(_a_habit(index), between(index + 12, index + 12.5))
            for index in range(6)
        ]

        assert classified(a_week(*held), a_week(*held, *arriving)) == classified(
            a_week(*reversed(held)), a_week(*reversed(arriving), *held)
        )
        assert classified(a_week(*held), a_week()) == classified(a_week(*reversed(held)), a_week())

    def test_the_classes_are_ordered_by_placement(self) -> None:
        live = a_week()
        candidate = a_week(
            a_block_holding(LEETCODE, between(14, 15)), a_block_holding(GYM, between(9, 10))
        )

        placements = [change.after for change in classified(live, candidate).auto_applicable]

        assert placements == [between(9, 10), between(14, 15)]

    def test_two_documents_of_different_weeks_are_refused(self) -> None:
        live = a_week(a_block_holding(GYM, between(9, 10)))
        elsewhere = a_document(week=IsoWeek(2026, 9), blocks=())

        with pytest.raises(ClassificationRejected, match="2026-W07 and 2026-W09"):
            classified(live, elsewhere)

    def test_a_change_that_replaced_a_placement_may_not_auto_apply(self) -> None:
        displacing = BlockChange.added(a_block_holding(LEETCODE, between(14, 15)))

        with pytest.raises(ClassificationRejected, match="applies without asking"):
            Classification(auto_applicable=(replace(displacing, before=between(9, 10)),))

    def test_one_block_may_not_be_in_two_authority_classes(self) -> None:
        # A hand-built classification, because `classify` partitions and cannot produce one. The
        # value refuses it anyway: applied and asked about is two answers for one block.
        arriving = a_block_holding(LEETCODE, between(14, 15))

        with pytest.raises(ClassificationRejected, match="is also held for assent"):
            Classification(
                auto_applicable=(BlockChange.added(arriving),),
                proposal_diff=ProposalDiff(removed=(BlockChange.removed(arriving),)),
            )

    def test_one_block_may_not_appear_twice_among_the_fills(self) -> None:
        # A different mistake from the one above, so it says so: nothing is held for assent here.
        arriving = BlockChange.added(a_block_holding(LEETCODE, between(14, 15)))

        with pytest.raises(ClassificationRejected, match="applies without asking twice"):
            Classification(auto_applicable=(arriving, arriving))

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
