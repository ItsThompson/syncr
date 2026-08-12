"""One pairing rule as its three producers state it, crossed on one week.

A pin and the live-plan block it pins are one placement, at the pin's interval. Three producers in
this package state that rule separately, and each answers a different question in a different shape:
``SolveInputs.committed_occupancy`` unions the spans a week has committed, ``PartialPlan.immovable``
indexes by binding what the solver may not move, and ``inherited`` builds the placements a solve
seeds, each carrying its block's title and Area. So the rule can hold in one of them and not in the
next, and this module reads all three of one week rather than one of three weeks.

The week holds the three states a pin can be in -- the plan holds the block at a span that has
begun, the plan holds it somewhere else, the plan holds it nowhere -- and one binding with no pin,
which is where the agreement stops: an unpinned future block is committed time the solver may still
move, so the union holds it and the other two claim nothing for it.

Every pin here moves its block, because a pin at the span the plan already holds cannot separate a
producer that reads the pin from one that reads the block. And every pin names a span still to come,
because an assembly carries only the pins it has not reached: a pin at a span that has begun is a
record rather than a constraint, so a week holding one is a week no assembler produces.

Every span the week names is disjoint from every other and touches none of them: ``IntervalSet``
merges adjacent members as well as overlapping ones, so two spans that merged would let one member
of the union answer for two bindings. The layout is asserted rather than assumed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from syncr_domain.identity import BindingRef
from syncr_domain.intervals import IntervalSet
from syncr_solver.inheritance import inherited
from syncr_solver.materialize import derive
from syncr_solver.metrics import MaterializeCause
from syncr_solver.state import PartialPlan
from tests.materialized_weeks import (
    CAREER,
    a_block,
    a_live_plan,
    a_pin,
    between,
    inputs,
)
from tests.objective_weeks import an_eligible_task

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval
    from syncr_solver.inputs import SolveInputs

A_TASK_THE_WEEK_REACHED = UUID("00000000-0000-4000-8000-0000000000d1")
A_TASK_THE_WEEK_HAS_NOT = UUID("00000000-0000-4000-8000-0000000000d2")
A_TASK_NO_BLOCK_HOLDS = UUID("00000000-0000-4000-8000-0000000000d3")
A_TASK_NOBODY_PINNED = UUID("00000000-0000-4000-8000-0000000000d4")

STARTED_AND_PINNED = BindingRef.for_task(A_TASK_THE_WEEK_REACHED)
PINNED_ELSEWHERE = BindingRef.for_task(A_TASK_THE_WEEK_HAS_NOT)
PINNED_WITH_NO_BLOCK = BindingRef.for_task(A_TASK_NO_BLOCK_HOLDS)
HELD_BUT_NOT_PINNED = BindingRef.for_task(A_TASK_NOBODY_PINNED)

# ``now`` is Wednesday 09:00, so Monday's span has begun and every later span has not.
STARTED_SPAN = between(8, 10)
STARTED_PIN = between(9, 10, day=5)
ELSEWHERE_SPAN = between(10, 11, day=3)
ELSEWHERE_PIN = between(15, 16, day=3)
NO_BLOCK_PIN = between(9, 10, day=4)
NOT_PINNED_SPAN = between(13, 14, day=4)


def a_week_holding_every_state_a_pin_can_be_in() -> SolveInputs:
    """One week whose plan and pins hold the three pinned states, plus a block nobody pinned.

    The task the plan holds no block for is eligible, which is what makes the third state a pin on
    content the week HOLDS rather than a pin the assembler should never have produced: the
    placements a solve seeds are built from the candidate, so the content has to exist somewhere.
    """
    return inputs(
        live_plan=a_live_plan(
            a_block(binding=STARTED_AND_PINNED, interval=STARTED_SPAN, title="Leetcode"),
            a_block(binding=PINNED_ELSEWHERE, interval=ELSEWHERE_SPAN, title="Papers"),
            a_block(binding=HELD_BUT_NOT_PINNED, interval=NOT_PINNED_SPAN, title="Reading"),
        ),
        pins=(
            a_pin(binding=STARTED_AND_PINNED, interval=STARTED_PIN),
            a_pin(binding=PINNED_ELSEWHERE, interval=ELSEWHERE_PIN),
            a_pin(binding=PINNED_WITH_NO_BLOCK, interval=NO_BLOCK_PIN),
        ),
        eligible_tasks=(
            an_eligible_task(task_id=A_TASK_NO_BLOCK_HOLDS, title="Thesis", area_id=CAREER),
        ),
    )


def spans_the_union_holds_for(week: SolveInputs, binding: BindingRef) -> tuple[Interval, ...]:
    """Every member of the committed union that one of this binding's own spans reaches.

    The union is by interval and names no binding, so a member is attributed to the binding whose
    block or pin it covers. A binding whose block and pin both survive into the union therefore
    answers with two members rather than with the later one.
    """
    named = spans_the_week_names_for(week, binding)
    return tuple(
        member
        for member in week.committed_occupancy()
        if any(member.overlaps(span) for span in named)
    )


def the_span_the_index_holds_for(week: SolveInputs, binding: BindingRef) -> tuple[Interval, ...]:
    """Where the index of what the solver may not move holds this binding, if it holds it at all."""
    held = PartialPlan.of(week).immovable.get(binding)
    return () if held is None else (held.interval,)


def spans_the_seeded_placements_hold_for(
    week: SolveInputs, binding: BindingRef
) -> tuple[Interval, ...]:
    """Where the placements a solve seeds put this binding, composed as the entry point does."""
    derived = derive(week, cause=MaterializeCause.PHASE1).document.blocks
    return tuple(
        placed.block.interval
        for placed in inherited(week, derived)
        if placed.block.binding == binding
    )


def spans_the_week_names_for(week: SolveInputs, binding: BindingRef) -> tuple[Interval, ...]:
    """The spans this week's inputs name for one binding: its plan block, and its pin."""
    return tuple(span for named, span in _spans_by_binding(week) if named == binding)


