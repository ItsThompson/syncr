"""How much work one solve may do, and where a caller may ask it to stop.

Two numbers and one predicate. The numbers are what keep a solve inside its two-second budget and
what make "the same input always consumes the same number of iterations" true; the predicate is
what lets a worker stop a solve whose result nobody will read.

## Where the numbers come from

Ticket 34 measured the objective at **p50 1.509 ms and p99 1.709 ms on a 210-block week**, which is
the size this product is sized against. The objective is what a solve spends its time on, so the
budget is a count of evaluations rather than a wall clock:

```
  2000 ms budget / 1.5 ms an evaluation  ~=  1300 evaluations for a whole solve
  construction   ~210 placements x 4 scored windows each  ~=  840 at the ceiling
  local search   400 moves considered, of which the legal ones are evaluated
```

Construction reaches its ceiling only where every candidate has four legal windows, and the plan
is smaller than 210 blocks for most of the run, so the measured figure is well inside the budget.
The measurement is in the changeset rather than asserted in the suite: a wall-time assertion in a
test measures the machine it runs on.

## Why a bound cannot make a plan wrong

The window bound decides which windows are SCORED, not which are legal, and the order they are
offered in puts a candidate's own preferred windows first. So a smaller bound produces a plan the
objective likes less; it cannot produce one a rule refuses. The move bound is the same shape: the
search accepts only a strict improvement, so stopping it early leaves a plan that is worse than the
one it would have reached and better than the one it started from.

## Cancellation is an optimization and nothing else

**Correctness comes from ticket 40's conditional write**, which refuses a solve whose input version
has moved. A cancelled solve stops early and returns the plan it had, and the coordinator discards
it; a solve that misses its checkpoint finishes and is discarded just the same. So the predicate is
allowed to answer differently between two calls without making a solve non-deterministic in any
sense a stored plan can observe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

type Cancelled = Callable[[], bool]
"""Whether the caller has stopped wanting this solve's result."""

# How many legal windows a candidate is scored in. Four rather than every gap, because a week holds
# roughly fifty and scoring them all would spend the whole budget on construction.
SCORED_WINDOWS: Final = 4

# How many local-search moves one solve considers. A move that a rule refuses costs a constraint
# check and a move that it accepts costs an objective evaluation, so this bounds the work either
# way.
MOVE_EVALUATIONS: Final = 400

# How often the search asks whether the caller still wants the result. Every fiftieth move, so the
# question costs nothing measurable and a cancelled solve gives up inside a few milliseconds.
CHECKPOINT_EVERY: Final = 50


@dataclass(frozen=True, slots=True, kw_only=True)
class SolveBudget:
    """The bounded work one solve may do. Configured, so a caller can size a solve to its worker."""

    scored_windows: int = SCORED_WINDOWS
    move_evaluations: int = MOVE_EVALUATIONS
    checkpoint_every: int = CHECKPOINT_EVERY


def never_cancelled() -> bool:
    """The default: nobody has asked this solve to stop."""
    return False
