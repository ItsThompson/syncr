"""H6, H7 and H14: how small a block may be, and where its bounds may fall.

Each rule is driven alone, because the three answer for the candidate and read nothing about the
week. H6 and H7 are also driven at the case that separates them: an atomic demand smaller than its
own minimum chunk, which one accepts and the other must never see.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from syncr_domain.identity import BindingKind, BindingRef, TransitLeg
from syncr_domain.intervals import Interval
from syncr_solver.constraints import ConstraintCheck, ConstraintRule
from syncr_solver.shape import EXEMPT_FROM_THE_SNAP, atomic_not_splittable, below_min_chunk, snap
from syncr_solver.state import PartialPlan
from tests.materialized_weeks import (
    CAREER,
    a_candidate,
    a_prep_block,
    a_sizing,
    at,
    between,
    inputs,
    on,
)

A_TASK_ID = UUID("00000000-0000-4000-8000-0000000000aa")
A_HABIT_ID = UUID("00000000-0000-4000-8000-0000000000ab")
AN_ANCHOR_ID = UUID("00000000-0000-4000-8000-0000000000bb")

EMPTY = PartialPlan.of(inputs())


def minutes_past(hour: int, minutes: int, *, ending: float) -> Interval:
    """A span whose start is deliberately off the quarter hour, as an imported fact's would be."""
    return Interval(at(hour) + timedelta(minutes=minutes), at(ending))


# --------------------------------------------------------------------------------
# H6: an atomic demand is this duration or nothing
# --------------------------------------------------------------------------------