def _spans_by_binding(week: SolveInputs) -> tuple[tuple[BindingRef, Interval], ...]:
    """Every span this week's inputs name, each with the binding it is named for."""
    blocks = () if week.live_plan is None else week.live_plan.blocks
    return (
        *((block.binding, block.interval) for block in blocks),
        *((pin.binding, pin.interval) for pin in week.pins),
    )


@pytest.mark.parametrize(
    ("binding", "pinned_at"),
    [
        (STARTED_AND_PINNED, STARTED_PIN),
        (PINNED_ELSEWHERE, ELSEWHERE_PIN),
        (PINNED_WITH_NO_BLOCK, NO_BLOCK_PIN),
    ],
    ids=["started-and-pinned", "the-plan-holds-it-elsewhere", "the-plan-holds-it-nowhere"],
)
def test_all_three_producers_hold_a_pinned_binding_at_the_span_the_user_chose(
    binding: BindingRef, pinned_at: Interval
) -> None:
    week = a_week_holding_every_state_a_pin_can_be_in()

    assert {
        "committed_occupancy": spans_the_union_holds_for(week, binding),
        "state.immovable": the_span_the_index_holds_for(week, binding),
        "inherited": spans_the_seeded_placements_hold_for(week, binding),
    } == {
        "committed_occupancy": (pinned_at,),
        "state.immovable": (pinned_at,),
        "inherited": (pinned_at,),
    }


def test_a_block_nobody_pinned_is_committed_time_nothing_else_claims() -> None:
    """The other edge of the pairing: it is the pin that outranks the block, not the block itself.

    An unpinned future block is time the week has committed AND a placement the solver may still
    re-place, so the union holds it at its own span while the index of what may not move and the
    placements a solve seeds hold nothing for it. Three producers that agreed here would be three
    readings of one set rather than three statements of one precedence.
    """
    week = a_week_holding_every_state_a_pin_can_be_in()

    assert {
        "committed_occupancy": spans_the_union_holds_for(week, HELD_BUT_NOT_PINNED),
        "state.immovable": the_span_the_index_holds_for(week, HELD_BUT_NOT_PINNED),
        "inherited": spans_the_seeded_placements_hold_for(week, HELD_BUT_NOT_PINNED),
    } == {
        "committed_occupancy": (NOT_PINNED_SPAN,),
        "state.immovable": (),
        "inherited": (),
    }


def test_no_two_spans_this_week_names_share_a_member_of_the_committed_union() -> None:
    """The control for the attribution above, which reads the union by overlap.

    ``IntervalSet`` merges adjacent members as well as overlapping ones, so two of this week's spans
    that touched would answer as one member for two bindings, and a producer reading the wrong one
    would be indistinguishable from one reading the right one.

    The count is asserted against the week's own blocks and pins first, because a disjointness claim
    over a reading that returned nothing is a claim about nothing.
    """
    week = a_week_holding_every_state_a_pin_can_be_in()
    held = week.live_plan
    assert held is not None
    named = [span for _, span in _spans_by_binding(week)]

    assert len(named) == len(held.blocks) + len(week.pins)
    assert len(IntervalSet(named)) == len(named)
