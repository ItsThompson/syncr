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

from syncr_domain.identity import BindingKind
from syncr_domain.preferences import PreferenceStrength
from syncr_solver.attempt import Attempt
from syncr_solver.binding import bind_slots
from syncr_solver.budget import SolveBudget, never_cancelled
from syncr_solver.filling import fill_gaps
from syncr_solver.inheritance import inherited
from syncr_solver.materialize import derive
from syncr_solver.metrics import MaterializeCause
from syncr_solver.moves import RELOCATE, RESIZE, RESPLIT, SWAP, moves
from syncr_solver.objective import evaluate
from syncr_solver.offering import CHECK
from syncr_solver.preferred import ResolvedPreferences
from syncr_solver.search import _stop, improve
from tests.materialized_weeks import (
    CAREER,
    a_frame_entry,
    a_live_plan,
    a_pin,
    an_area_budget,
    between,
)
from tests.objective_weeks import (
    A_TASK,
    ANOTHER_TASK,
    a_chunk_block,
    a_preference,
    a_window,
    an_eligible_task,
    an_occurrence,
    hand_tuned_weights,
)
from tests.reference_week import reference_week
from tests.search_yield import constructed as constructed_at
from tests.solve_weeks import QUICK, a_week

if TYPE_CHECKING:
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.search import Improved

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
    """The plan the construction produces, which is what a move is offered over.

    Phase 1 and the inheritance run too, rather than starting from an empty attempt. Without them
    the plan holds no placement the solve did not choose, so a test about what a move may not touch
    has nothing to touch and passes over an arrangement the entry point never produces.
    """
    attempt = Attempt.of(
        week,
        placements=inherited(week, derive(week, cause=MaterializeCause.PHASE1).document.blocks),
    )
    return fill_gaps(bind_slots(attempt), hand_tuned_weights(), budget=BUDGET)


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


def a_week_whose_pinned_chunk_a_re_split_could_drop() -> SolveInputs:
    """A divided task with one piece pinned outside its Area's preferred window.

    The arrangement the property below needs and the week above cannot produce: that week holds no
    live plan and no pins, so every placement in it is one the solve chose and the property is
    vacuous with respect to the filter it is named for.

    A re-split drops every piece of the task and lets the packer place the work again, and a
    re-placed piece takes a NEW chunk number, so H11 cannot match it. **What makes dropping the
    pinned piece a strict improvement is the Area's target.** The pinned chunk is netted out of
    ``remaining_minutes``, so re-placing the work does not put it back: the plan loses two hours,
    and with the target at two hours rather than four the Area's deviation falls from the whole of
    it to nothing. So a search that reached the pinned piece would take the move.
    """
    pinned = a_chunk_block(
        task_id=A_TASK,
        index=0,
        of=2,
        interval=between(2, 4, day=3),
        title="Papers",
        area_id=CAREER,
    )
    return a_week(
        eligible_tasks=(
            an_eligible_task(
                task_id=A_TASK,
                remaining_minutes=120,
                min_chunk_minutes=60,
                area_id=CAREER,
                title="Papers",
            ),
        ),
        areas=(an_area_budget(area_id=CAREER, name="Career", target_minutes=120),),
        preferences=(
            a_preference(
                owner_id=CAREER,
                windows=tuple(a_window(18, 22, day=day) for day in range(7)),
                strength=PreferenceStrength.STRONG,
            ),
        ),
        live_plan=a_live_plan(pinned),
        pins=(a_pin(binding=pinned.binding, interval=pinned.interval),),
    )


def test_no_move_touches_a_placement_the_solve_did_not_choose() -> None:
    """The frame, the commitments and the pins are the space rather than candidates inside it.

    Driven over a week that HOLDS a pinned chunk of a divided task, which is the one arrangement a
    move can break the property on: a re-split places the work again under a new chunk number, so
    H11 cannot match the pinned piece and cannot refuse a move that dropped it. Over a week with no
    pins the assertion is true of every move and says nothing, which is what this test used to be.
    """
    attempt = constructed(a_week_whose_pinned_chunk_a_re_split_could_drop())
    preferences = ResolvedPreferences(attempt.inputs.preferences)
    fixed = {
        (held.block.binding, held.block.interval) for held in attempt.placements if not held.chosen
    }

    assert fixed, "the week has to hold a placement the solve did not choose"
    assert any(
        held.chosen and held.block.binding.kind is BindingKind.TASK for held in attempt.placements
    ), "and a chosen piece of the same task, or no re-split is offered at all"

    for index, move in enumerate(moves(attempt, preferences)):
        held = {
            (one.block.binding, one.block.interval)
            for one in move.attempt.placements
            if not one.chosen
        }
        assert held == fixed, move.kind
        if index >= 40:
            break


