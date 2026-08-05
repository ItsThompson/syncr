"""Phase 3: placing the cadence items and the remaining task work into what is left of the week.

The gaps are ``span.subtract(union(everything fixed and placed))``, and every due occurrence and
every task with work outstanding is offered into them in tie-break order. A refusal is recorded with
its rule and its window; an acceptance is scored with the objective and the best is kept.

## One round places one piece, and the ordering is taken again every round

A task's remaining work shrinks as pieces of it are placed and an Area's unmet floor shrinks as
content lands in it, so the order candidates are offered in is a function of the week as it stands
rather than of the week as it arrived. Taking the ordering once would offer a task four times before
looking at the Area that had fallen furthest behind.

Progress is guaranteed because a round either places something, which reduces what is left to place,
or gives up on one candidate, which reduces the candidates. So the loop terminates on the inputs
rather than on a step count, and it consumes the same number of rounds for the same inputs.

## Why only a bounded number of windows are scored, and why that cannot make a plan wrong

Scoring is a whole-plan objective evaluation, measured at 1.5 ms on the week this product is sized
against, so scoring every gap for every candidate would spend a solve's whole budget on
construction. The bound is on how many LEGAL windows are scored, the illegal ones cost a constraint
check and are recorded, and the windows are offered with the candidate's own preferred ones first.
A tighter bound therefore produces a plan the objective likes less rather than one a rule refuses.

## A piece the rules refuse is the packing failure the verdict names

A task whose minimum chunk exceeds every remaining gap is offered the largest piece each gap can
hold and refused by H7 every time, so the log ends up holding the rule and the window for it. That
is what lets phase 5 report a packing failure rather than an absence nobody recorded, and it is the
transition the probe structurally cannot find.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_solver.candidates import candidates_for
from syncr_solver.offering import Scored, offers_in, refusal_of, scored, windows_for
from syncr_solver.preferred import ResolvedPreferences

if TYPE_CHECKING:
    from syncr_domain.identity import BindingRef
    from syncr_solver.attempt import Attempt
    from syncr_solver.budget import SolveBudget
    from syncr_solver.candidates import Candidate
    from syncr_solver.constraints import BlockedCandidate
    from syncr_solver.weights import WeightSet


def fill_gaps(attempt: Attempt, weights: WeightSet, *, budget: SolveBudget) -> Attempt:
    """Every due occurrence and every task with work left, placed into the gaps that remain.

    ``exhausted`` holds the candidates no gap can take. It only ever grows, because the gaps only
    ever shrink: a candidate the week could not hold at one round cannot be held at a later one, so
    re-offering it would spend the budget proving the same thing again.
    """
    preferences = ResolvedPreferences(attempt.inputs.preferences)
    exhausted: set[BindingRef] = set()
    while True:
        chosen = _next_candidate(attempt, exhausted)
        if chosen is None:
            return attempt
        attempt, placed = _place(chosen, attempt, weights, budget=budget, preferences=preferences)
        if not placed:
            exhausted.add(chosen.binding)


def _next_candidate(attempt: Attempt, exhausted: set[BindingRef]) -> Candidate | None:
    """The highest-ordered demand still worth offering, or nothing because there is none left."""
    return next(
        (
            candidate
            for candidate in candidates_for(
                attempt.inputs,
                placed_minutes=attempt.placed_minutes(),
                floor_shortfalls=attempt.floor_shortfalls(),
            )
            if candidate.binding not in exhausted
        ),
        None,
    )


def _place(
    candidate: Candidate,
    attempt: Attempt,
    weights: WeightSet,
    *,
    budget: SolveBudget,
    preferences: ResolvedPreferences,
) -> tuple[Attempt, bool]:
    """One piece of this candidate at the best-scoring legal window, and every refusal on the way.

    The refusals are recorded whether or not anything was placed, which is the half that matters
    for a candidate nothing could hold: the log is where the rule and the window that refused it
    survive, and a candidate that vanished without a row would be a gap in the plan with no reason.

    Within one window the offers run longest first, so the first the rules accept is the largest
    length that fits. That is the elastic rule's own first condition, and for a task it is the
    largest piece of what is left.
    """
    refusals: list[BlockedCandidate] = []
    best: Scored | None = None
    scored_windows = 0
    for window in windows_for(candidate, attempt.gaps(), preferences):
        if scored_windows >= budget.scored_windows:
            break
        for offer in offers_in(candidate, window, attempt=attempt):
            refusal = refusal_of(offer, attempt)
            if refusal is not None:
                refusals.append(refusal)
                continue
            found = scored(offer, attempt, weights)
            scored_windows += 1
            if best is None or found.total < best.total:
                best = found
            break
    attempt = attempt.with_blocked(refusals)
    if best is None:
        return (attempt, False)
    return (attempt.adding(best.offer.placed), True)
