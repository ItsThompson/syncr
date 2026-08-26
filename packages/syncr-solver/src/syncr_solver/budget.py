"""How much work one solve may do, and where a caller may ask it to stop.

Three numbers and one predicate. The numbers are what keep a solve inside its two-second budget and
what make "the same input always consumes the same number of iterations" true; the predicate is
what lets a worker stop a solve whose result nobody will read.

## Where the numbers come from

Measured at **p50 1.509 ms and p99 1.709 ms on a 210-block week**, which is the size this product
is sized against. The objective is what a solve spends its time on, so the budget is a count of
evaluations rather than a wall clock:

```
  2000 ms budget / 1.5 ms an evaluation  ~=  1300 evaluations for a whole solve
  construction   210 placements x 3 scored windows each  ~=  630 at the ceiling
  local search   200 moves considered, of which the legal ones are evaluated
```

Measured end to end on a 226-block week, which is what the two numbers were chosen against rather
than derived from: construction 0.96 s, search 0.68 s, 1.64 s in all.
``python -m tests.measure_solve`` reproduces the table, so the next person to change either number
can re-measure what it was sized against. A wall-time assertion in the suite is deliberately absent,
because it would measure the machine it runs on; the suite asserts the iteration count instead.

## Why a bound cannot make a plan wrong

The window bound decides which windows are SCORED, not which are legal, and the order they are
offered in puts a candidate's own preferred windows first. So a smaller bound produces a plan the
objective likes less; it cannot produce one a rule refuses. The move bound is the same shape: the
search accepts only a strict improvement, so stopping it early leaves a plan that is worse than the
one it would have reached and better than the one it started from. The rejection run is that bound
read from the other end: it fires only after a stretch of refusals, so what it costs is at worst a
late improvement, never a rule or a placement.

## Cancellation is an optimization and nothing else

**Correctness comes from the conditional write**, which refuses a solve whose input version
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

# How many legal windows a candidate is scored in. Three rather than every gap, because a week holds
# roughly fifty and scoring them all would spend the whole budget on construction. Measured on a
# 210-block week: four windows cost 950 ms of construction and three cost 700 ms, for a plan the
# objective valued the same to four decimal places.
SCORED_WINDOWS: Final = 3

# How many local-search moves one solve considers. A move that a rule refuses costs a constraint
# check and a move that it accepts costs an objective evaluation, so this bounds the work either
# way. Measured on a 210-block week at roughly 4 ms a move, so 200 is 800 ms of the budget; the
# construction is the other 700, which leaves half a second of headroom against the two seconds.
MOVE_EVALUATIONS: Final = 200

# How often the search asks whether the caller still wants the result. Every fiftieth move, so the
# question costs nothing measurable and a cancelled solve gives up inside a few milliseconds.
CHECKPOINT_EVERY: Final = 50

# How many moves the objective may refuse in a row before the search stops and returns the plan it
# had, instead of spending the rest of its budget proving that nothing improves. Measured through
# ``python -m tests.measure_solve yield``: the longest refusal run an accepted move sits behind is
# 56 on the reference week, 91 on the dense and 38 on the saturated, so 120 keeps every acceptance
# all three weeks make today while cutting the saturated week's tail from 161 iterations to 121.
REJECTION_RUN: Final = 120


@dataclass(frozen=True, slots=True, kw_only=True)
class SolveBudget:
    """The bounded work one solve may do. Configured, so a caller can size a solve to its worker."""

    scored_windows: int = SCORED_WINDOWS
    move_evaluations: int = MOVE_EVALUATIONS
    rejection_run: int = REJECTION_RUN
    checkpoint_every: int = CHECKPOINT_EVERY


def never_cancelled() -> bool:
    """The default: nobody has asked this solve to stop."""
    return False
