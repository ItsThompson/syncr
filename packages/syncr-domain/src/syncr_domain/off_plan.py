"""Off-plan periods: the spans over which discretionary scheduling suspends.

A period is an arbitrary interval with instant precision, so Friday 14:00 to Monday 09:00
is one declaration rather than three days plus two part-days. It is not restricted to whole
days or whole weeks, and nothing here knows what an ISO week is: a period that runs across
a week boundary is ONE value, and clipping it to a week is the caller's business.

## The half-open convention, stated once

The bounds are ``[start, end)``, which :class:`~syncr_domain.intervals.Interval` already
guarantees, and every rule in this module is a consequence of it:

*A period ending Monday 09:00 leaves 09:00 itself on-plan.* The last minute it covers is
08:59, so a routine or a block starting at 09:00 is outside the span.

*Two periods that abut exactly do not overlap.* One ending Monday 09:00 and the next
starting Monday 09:00 cover no common instant, so both are declarable. This is the same
reading ``TravelOverride.overlaps`` gives dates and the reading Postgres gives a
``tstzrange`` built with the default bounds.

*A zero-length period does not exist.* ``Interval`` refuses ``start == end`` on
construction, so "off from 09:00 to 09:00" is a rejected declaration rather than a period
covering nothing.

## What this module decides, and what it does not

Three of the eleven off-plan rules are here, because all three are statements about the
span itself rather than about a subsystem that reads it:

| Rule | Where |
|---|---|
| The bounds run forward | ``Interval``, which refuses ``start >= end`` |
| Both bounds land on the quarter hour | :class:`OffPlanPeriod` |
| Periods of one tenant never overlap | :func:`require_disjoint` |
| The span leaves the denominator through the interval UNION | :mod:`syncr_domain.discretionary` |

The third is not implemented here at all, and that is the point: the union of the four
subtrahends has exactly one implementation, in :mod:`syncr_domain.discretionary`, so an
off-plan span reaches the denominator as a member of an ``IntervalSet`` and a frame span
sitting inside one is subtracted once rather than twice.

The remaining eight rules belong to the subsystems they constrain, and each is owned by a
ticket that builds that subsystem. They are listed so a reader looking for them here
learns where to look instead:

| Rule | Owner |
|---|---|
| Nothing materializes inside the span, and ``keep_frame`` decides whether routines do | ticket 25 |
| The solver places no task, habit occurrence, or Area slot inside the span | ticket 33 |
| A pin inside the span is honored as a hard constraint | ticket 33 (H11 and H12) |
| Anchors still ingest and shadows still generate, having nothing to forbid | ticket 23 |
| An anchor over a pinned block inside the span is still a conflict | ticket 39 |
| The span is excluded wholesale from reviews and from every fitter | tickets 51 and 53 |
| A majority-off-plan week is skipped by the engagement canary | ticket 54 |
| The span renders as a forbidden window, with no fourth use of hatch | ticket 35 |

The learning exclusion is unconditional and has no field. A split rule that preserved
duration signal from confirmed pinned blocks inside the span was considered and rejected:
it makes "what counts" harder to state on the Learned screen, and the signal it would
recover is a few blocks a year against a duration multiplier that needs ten to fifteen
confirmed blocks per Area.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from syncr_domain.errors import DomainError
from syncr_domain.snap import SNAP_MINUTES, is_on_snap_grid

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.intervals import Interval


class OffPlanError(DomainError):
    """An off-plan declaration breaks one of the period rules."""


class OverlappingOffPlanError(OffPlanError):
    """Two off-plan periods cover a common instant, so neither answers for it."""


@dataclass(frozen=True)
class OffPlanPeriod:
    """One declared span of time off, and what survives inside it.

    ``keep_frame`` carries two meanings and both are the user's to choose. False means no
    routine materializes inside the span, so the frame disappears with everything else.
    True means routines materialize and nothing else does, which is the quiet-week-at-home
    reading rather than the holiday-abroad one.

    ``label`` is the user's own words, rendered in the gutter beside the span. It is
    optional because a span needs no name to suspend scheduling.
    """

    interval: Interval
    keep_frame: bool = False
    label: str | None = None

    def __post_init__(self) -> None:
        unsnapped = [
            moment
            for moment in (self.interval.start, self.interval.end)
            if not is_on_snap_grid(moment)
        ]
        if unsnapped:
            stated = ", ".join(str(moment) for moment in unsnapped)
            raise OffPlanError(
                f"an off-plan period's bounds land on the {SNAP_MINUTES}-minute grid, "
                f"and these do not: {stated}"
            )

    def overlaps(self, other: OffPlanPeriod) -> bool:
        """Whether both cover a common instant. Two that abut exactly do not."""
        return self.interval.overlaps(other.interval)


def require_disjoint(periods: Sequence[OffPlanPeriod]) -> None:
    """Raise unless no two of ``periods`` cover a common instant.

    Stated over the whole set rather than over one candidate, so the caller passes the
    periods it would end up storing and this answers for the result rather than for the
    request. A declaration that would overlap is refused; a period being edited is compared
    against the others by leaving its stored self out of the sequence.

    Adjacent pairs of the start-ordered sequence are the only ones compared, and that is
    complete rather than a shortcut, by the contrapositive: if NO adjacent pair overlaps then
    ``end[i] <= start[i + 1]`` for every ``i``, and starts are non-decreasing, so
    ``end[i] <= start[j]`` for every ``j > i`` and no pair overlaps at all. It is NOT true
    that an overlapping pair is always adjacent, which is the tempting reason to give:
    ``[0h, 100h)``, ``[1h, 2h)``, ``[50h, 60h)`` sorts in that order, and the third overlaps
    the first without overlapping the second.
    """
    ordered = sorted(periods, key=lambda period: period.interval)
    for earlier, later in pairwise(ordered):
        if earlier.overlaps(later):
            raise OverlappingOffPlanError(
                f"off-plan periods [{earlier.interval.start}, {earlier.interval.end}) and "
                f"[{later.interval.start}, {later.interval.end}) cover a common instant"
            )
