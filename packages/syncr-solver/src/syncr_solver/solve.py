"""``solve``: one week's inputs plus one weight set into a plan, a breakdown, and a verdict.

The second public entry point. It is deterministic, pure in everything a stored plan can observe,
and it performs no lookup and no I/O: every figure it needs arrives on ``SolveInputs``, and the only
effects it has besides its return value are the four metric families it observes.

## Five phases over one accumulating value

```
1  MATERIALIZE   the frame, the commitments, the buffers, the day's shape, the windows
   INHERIT       the pins and the blocks that have begun, which the space also holds
2  BIND          content into the slots whose time the template already fixed
3  FILL          the due occurrences and the remaining task work, into what is left
4  IMPROVE       bounded local search, accepting only a strict objective improvement
5  VERDICT       the probe's shortfalls, plus the packing failures the attempt found
```

Phase 1 is ``materialize``, unchanged and shared: it is phase 1 of every solve forever and the plan
of last resort when a solve fails terminally, which is why it is not scaffolding a later slice
deletes. Its refusals are carried into this log rather than re-derived, because the check that
already knew is the one that recorded them.

## Determinism, and where each mechanism lives

| Mechanism | Where |
|---|---|
| a total order on candidates | :mod:`syncr_solver.tiebreak`, ending in the whole of a binding |
| a deterministic order on windows and moves | `offering.py` and `moves.py` |
| only strict improvements accepted | :mod:`syncr_solver.search`: no temperature, no randomness |
| a bounded iteration budget | :mod:`syncr_solver.budget`, configured and counted |

``SolveInputs.seed`` is read by nothing here, and that is the stronger property rather than an
omission: the comparator breaks every tie, so no figure a document carries can depend on a seed.

## No language model participates in placement

Nothing in this package imports an ML library, and a test reads that from the source rather than
from the lockfile. The choice at every step is a comparator, a constraint check, or an arithmetic
comparison of two objective totals.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_domain.gaps import EmptySlotReason
from syncr_solver.attempt import Attempt
from syncr_solver.binding import bind_slots
from syncr_solver.budget import SolveBudget, never_cancelled
from syncr_solver.filling import fill_gaps
from syncr_solver.inheritance import inherited
from syncr_solver.materialize import derive
from syncr_solver.metrics import (
    SOLVE_BLOCKS_PLACED,
    SOLVE_DURATION,
    SOLVE_EMPTY_SLOTS,
    SOLVE_ITERATIONS,
    MaterializeCause,
    SolveOutcome,
)
from syncr_solver.search import improve
from syncr_solver.verdicts import verdict_of

if TYPE_CHECKING:
    from syncr_domain.feasibility import Verdict
    from syncr_domain.plan import PlanDocument
    from syncr_solver.budget import Cancelled
    from syncr_solver.constraints import BlockedCandidate
    from syncr_solver.inputs import SolveInputs
    from syncr_solver.objective import ObjectiveBreakdown
    from syncr_solver.search import Improved
    from syncr_solver.weights import WeightSet


@dataclass(frozen=True, slots=True, kw_only=True)
class SolveResult:
    """What one solve produced: the plan, what it costs, whether it works, and what it refused.

    ``blocked_log`` is bounded by two rows per binding, which is the clause budget's own figure for
    rejected windows, so a document appended forever cannot grow with the number of windows a solve
    tried.

    The breakdown and the log are carried rather than recomputed, because a reason record is a
    projection of what the solve decided: reconstructing either would mean re-running the checks and
    the arithmetic that already knew.
    """

    document: PlanDocument
    objective_breakdown: ObjectiveBreakdown
    verdict: Verdict
    blocked_log: tuple[BlockedCandidate, ...]
    # How many local-search moves this solve considered, against the budget it was given. Carried
    # because the same inputs consume the same number, so a change in it is a change in behaviour.
    iterations: int


def solve(
    inputs: SolveInputs,
    weights: WeightSet,
    *,
    budget: SolveBudget | None = None,
    cancelled: Cancelled = never_cancelled,
) -> SolveResult:
    """The plan ``inputs`` and ``weights`` produce, and the verdict the attempt is authoritative on.

    ``budget`` is configured rather than fixed so a caller can size a solve to its worker, and it
    cannot make a plan illegal: it bounds how many legal windows are scored and how many moves are
    considered, and the rules judge every placement whatever the budget was.

    ``cancelled`` is an optimization only. Correctness comes from the conditional write in the solve
    coordinator, which refuses a plan whose input version has moved, so a solve that stops early and
    one that finishes are both discarded when nobody wants the result.
    """
    limits = SolveBudget() if budget is None else budget
    with SOLVE_DURATION.labels(outcome=SolveOutcome.SUCCEEDED.value).time():
        materialization = derive(inputs, cause=MaterializeCause.PHASE1)
        attempt = Attempt.of(
            inputs, placements=inherited(inputs, materialization.document.blocks)
        ).with_blocked(materialization.blocked)
        attempt = fill_gaps(bind_slots(attempt), weights, budget=limits)
        # The checkpoint after construction, expressed as a search with no moves to spend: the plan
        # is still evaluated, because a result carries what its own plan costs.
        spent = replace(limits, move_evaluations=0) if cancelled() else limits
        return _result(improve(attempt, weights, budget=spent, cancelled=cancelled))


def _result(found: Improved) -> SolveResult:
    """The result, with the three figures this package publishes observed once each.

    The breakdown is the search's own rather than a fresh evaluation, because it is the cost of the
    plan being returned and computing it again would be the same arithmetic on the same document.
    """
    document = found.attempt.document()
    SOLVE_BLOCKS_PLACED.observe(len(document.blocks))
    SOLVE_ITERATIONS.observe(found.iterations)
    for reason in EmptySlotReason:
        SOLVE_EMPTY_SLOTS.labels(reason=reason.value).observe(
            sum(1 for slot in document.empty_slots if slot.reason is reason)
        )
    return SolveResult(
        document=document,
        objective_breakdown=found.breakdown,
        verdict=verdict_of(found.attempt),
        blocked_log=found.attempt.log.rows,
        iterations=found.iterations,
    )
