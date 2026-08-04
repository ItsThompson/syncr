"""Which weeks a mutation invalidates, and who is told about it.

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

``BacklogWideBump`` is here rather than in the feature modules that use it because the same
four steps serve every mutation whose effect has no end date: an Area budget, a task, a habit,
a routine, a template. Each of them governs every week the user has not yet lived, so each
needs today's LOCAL date resolved in the home zone, and resolving that in five places would
let five services disagree about which week the floor is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from syncr_api.user_settings.zone_reading import local_date
from syncr_common.logging import get_logger
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from datetime import date, datetime

    from syncr_api.core.clock import Clock
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.user_settings.repository import SettingsRepository

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

    ``start_date <= end_date`` is a precondition. The domain refuses the reversed pair
    before an override can be stored or declared, so a caller here already holds a range
    that runs forward; passing a reversed one raises ``ValueError`` from ``WeekRange``
    rather than returning a range nobody could act on.
    """
    current = IsoWeek.containing(today)
    last = IsoWeek.containing(end_date)
    if last < current:
        return None
    return WeekRange(first=max(current, IsoWeek.containing(start_date - _ONE_DAY)), last=last)


class BacklogWideBump:
    """Invalidates the current week's inputs and every week after it.

    For a mutation whose effect has no end date: a budget, a task, a habit, a routine, a
    template. The range has no end because such a change governs every week the user has not yet
    lived, and its floor is the week holding today's local date in the HOME zone, because a past
    week's approved revision is immutable and keeps the inputs it was computed with.

    A collaborator rather than a function so a service takes one dependency instead of two and a
    service test can record what would have been bumped without a settings row.
    """

    def __init__(self, versions: WeekInputVersions, settings: SettingsRepository) -> None:
        self._versions = versions
        self._settings = settings

    async def from_the_week_holding(self, now: datetime) -> None:
        """Bump every tracked week from the one holding ``now``'s local date onwards."""
        settings = await self._settings.read()
        await self._versions.bump(weeks_from(local_date(now, settings.home_zone)))