def test_a_re_split_keeps_the_pinned_piece_of_the_task_it_re_divides() -> None:
    """The property above, read from the other side: the pin is still at its interval afterwards.

    Stated as well as the set equality because this is what a user loses when it fails. Measured
    with the three filters that hold it all removed: the objective falls from 4.667 to 1.667, the
    search accepts the move, and the pinned chunk is absent from the proposal.
    """
    week = a_week_whose_pinned_chunk_a_re_split_could_drop()
    pinned = week.pins[0]

    found = improve(
        constructed(week), hand_tuned_weights(), budget=BUDGET, cancelled=never_cancelled
    )

    assert any(
        block.binding == pinned.binding and block.interval == pinned.interval
        for block in found.attempt.document().blocks
    )


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


# --------------------------------------------------------------------------------------
# The rejection bound
# --------------------------------------------------------------------------------------


def improved_reference_week(budget: SolveBudget) -> Improved:
    """The reference week's descent under this budget, cancellation out of the way.

    Built at the budget it is descended under, the way ``solve`` builds it, and a real week rather
    than the ten-move fixture above: the bound earns its keep where a plan sits near its optimum and
    almost every remaining move is refused, and that fixture reaches its optimum inside a handful of
    moves with no tail to speak of. Both arms of a comparison build at their own budget
    symmetrically, so a difference in the descent is never confounded with one in the construction.
    """
    weights = hand_tuned_weights()
    return improve(
        constructed_at(reference_week(), weights, budget=budget),
        weights,
        budget=budget,
        cancelled=never_cancelled,
    )


def test_a_run_of_rejections_ends_the_search_before_its_budget() -> None:
    """A short refusal run stops the descent early; the move budget alone lets it run on.

    Stopping earlier can only leave a plan the objective likes less, never one it likes more, which
    is the second assertion: a stop condition that improved the plan would be a different mechanism.
    """
    short = improved_reference_week(SolveBudget(rejection_run=10, checkpoint_every=10_000))
    whole = improved_reference_week(SolveBudget(checkpoint_every=10_000))

    assert short.iterations < whole.iterations
    assert short.breakdown.total() >= whole.breakdown.total()


def test_the_rejection_bound_keeps_an_acceptance_that_sits_behind_a_long_run() -> None:
    """The bound sits just above the measured runs, so the descent's last acceptance survives it.

    Measured through ``python -m tests.measure_solve yield``: this week's final acceptance landed on
    iteration 175, behind a run of 56 refusals, though 167 refusals precede it across the descent as
    a whole. A bound of 57 buys it and 56 does not, so the boundary is where the measurement says it
    is, and the counter is refusals SINCE THE LAST ACCEPTANCE rather than a running total -- a
    counter that never reset would have crossed 57 long before the acceptance it protects. The
    counts move when the generator or the objective moves, so re-measure rather than adjust.
    """
    kept = improved_reference_week(SolveBudget(rejection_run=57))
    lost = improved_reference_week(SolveBudget(rejection_run=56))

    assert kept.accepted == lost.accepted + 1
    assert kept.breakdown.total() < lost.breakdown.total()


def test_a_full_rejection_run_stops_where_neither_the_budget_nor_the_checkpoint_does() -> None:
    run = SolveBudget().rejection_run
    budget = SolveBudget(move_evaluations=1000, rejection_run=run, checkpoint_every=100)

    assert _stop(5, run, budget=budget, cancelled=never_cancelled) is True


def test_below_the_run_the_search_stops_on_nothing_but_its_budget_or_its_caller() -> None:
    run = SolveBudget().rejection_run
    budget = SolveBudget(move_evaluations=1000, rejection_run=run, checkpoint_every=100)

    assert _stop(5, run - 1, budget=budget, cancelled=never_cancelled) is False
    # One below the budget, one below the checkpoint: neither clause alone may fire early.
    assert _stop(999, run - 1, budget=budget, cancelled=never_cancelled) is False


def test_the_same_plan_under_the_rejection_bound_consumes_the_same_iterations() -> None:
    """The determinism contract crosses the new exit: the count is the inputs', not the host's."""
    weights = hand_tuned_weights()
    budget = SolveBudget(rejection_run=20)
    attempt = constructed_at(reference_week(), weights, budget=budget)

    runs = [improve(attempt, weights, budget=budget, cancelled=never_cancelled) for _ in range(3)]

    assert {(found.iterations, found.accepted) for found in runs} == {
        (runs[0].iterations, runs[0].accepted)
    }
