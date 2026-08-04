"""Which weeks a span reaches into, and therefore which weeks a mutation invalidates.

An off-plan period changes the discretionary-time denominator of every week it touches, so
declaring, editing, or removing one bumps the week input version of each of those weeks: a
running solve for such a week read a denominator that no longer holds, and its conditional
write is what the bump makes fail.

**The range is the weeks the span TOUCHES, with no floor at the current week.** That differs
from a budget or a zone change deliberately. Those have no end date: they govern every week
from now on, so their range is open-ended, it has to be floored at the current week to avoid
re-deriving a past week that keeps the inputs its approved revision was computed with, and the
four steps that build such a range have one implementation every mutation of that shape shares.
An off-plan span is the other shape, bounded at both ends like a travel override's dates: it
names a bounded set of weeks, and a past week inside it genuinely reports a different
denominator than it did before the span was declared, so flooring it would leave that week
reporting a figure nothing invalidated. Only weeks with a version row are bumped in any case,
so a past week nothing has planned is never touched.

**The last week is the week holding the last instant the span COVERS, not the week holding
``end``.** The bounds are half-open, so a period ending at a Monday's local midnight ends
where the next week begins and reaches nothing inside it. Reading ``end``'s own week would bump
one week too many at exactly the boundary a user is most likely to declare.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.snap import SNAP
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneId


def weeks_touching(interval: Interval, *, home_zone: ZoneId) -> WeekRange:
    """Every ISO week ``interval`` reaches into, as one contiguous range.

    The zone is the HOME zone, matching every other week derivation in the product: an ISO
    week is a pair of local Mondays, and resolving which one a span falls inside in a travel
    override's zone would make the answer depend on which day of the trip is being asked
    about.
    """
    # The final quarter hour the span covers. Clamped to the start so a span shorter than one
    # quarter hour, which the grid rule forbids and this function does not require, still names
    # an instant inside itself rather than one before it.
    last_covered = max(interval.start, interval.end - SNAP)
    return WeekRange(
        first=IsoWeek.containing(local_date(interval.start, home_zone)),
        last=IsoWeek.containing(local_date(last_covered, home_zone)),
    )
