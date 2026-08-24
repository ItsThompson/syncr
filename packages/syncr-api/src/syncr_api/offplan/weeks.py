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

from datetime import UTC
from typing import TYPE_CHECKING

from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_domain.snap import SNAP
from syncr_domain.weeks import IsoWeek, week_span

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile


def weeks_touching(interval: Interval, *, profile: ZoneProfile) -> WeekRange:
    """Every ISO week ``interval`` reaches into, as one contiguous range.

    Which weeks those are is asked of the weeks themselves: each week's ``week_span``, built
    from the whole profile, is bounded by the ACTIVE zone on its two Mondays, so the range
    names every week whose span overlaps the interval and no other. Resolving the bounds in
    the HOME zone instead answers where the span sits among home-zone dates, which under a
    travel override names a week beside the one whose denominator actually changed.
    """
    # The final quarter hour the span covers. Clamped to the start so a span shorter than one
    # quarter hour, which the grid rule forbids and this function does not require, still names
    # an instant inside itself rather than one before it.
    last_covered = max(interval.start, interval.end - SNAP)
    return WeekRange(
        first=_week_holding(interval.start, profile),
        last=_week_holding(last_covered, profile),
    )


def _week_holding(instant: datetime, profile: ZoneProfile) -> IsoWeek:
    """The one ISO week whose span contains ``instant``.

    Consecutive spans abut -- a week ends exactly where its successor begins, both being the
    following Monday's local midnight resolved through the same profile -- so the spans tile
    the timeline and every instant belongs to exactly one of them. The walk starts from the
    UTC date, which no zone's local date can disagree with by more than a day, and corrects
    in whichever direction the real bounds fall on the other side.
    """
    week = IsoWeek.containing(instant.astimezone(UTC).date())
    while week_span(week, profile).end <= instant:
        week = week.following()
    while week_span(week, profile).start > instant:
        week = week.preceding()
    return week
