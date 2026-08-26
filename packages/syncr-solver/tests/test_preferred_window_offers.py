"""The starts a candidate is offered inside one window, and what they let the objective price.

A window is offered with its own first grid point and with the first grid point at or after each
of the candidate's OWN applicable preferred windows that falls inside it. Without those starts, a
declared window strictly inside a roomy gap is never offered anywhere -- the gap is offered at
wherever it opens -- so no rule ever prices the window and nothing lands in it.

Every figure asserted here is bounded by declared windows rather than by the grid: a week that
declared a hundred windows would add a hundred offers, and a finer grid would add none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef
from syncr_domain.preferences import PreferenceStrength
from syncr_domain.reasons import Bound
from syncr_solver.attempt import Attempt, Placed
from syncr_solver.candidates import Candidate
from syncr_solver.moves import RELOCATE, moves
from syncr_solver.offering import offers_in
from syncr_solver.preferred import ResolvedPreferences
from syncr_solver.state import Sizing
from tests.materialized_weeks import (
    FITNESS,
    a_block,
    a_frame_entry,
    an_area_budget,
    at,
    between,
    inputs,
)
from tests.objective_weeks import (
    A_HABIT,
    a_preference,
    an_occurrence,
)
from tests.solve_weeks import a_week, solved

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.intervals import Interval
    from syncr_solver.inputs import SolveInputs

WEDNESDAY = 2


def a_gym_candidate() -> Candidate:
    """One fixed-hour Fitness occurrence, the candidate every offer below is taken over."""
    return Candidate(
        binding=BindingRef.for_habit(A_HABIT, index=0),
        area_id=FITNESS,
        title="Gym",
        sizing=Sizing(whole_minutes=60, min_chunk_minutes=60, splittable=False),
        min_minutes=60,
        max_minutes=60,
        remaining_minutes=60,
        deadline=None,
        stale_minutes=0,
        floor_shortfall_minutes=0,
        bound=Bound(source=BindingSource.FIXED, selected="Gym"),
    )


def preferences_of(windows: tuple[Interval, ...]) -> ResolvedPreferences:
    """One strong Fitness preference over these windows, resolved the way a solve receives it."""
    return ResolvedPreferences(
        (a_preference(windows=windows, strength=PreferenceStrength.STRONG),)
    )


def offered_starts(week: SolveInputs, declared: tuple[Interval, ...]) -> list[datetime]:
    """Every start the candidate is offered across the week's gaps, in the order offered."""
    attempt = Attempt.of(week)
    preferences = preferences_of(declared)
    return [
        offer.interval.start
        for gap in attempt.gaps()
        for offer in offers_in(a_gym_candidate(), gap, attempt=attempt, preferences=preferences)
    ]


def the_measurement_week() -> SolveInputs:
    """One 60-minute Fitness occurrence whose strong window is Wednesday 13:00, and nothing else.

    No anchors and no template entries hold the week; the frame is sleep alone, so Wednesday
    13:00 sits strictly inside the gap that opens Tuesday morning. Nothing structural places the
    occurrence in its window: only the window's own start can.
    """
    return a_week(
        frame=tuple(a_frame_entry(day=day) for day in range(7)),
        habit_occurrences=(an_occurrence(minutes=60, title="Gym"),),
        areas=(an_area_budget(target_minutes=60, floor_minutes=0),),
        preferences=(
            a_preference(
                windows=(between(13, 14, day=WEDNESDAY),),
                strength=PreferenceStrength.STRONG,
            ),
        ),
    )


# --------------------------------------------------------------------------------------
# The added starts
# --------------------------------------------------------------------------------------


def test_a_window_strictly_inside_a_gap_is_offered_at_its_own_start() -> None:
    """Thursday 13:00 sits mid-afternoon inside the week's one roomy gap, and it is offered."""
    starts = offered_starts(inputs(), (between(13, 14, day=3),))

    assert at(13, day=3) in starts


def test_the_offers_still_include_each_gap_s_own_start() -> None:
    """The added starts are IN ADDITION TO the first grid point of each window."""
    week = inputs()
    starts = offered_starts(week, (between(13, 14, day=3),))

    assert {gap.start for gap in Attempt.of(week).gaps()} <= set(starts)


def test_a_window_outside_the_gap_adds_nothing_to_it() -> None:
    """A morning preference never drops a start into an afternoon gap, and vice versa."""
    # NOW is Wednesday 09:00, so the week's one gap opens there: Monday's window is outside it.
    starts = offered_starts(inputs(), (between(6, 7, day=0),))

    assert starts == [at(9, day=WEDNESDAY)]


def test_a_window_opening_on_the_gap_s_own_start_is_not_offered_twice() -> None:
    """The deduplication: a preference that opens where the gap opens adds no second offer."""
    week = inputs(now=at(13, day=3))
    starts = offered_starts(week, (between(13, 14, day=3),))

    assert starts == [at(13, day=3)]


# --------------------------------------------------------------------------------------
# The bound
# --------------------------------------------------------------------------------------


def test_the_added_offers_are_bounded_by_the_declared_windows() -> None:
    """Five declared windows buy five extra starts whatever the grid holds.

    The week's single gap spans days of free time -- thousands of fifteen-minute steps -- so an
    unbounded reading of "the starts inside the window" would grow with the grid. It grows with
    the declaration instead, which is what this asserts over the public generator.
    """
    declared = tuple(between(9 + day, 10 + day, day=day) for day in range(2, 7))
    starts = offered_starts(inputs(), declared)

    assert len(starts) <= 1 + len(declared)
    assert len(set(starts)) == 1 + len(declared)


# --------------------------------------------------------------------------------------
# The relocation move
# --------------------------------------------------------------------------------------


def test_a_relocation_reaches_a_declared_window_inside_a_roomy_gap() -> None:
    """A block parked at a gap's opening is offered its own window further into the same gap."""
    held = a_block(binding=BindingRef.for_habit(A_HABIT, index=0), interval=between(9, 10))
    attempt = Attempt.of(
        the_measurement_week(),
        placements=(
            Placed.of(
                held,
                sizing=Sizing(whole_minutes=60, min_chunk_minutes=60, splittable=False),
                chosen=True,
            ),
        ),
    )
    relocations = [
        move.attempt.placements[-1].block.interval.start
        for move in moves(attempt, preferences_of((between(13, 14),)))
        if move.kind == RELOCATE
    ]
    assert at(13) in relocations


# --------------------------------------------------------------------------------------
# The measurement: a solve lands the occurrence in its window
# --------------------------------------------------------------------------------------


def test_one_fitness_occurrence_lands_in_its_strong_wednesday_window() -> None:
    """One occurrence, one strong window, and nothing else that could put it there.

    Offered only at gap starts, the occurrence cannot reach its window at any price; offered at
    the window's own start, the misfit term prices the two apart and the window wins.
    """
    document = solved(the_measurement_week()).document
    gym = [block for block in document.blocks if block.title == "Gym"]

    assert len(gym) == 1
    assert gym[0].interval == between(13, 14, day=WEDNESDAY)


def test_solving_the_measurement_week_twice_yields_the_same_plan() -> None:
    """Twice the same week, twice the same plan: the added starts keep the loop deterministic."""
    week = the_measurement_week()

    assert solved(week).document.blocks == solved(week).document.blocks