def test_a_chunk_of_an_atomic_demand_is_refused_and_names_the_chunk() -> None:
    rejection = atomic_not_splittable(
        a_candidate(
            between(10, 11),
            title="Submit dissertation",
            binding=BindingRef.for_task(A_TASK_ID, split_index=1),
            sizing=a_sizing(whole_minutes=60, splittable=False),
        ),
        EMPTY,
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.ATOMIC_NOT_SPLITTABLE
    assert rejection.detail == "Submit dissertation is not splittable, and this is chunk 1"


def test_less_of_an_atomic_demand_than_is_left_is_refused_and_states_both_figures() -> None:
    # The other way to divide one. A partial placement with no chunk number would otherwise pass
    # while placing half the work, which is the state the rule exists to make unrepresentable.
    rejection = atomic_not_splittable(
        a_candidate(
            between(10, 10.5),
            title="Submit dissertation",
            sizing=a_sizing(whole_minutes=60, splittable=False),
        ),
        EMPTY,
    )

    assert rejection is not None
    assert rejection.detail == "Submit dissertation takes 60m or nothing, and this is 30m"


def test_an_atomic_demand_placed_whole_is_accepted() -> None:
    candidate = a_candidate(between(10, 11), sizing=a_sizing(whole_minutes=60, splittable=False))

    assert atomic_not_splittable(candidate, EMPTY) is None


def test_an_atomic_demand_placed_longer_than_it_needs_is_not_a_division() -> None:
    # An elastic occurrence sized above its smallest legal length reaches this rule as exactly that
    # shape, so a bound in the other direction would refuse the ordinary case. Over-allocating is
    # charged by the objective's budget term rather than forbidden here.
    candidate = a_candidate(between(10, 11.5), sizing=a_sizing(whole_minutes=60, splittable=False))

    assert atomic_not_splittable(candidate, EMPTY) is None


def test_a_divisible_demand_is_not_judged_by_the_atomic_rule_even_as_a_chunk() -> None:
    candidate = a_candidate(
        between(10, 10.25),
        binding=BindingRef.for_task(A_TASK_ID, split_index=2),
        sizing=a_sizing(whole_minutes=240, min_chunk_minutes=15, splittable=True),
    )

    assert atomic_not_splittable(candidate, EMPTY) is None


# --------------------------------------------------------------------------------
# H7: a divisible demand is placed in usable pieces
# --------------------------------------------------------------------------------


def test_a_piece_below_the_minimum_chunk_is_refused_and_states_both_figures() -> None:
    rejection = below_min_chunk(
        a_candidate(
            between(10, 10.25),
            title="Leetcode",
            sizing=a_sizing(whole_minutes=240, min_chunk_minutes=45, splittable=True),
        ),
        EMPTY,
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.BELOW_MIN_CHUNK
    assert rejection.detail == "Leetcode is placed in 45m at least, and this is 15m"


def test_a_piece_at_exactly_the_minimum_chunk_is_accepted() -> None:
    candidate = a_candidate(
        between(10, 10.75), sizing=a_sizing(whole_minutes=240, min_chunk_minutes=45)
    )

    assert below_min_chunk(candidate, EMPTY) is None


def test_an_atomic_demand_smaller_than_its_own_minimum_chunk_is_placed_whole() -> None:
    # The case that keeps the two rules disjoint. A task with 30m left and a 45m minimum chunk is
    # placed at 30m, because a minimum chunk names a division an atomic demand does not have, and
    # reading it here would report the wrong rule for a candidate H6 already accepted.
    candidate = a_candidate(
        between(10, 10.5),
        sizing=a_sizing(whole_minutes=30, min_chunk_minutes=45, splittable=False),
    )

    assert atomic_not_splittable(candidate, EMPTY) is None
    assert below_min_chunk(candidate, EMPTY) is None


def test_neither_sizing_rule_judges_a_candidate_derivation_sized() -> None:
    # A derived block carries no sizing at all, which is the pairing the candidate enforces, so
    # both rules pass over it rather than reading a figure that is not there.
    derived = a_candidate(
        between(8, 9),
        title="Interview prep",
        binding=a_prep_block(anchor_id=AN_ANCHOR_ID).binding,
        area_id=CAREER,
    )

    assert atomic_not_splittable(derived, EMPTY) is None
    assert below_min_chunk(derived, EMPTY) is None


# --------------------------------------------------------------------------------
# H14: the fifteen-minute grid, and the imported fact that keeps its own time
# --------------------------------------------------------------------------------


def test_a_candidate_off_the_grid_is_refused_and_names_every_bound_that_is_off() -> None:
    minute_precise = minutes_past(10, 7, ending=11)

    rejection = snap(a_candidate(minute_precise, title="Leetcode"), EMPTY)

    assert rejection is not None
    assert rejection.rule is ConstraintRule.SNAP
    assert rejection.detail is not None
    assert rejection.detail.startswith("Leetcode is off the 15-minute grid at ")
    assert str(minute_precise.start) in rejection.detail


def test_a_candidate_whose_end_alone_is_off_the_grid_is_refused() -> None:
    # Both bounds are read, because a duration off the grid moves an end off it from a start that
    # was on it, which is the shape a scaled elastic duration produces.
    span = Interval(at(10), at(10) + timedelta(minutes=40))

    rejection = snap(a_candidate(span, title="Leetcode"), EMPTY)

    assert rejection is not None
    assert rejection.detail == f"Leetcode is off the 15-minute grid at {span.end}"


@pytest.mark.parametrize(
    "binding",
    [
        BindingRef.for_anchor(AN_ANCHOR_ID),
        BindingRef.for_anchor_prep(AN_ANCHOR_ID),
        BindingRef.for_anchor_transit(AN_ANCHOR_ID, leg=TransitLeg.BACK),
    ],
    ids=["anchor", "prep", "transit"],
)
def test_an_imported_fact_and_the_buffers_computed_from_it_keep_their_real_time(
    binding: BindingRef,
) -> None:
    # A 30-minute journey before a 16:07 commitment starts at 15:37, and the exemption is what makes
    # the grid a snap target for the user's own placements rather than a claim about every block.
    span = minutes_past(15, 37, ending=16 + 7 / 60)

    assert snap(a_candidate(span, binding=binding, area_id=CAREER), EMPTY) is None


def test_a_template_entry_off_the_grid_is_still_refused() -> None:
    # The exemption is the imported fact's, not every derived block's: an entry's declared time is
    # the user's own and is refused off the grid where it is declared, so one reaching here is a
    # producer that let it through.
    span = minutes_past(6, 47, ending=7)

    rejection = snap(
        a_candidate(span, binding=BindingRef.for_template_entry(UUID(int=9), on=on(0))), EMPTY
    )

    assert rejection is not None
    assert rejection.rule is ConstraintRule.SNAP


def test_the_grid_binds_every_kind_but_the_imported_fact_and_its_buffers() -> None:
    # Bounded by the inventory of binding kinds rather than by the ones anyone listed: an eighth
    # kind is bound by the grid until this set says otherwise.
    assert {
        BindingKind.ANCHOR,
        BindingKind.ANCHOR_PREP,
        BindingKind.ANCHOR_TRANSIT,
    } == EXEMPT_FROM_THE_SNAP
    assert set(BindingKind) - EXEMPT_FROM_THE_SNAP == {
        BindingKind.ROUTINE,
        BindingKind.TEMPLATE_ENTRY,
        BindingKind.HABIT,
        BindingKind.TASK,
    }


def test_a_candidate_on_the_grid_is_accepted() -> None:
    assert snap(a_candidate(between(10, 11)), EMPTY) is None
    assert snap(a_candidate(between(10.25, 10.5)), EMPTY) is None


def test_the_three_shape_rules_are_the_ones_the_table_numbers_six_seven_and_fourteen() -> None:
    reported = {
        rejection.rule
        for rejection in (
            atomic_not_splittable(
                a_candidate(between(10, 10.5), sizing=a_sizing(whole_minutes=60, splittable=False)),
                EMPTY,
            ),
            below_min_chunk(
                a_candidate(between(10, 10.25), sizing=a_sizing(min_chunk_minutes=45)), EMPTY
            ),
            snap(a_candidate(minutes_past(10, 7, ending=11)), EMPTY),
        )
        if rejection is not None
    }

    assert reported == {
        ConstraintRule.ATOMIC_NOT_SPLITTABLE,
        ConstraintRule.BELOW_MIN_CHUNK,
        ConstraintRule.SNAP,
    }


def test_a_habit_occurrence_is_sized_like_any_other_demand() -> None:
    # An occurrence is atomic and elastic: it is placed at a length in its own range, so H6 bounds
    # it below at the smallest legal one and H7 never reads it.
    occurrence = a_candidate(
        between(10, 10.25),
        title="Shower",
        binding=BindingRef.for_habit(A_HABIT_ID, index=0),
        sizing=a_sizing(whole_minutes=30, min_chunk_minutes=30, splittable=False),
    )

    rejection = atomic_not_splittable(occurrence, EMPTY)

    assert rejection is not None
    assert rejection.rule is ConstraintRule.ATOMIC_NOT_SPLITTABLE
    assert below_min_chunk(occurrence, EMPTY) is None
    assert (
        ConstraintCheck((atomic_not_splittable, below_min_chunk)).check(occurrence, EMPTY)
        == rejection
    )
