"""How long an elastic occurrence is placed for, and the three things that bound the choice.

``Habit.duration`` may be elastic, with a minimum and a maximum. **Nothing in the objective
rewards a longer block on its own**, so the selection rule has to be stated or two implementations
would produce different plans from the same inputs, which the determinism property cannot catch
because it only compares a build against itself.

```
The LARGEST duration in [min, max] that:
  1. fits the window, after H1 to H14;
  2. does not push its Area past `target_minutes` for the week;
  3. does not push its Area past `max_per_day_minutes` for that day.

If no size satisfies all three it takes `min`.
If `min` does not fit either, the occurrence is not placed and the gap is left unallocated.
```

Largest rather than smallest, because an elastic habit exists so the user gets as much of it as
the week affords: ``Leetcode`` at 25, 45 and 90 minutes in one real week is the observation the
rule comes from. Bounded by the Area's TARGET rather than its floor, because one elastic habit
sized to a floor would consume its Area's whole remainder and starve every task in it. And what
makes the choice converge is ``budget_deviation``: sizing up closes an Area's under-target gap, so
the objective already prefers it and this rule only makes the preference deterministic.

**The third bound is H8, and it is deliberately not restated here.** The rule names a daily cap
and so does the hard-constraint table, and every placement passes through the checker whatever
chose its length, so H8 answers condition 3 exactly: over the local dates the placement reaches,
in each date's own share, which is arithmetic this module has no window to do. What is stated here
is condition 2, the weekly target, which no hard rule reads because a target is a reporting figure
rather than a reservation.

## Every size lands on the grid, and that falls out rather than being enforced

``Duration`` refuses a bound that is not a multiple of the fifteen-minute step, so stepping from
the minimum to the maximum in one step at a time visits only lengths a block can hold. H14 checks
the bounds anyway, for the same reason the cap is checked twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.snap import SNAP_MINUTES

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_solver.attempt import Attempt
    from syncr_solver.candidates import Candidate


def sizes_for(candidate: Candidate, attempt: Attempt) -> Iterator[int]:
    """Every length this candidate may be placed at, largest first, then the minimum.

    The minimum is yielded last as well as in its own place in the descending run, which is the
    "if no size satisfies all three it takes ``min``" branch: a caller walks the sequence and takes
    the first length the checker accepts, so the fallback is expressed as the last thing offered
    rather than as a second call. A minimum that does not fit is refused by the checker, and the
    gap is left unallocated because nothing else was offered.

    A candidate whose length the elastic rule does not choose yields its maximum and nothing else:
    a task's length is what the packer can fit, and the caller narrows it to the window.
    """
    if not candidate.sizes_within_a_range:
        yield candidate.max_minutes
        return
    allowed = [
        minutes
        for minutes in _descending(candidate)
        if _within_the_area_target(candidate, attempt, minutes)
    ]
    yield from allowed
    if candidate.min_minutes not in allowed:
        yield candidate.min_minutes


def _descending(candidate: Candidate) -> Iterator[int]:
    """The lengths the range holds, largest first, one grid step apart."""
    minutes = candidate.max_minutes
    while minutes >= candidate.min_minutes:
        yield minutes
        minutes -= SNAP_MINUTES


def _within_the_area_target(candidate: Candidate, attempt: Attempt, minutes: int) -> bool:
    """Whether this length leaves the Area inside the target it is aiming at for the week.

    Measured over what the attempt holds rather than over ``AreaBudget.placed_minutes``: that figure
    counts the placements this plan's own blocks already are, so adding the two would charge one
    Area for its week twice, which is the fault class this epic has found at five sites.

    An Area with no target states nothing for a length to pass, so every length is allowed and the
    checker is what bounds them.
    """
    area = next((held for held in attempt.state.areas if held.area_id == candidate.area_id), None)
    if area is None or area.target_minutes <= 0:
        return True
    return attempt.spans_in(candidate.area_id).total_minutes() + minutes <= area.target_minutes
