"""Phase 4: the four move kinds, and the inequality that makes the descent well behaved.

The move kinds are driven directly, because a search that accepts only strict improvements may
legitimately accept none of them on a given week: a test that asserted "the plan changed" would be
asserting that the construction was bad rather than that the move exists.

What is asserted about the loop instead is what the design promises of it: the plan never gets
worse, the same inputs consume the same number of iterations, and the budget bounds the work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from syncr_solver.attempt import Attempt
from syncr_solver.binding import bind_slots
from syncr_solver.budget import SolveBudget, never_cancelled
from syncr_solver.filling import fill_gaps
from syncr_solver.moves import RELOCATE, RESIZE, RESPLIT, SWAP, moves
from syncr_solver.objective import evaluate
from syncr_solver.offering import CHECK
from syncr_solver.preferred import ResolvedPreferences
from syncr_solver.search import improve
from tests.materialized_weeks import (
    CAREER,
    a_frame_entry,
    an_area_budget,
    between,
)
from tests.objective_weeks import (
    A_TASK,
    ANOTHER_TASK,
    a_preference,
    a_window,
    an_eligible_task,
    an_occurrence,
    hand_tuned_weights,
)
from tests.solve_weeks import QUICK, a_week

if TYPE_CHECKING:
    from syncr_solver.inputs import SolveInputs

BUDGET = SolveBudget(scored_windows=2, move_evaluations=60, checkpoint_every=5)


def a_week_offering_every_move() -> SolveInputs:
    """A week whose constructed plan holds an elastic occurrence, a divided task, and a twin pair.

    The Monday holds two two-hour gaps and every other day holds one, so a four-hour task with a
    two-hour minimum chunk is divided into two equal pieces: that gives the re-split kind something
    to re-divide and the swap kind two blocks of equal length. The elastic occurrence gives the
    resize kind a range, and every block gives the relocate kind another window.
    """
    frame = (
        a_frame_entry(day=0, interval=between(0, 8)),
        a_frame_entry(day=0, interval=between(10, 12), routine_id=uuid4()),
        a_frame_entry(day=0, interval=between(14, 24), routine_id=uuid4()),
        *(
            a_frame_entry(day=day, interval=between(0, 22, day=day), routine_id=uuid4())
            for day in range(1, 7)
        ),
    )
    return a_week(
        frame=frame,
        habit_occurrences=(an_occurrence(minutes=45, max_minutes=90),),
        eligible_tasks=(
            an_eligible_task(
                task_id=A_TASK,
                remaining_minutes=240,
                min_chunk_minutes=120,
                area_id=CAREER,
                title="Papers",
            ),
            an_eligible_task(
                task_id=ANOTHER_TASK, remaining_minutes=60, area_id=CAREER, title="Notes"
            ),
        ),
        areas=(
            an_area_budget(target_minutes=300),
            an_area_budget(area_id=CAREER, name="Career", target_minutes=600),
        ),
        preferences=(a_preference(owner_id=CAREER, windows=(a_window(20, 22, day=3),)),),
    )


def constructed(week: SolveInputs) -> Attempt:
    """The plan the two construction phases produce, which is what a move is offered over."""
    return fill_gaps(bind_slots(Attempt.of(week)), hand_tuned_weights(), budget=BUDGET)


def kinds_offered(attempt: Attempt, limit: int = 4000) -> set[str]:
    """Which move kinds this plan offers, over a bounded walk of the generator."""
    preferences = ResolvedPreferences(attempt.inputs.preferences)
    found: set[str] = set()
    for index, move in enumerate(moves(attempt, preferences)):
        found.add(move.kind)
        if index >= limit:
            break
    return found


# --------------------------------------------------------------------------------------
# The four kinds
# --------------------------------------------------------------------------------------


def test_the_constructed_plan_this_suite_drives_holds_what_each_kind_needs() -> None:
    # The control for every test below: without the divided task there is nothing to re-split and
    # nothing of equal length to swap, and the assertions would pass over an empty generator.
    attempt = constructed(a_week_offering_every_move())
    chosen = [held for held in attempt.placements if held.chosen]
    lengths = [held.block.interval.total_minutes() for held in chosen]

    assert len(chosen) >= 3
    assert len(lengths) != len(set(lengths)), "a swap needs two blocks of equal length"
    assert any(held.block.binding.split_index is not None for held in chosen), "a division"


def test_all_four_move_kinds_are_offered_on_a_plan_that_holds_what_each_needs() -> None:
    offered = kinds_offered(constructed(a_week_offering_every_move()))

    assert offered == {RELOCATE, SWAP, RESIZE, RESPLIT}


def test_every_move_offered_proposes_a_plan_the_thirteen_rules_accept() -> None:
    """A move is a proposal, and one the rules refused was never proposed at all."""
    attempt = constructed(a_week_offering_every_move())
    preferences = ResolvedPreferences(attempt.inputs.preferences)

    for index, move in enumerate(moves(attempt, preferences)):
        rest = Attempt.of(move.attempt.inputs)
        for held in move.attempt.placements:
            if not held.chosen:
                rest = rest.adding(held)
                continue
            assert CHECK.check(held.placement, rest.state) is None, move.kind
            rest = rest.adding(held)
        if index >= 40:
            break


def test_no_move_touches_a_placement_the_solve_did_not_choose() -> None:
    """The frame, the commitments and the pins are the space rather than candidates inside it."""
    attempt = constructed(a_week_offering_every_move())
    preferences = ResolvedPreferences(attempt.inputs.preferences)
    fixed = {
        (held.block.binding, held.block.interval) for held in attempt.placements if not held.chosen
    }

    for index, move in enumerate(moves(attempt, preferences)):
        held = {
            (one.block.binding, one.block.interval)
            for one in move.attempt.placements
            if not one.chosen
        }
        assert held == fixed, move.kind
        if index >= 40:
            break


def test_a_relocation_moves_one_block_and_leaves_every_other_one_where_it_was() -> None:
    attempt = constructed(a_week_offering_every_move())
    preferences = ResolvedPreferences(attempt.inputs.preferences)
    before = {held.block.id: held.block.interval for held in attempt.placements if held.chosen}

    relocation = next(move for move in moves(attempt, preferences) if move.kind == RELOCATE)
    after = {
        held.block.id: held.block.interval for held in relocation.attempt.placements if held.chosen
    }

    assert len(before) == len(after)
    assert sum(1 for key in before if after.get(key) != before[key]) == 1


def test_a_resize_changes_one_occurrences_length_and_nothing_else() -> None:
    attempt = constructed(a_week_offering_every_move())
    preferences = ResolvedPreferences(attempt.inputs.preferences)

    resize = next(move for move in moves(attempt, preferences) if move.kind == RESIZE)
    lengths = sorted(
        held.block.interval.total_minutes() for held in resize.attempt.placements if held.chosen
    )
    before = sorted(
        held.block.interval.total_minutes() for held in attempt.placements if held.chosen
    )

    assert lengths != before
    assert len(lengths) == len(before)


# --------------------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------------------


def test_the_descent_never_returns_a_plan_worse_than_the_one_it_started_from() -> None:
    attempt = constructed(a_week_offering_every_move())
    weights = hand_tuned_weights()
    before = evaluate(attempt.document(), inputs=attempt.inputs, weights=weights).total()

    found = improve(attempt, weights, budget=BUDGET, cancelled=never_cancelled)

    assert found.breakdown.total() <= before


def test_the_breakdown_returned_is_the_cost_of_the_plan_returned() -> None:
    """Which is what lets the entry point carry it rather than evaluate the same document twice."""
    attempt = constructed(a_week_offering_every_move())
    weights = hand_tuned_weights()

    found = improve(attempt, weights, budget=BUDGET, cancelled=never_cancelled)

    assert found.breakdown == evaluate(
        found.attempt.document(), inputs=found.attempt.inputs, weights=weights
    )


def test_the_same_plan_consumes_the_same_iterations_and_accepts_the_same_moves() -> None:
    attempt = constructed(a_week_offering_every_move())
    weights = hand_tuned_weights()

    runs = [improve(attempt, weights, budget=BUDGET, cancelled=never_cancelled) for _ in range(3)]

    assert {(found.iterations, found.accepted) for found in runs} == {
        (runs[0].iterations, runs[0].accepted)
    }


def test_the_budget_bounds_the_moves_considered() -> None:
    attempt = constructed(a_week_offering_every_move())

    found = improve(
        attempt,
        hand_tuned_weights(),
        budget=SolveBudget(move_evaluations=7, checkpoint_every=100),
        cancelled=never_cancelled,
    )

    assert found.iterations <= 7


def test_a_budget_of_no_moves_evaluates_the_plan_once_and_changes_nothing() -> None:
    attempt = constructed(a_week_offering_every_move())

    found = improve(
        attempt,
        hand_tuned_weights(),
        budget=SolveBudget(move_evaluations=0),
        cancelled=never_cancelled,
    )

    assert found.iterations == 0
    assert found.accepted == 0
    assert found.attempt.placements == attempt.placements


def test_a_cancelled_search_stops_at_its_next_checkpoint_and_keeps_what_it_had() -> None:
    attempt = constructed(a_week_offering_every_move())

    found = improve(
        attempt,
        hand_tuned_weights(),
        budget=SolveBudget(move_evaluations=1000, checkpoint_every=3),
        cancelled=lambda: True,
    )

    assert found.iterations == 3
    assert found.breakdown.total() > 0


def test_the_quick_budget_this_suite_uses_is_smaller_than_the_shipped_one() -> None:
    # So a suite's speed is not silently a claim about what a real solve spends.
    assert QUICK.move_evaluations < SolveBudget().move_evaluations
