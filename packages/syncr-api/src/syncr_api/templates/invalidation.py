"""Which weeks a day-shape mutation invalidates, and the one rule that decides it.

A week materializes its shapes through the week pattern: a date resolves to a weekday, the
weekday to a day type, and the day type to the shape whose entries are placed. So a mutation
reaches a week exactly when the pattern maps the day type it touched, and that one rule covers
every mutation this package makes:

* Declaring a day type reaches no week. A day type nothing maps and nothing shapes cannot change
  what materializes, and this falls out of the rule rather than being an exception to it.
* Creating, renaming, or removing a shape, and adding, changing, or removing one of its entries,
  reaches every future week when the pattern maps that shape's day type.
* Replacing the pattern reaches every future week, always. It maps all seven weekdays, so there
  is no week it does not describe.

**Past weeks are never bumped.** An approved revision is immutable and keeps the inputs it was
computed with, so the floor is the week holding today's local date in the home zone. Re-deriving
a past week would rewrite history rather than the plan.

The home zone is read here rather than resolved a second way, because which week holds "today"
is a local question and two answers would let the boundary and the assembler disagree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.user_settings.solve_inputs import weeks_from
from syncr_api.user_settings.zone_reading import local_date

if TYPE_CHECKING:
    from syncr_api.core.clock import Clock
    from syncr_api.templates.repository import WeekPatternRepository
    from syncr_api.user_settings.repository import SettingsRepository
    from syncr_api.user_settings.solve_inputs import WeekInputVersions
    from syncr_domain.identifiers import DayTypeId


class FutureWeeks:
    """The weeks a day-shape mutation invalidates: this one onwards, or none at all."""

    def __init__(
        self,
        patterns: WeekPatternRepository,
        settings: SettingsRepository,
        versions: WeekInputVersions,
        clock: Clock,
    ) -> None:
        self._patterns = patterns
        self._settings = settings
        self._versions = versions
        self._clock = clock

    async def invalidate(self) -> None:
        """Bump the input version of the current week and every week after it."""
        settings = await self._settings.read()
        await self._versions.bump(weeks_from(local_date(self._clock(), settings.home_zone)))

    async def invalidate_if_mapped(self, day_type_id: DayTypeId) -> bool:
        """:meth:`invalidate`, but only when some weekday uses this day type.

        Returns whether it did, so the mutation's own log line can state whether it reached a
        week. A tenant with no pattern yet has nothing mapped and nothing planned, so a shape
        declared before the pattern invalidates nothing.
        """
        pattern = await self._patterns.read()
        if pattern is None or not pattern.covers(day_type_id):
            return False
        await self.invalidate()
        return True
