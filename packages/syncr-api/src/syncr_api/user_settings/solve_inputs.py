"""Which weeks a zone change invalidates, and who is told about it.

A home-zone change or a travel override changes what ``week_span`` and ``active_zone``
answer, so it changes the inputs a solve reads. The week input version is the single
serialization point for that: a mutation bumps it, a running solve's conditional write
sees the mismatch and is superseded, and a follow-up solve reads the new zone.

**Past weeks are never bumped.** An approved revision is immutable and keeps the span it
was computed with, so re-deriving a past week would change history rather than the plan.
The floor is therefore the week holding the current local date, not the date the range
starts on.

The range a travel override affects reaches one day BEFORE its first date, because a
week's span ends at the following Monday's local midnight: an override beginning on a
Monday moves the end of the week before it. Taking the day before covers that without a
special case, and changes nothing when the range starts on any other weekday.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from syncr_common.logging import get_logger
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import date

    from syncr_api.core.clock import Clock
    from syncr_api.plans.versions import WeekInputVersionRepository

_ONE_DAY = timedelta(days=1)

_log = get_logger("syncr.user_settings")


@dataclass(frozen=True, slots=True)
class WeekRange:
    """The weeks one mutation invalidated: ``first`` onwards, up to ``last``.

    ``last`` is ``None`` for a change with no end date, which is what a home-zone change
    is: it governs every week the travel overrides do not cover, forever.
    """

    first: IsoWeek
    last: IsoWeek | None

    def __post_init__(self) -> None:
        if self.last is not None and self.last < self.first:
            message = f"a week range needs first <= last, got {self.first} to {self.last}"
            raise ValueError(message)

    def covers(self, week: IsoWeek) -> bool:
        """Whether ``week`` is inside this range."""
        return self.first <= week and (self.last is None or week <= self.last)


class WeekInputVersions(Protocol):
    """The week input version counter, as this module needs it.

    Declared here rather than imported so the settings service depends on the operation it
    performs rather than on plan storage's repository, and so a service test can record
    what would have been bumped instead of reaching a database.
    """

    async def bump(self, weeks: WeekRange) -> None:
        """Bump the input version of every tracked week in ``weeks``.

        A week with no version row is not tracked: it has no plan and no running solve to
        invalidate, and the write guard treats a missing row as a mismatch, so creating one
        here would buy nothing.
        """
        ...


class TrackedWeekInputVersions:
    """The counter, over plan storage's version rows.

    Enumerates before it writes, because the range a home-zone change invalidates is
    open-ended and only the rows say which of those weeks anything has planned. Each bump
    is plan storage's own single statement, so two mutations landing together cannot read
    one value and write the same successor.
    """

    def __init__(self, versions: WeekInputVersionRepository, clock: Clock) -> None:
        self._versions = versions
        self._clock = clock

    async def bump(self, weeks: WeekRange) -> None:
        at = self._clock()
        tracked = await self._versions.tracked_weeks(weeks.first, weeks.last)
        for week in tracked:
            await self._versions.bump(week, at=at)
        _log.info(
            "user_settings.input_version.bumped",
            first_week=str(weeks.first),
            last_week=str(weeks.last) if weeks.last is not None else None,
            weeks_bumped=len(tracked),
        )


def weeks_from(today: date) -> WeekRange:
    """Every week from the current one onwards: what a home-zone change invalidates."""
    return WeekRange(first=IsoWeek.containing(today), last=None)


def weeks_covering(start_date: date, end_date: date, *, today: date) -> WeekRange | None:
    """The future weeks a travel override over ``start_date..end_date`` invalidates.

    ``None`` when the whole range is behind the current week: those weeks keep the span
    they were computed with, so there is nothing to re-derive and nothing to bump.
    """
    current = IsoWeek.containing(today)
    last = IsoWeek.containing(end_date)
    if last < current:
        return None
    return WeekRange(first=max(current, IsoWeek.containing(start_date - _ONE_DAY)), last=last)
