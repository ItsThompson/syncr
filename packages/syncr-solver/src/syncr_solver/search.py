"""Phase 4: improving a constructed plan by bounded local search over the objective.

Greedy construction places each demand where the objective liked it best among the windows it
scored. That is a local decision taken in one order, so the plan it produces is rarely the best one
reachable: a block placed early takes a window a later one needed more. This phase is what recovers
those, one strictly improving move at a time.

## Only a strict improvement is accepted, which is the whole design

```
accept  total(candidate) < total(current)
```

The consequences are what a temperature schedule and a random restart exist to buy, and they come
free from the inequality:

| Property | Because |
|---|---|
| monotonic | every accepted move lowers one number, so the plan never gets worse |
| terminating | the objective is bounded below by zero and each step strictly descends |
| deterministic | no temperature, no annealing, no seed, and no randomness anywhere |
| reproducible | the move generator's order is a function of the plan |

Strict rather than "no worse", and that is load-bearing rather than pedantic: accepting an equal
plan would let two moves that undo each other alternate forever inside the budget.

## First improvement rather than best improvement

The search takes the first move that improves the plan and starts the pass again, rather than
scoring every move and taking the best. Two reasons, and both are about the budget: the best-move
pass costs one objective evaluation per move whether or not the plan improves, and a plan that has
just changed makes the rest of that pass's scores stale anyway.

## The iteration count is part of the contract

A move CONSIDERED is an iteration, whether the rules refused it or the objective did. That is what
the budget bounds and what ``syncr_solve_iterations`` reports, and because the generator's order is
a function of the plan, the same inputs consume the same number of iterations on every run and on
every machine.

## A run of rejections ends the search too

After an acceptance the search restarts its pass, and on a plan near its optimum almost everything
the remaining pass offers is refused: measured on the saturated week, 161 of the budget's 200
iterations went to proving that nothing improves. So the search also stops once the objective has
refused ``budget.rejection_run`` moves since the last acceptance, and returns the plan it had. The
bound sits above the longest refusal run any accepted move sat behind on the weeks
``python -m tests.measure_solve yield`` reports, which is what makes it a measured number rather
than a fraction of the move budget: within one descent it can cost only an improvement no measured
week ever made.

The stop bounds wasted work and nothing else. Every plan it returns is one a move strictly improved
upon, so monotonicity, termination and determinism are untouched, and the iteration count stays a
function of the inputs alone.

## Cancellation is an optimization only

Checked every ``checkpoint_every`` iterations. **Correctness comes from the conditional write**,
which refuses to store a plan whose input version has moved: a solve that misses its checkpoint
finishes and is discarded exactly like one that stops at it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_solver.moves import moves
from syncr_solver.objective import evaluate
from syncr_solver.preferred import ResolvedPreferences

if TYPE_CHECKING:
    from syncr_solver.attempt import Attempt
    from syncr_solver.budget import Cancelled, SolveBudget
    from syncr_solver.objective import ObjectiveBreakdown
    from syncr_solver.weights import WeightSet


@dataclass(frozen=True, slots=True, kw_only=True)
class Improved:
    """What the search left behind: the plan, its cost, and what it spent getting there."""

    attempt: Attempt
    breakdown: ObjectiveBreakdown
    iterations: int
    accepted: int


def improve(
    attempt: Attempt,
    weights: WeightSet,
    *,
    budget: SolveBudget,
    cancelled: Cancelled,
) -> Improved:
    """The best plan a bounded descent from ``attempt`` reaches, and the breakdown it costs.

    The breakdown is returned rather than recomputed by the caller, because it is the plan's own
    cost under this weight set and evaluating it twice would be the same arithmetic on the same
    document.
    """
    preferences = ResolvedPreferences(attempt.inputs.preferences)
    current = attempt
    breakdown = evaluate(current.document(), inputs=current.inputs, weights=weights)
    total = breakdown.total()
    iterations = 0
    accepted = 0
    rejections = 0
    improving = True
    while improving and iterations < budget.move_evaluations:
        improving = False
        for move in moves(current, preferences):
            iterations += 1
            if _stop(iterations, rejections, budget=budget, cancelled=cancelled):
                return Improved(
                    attempt=current,
                    breakdown=breakdown,
                    iterations=iterations,
                    accepted=accepted,
                )
            found = evaluate(move.attempt.document(), inputs=current.inputs, weights=weights)
            if found.total() >= total:
                rejections += 1
                continue
            current, breakdown, total = move.attempt, found, found.total()
            accepted += 1
            rejections = 0
            improving = True
            break
    return Improved(attempt=current, breakdown=breakdown, iterations=iterations, accepted=accepted)


def _stop(iterations: int, rejections: int, *, budget: SolveBudget, cancelled: Cancelled) -> bool:
    """Whether the budget is spent, the last acceptances are long gone, or the caller moved on.

    All three are one question because a caller reads one answer: the search stops and returns the
    plan it had. Which of the three stopped it is not a fact the plan carries, because a plan
    produced under a smaller budget is a legal plan and not a partial one.
    """
    if iterations >= budget.move_evaluations:
        return True
    if rejections >= budget.rejection_run:
        return True
    return iterations % budget.checkpoint_every == 0 and cancelled()
