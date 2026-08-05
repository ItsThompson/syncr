"""Which of a week's dates the user has answered for, read from the outcome log.

The Week screen renders the count of unconfirmed days beside the Today surface's own, and both
figures have to come from one rule or the two surfaces disagree about the same week. This is that
rule, offered as the reader the week view's own seam asks for: a date is confirmed when every block
that begins in it carries a confirmation, and a date holding no block is not confirmed, because
there is nothing to answer for.

**It reads the plan of record, not just the log.** A date is settled relative to what was planned
in it, so the answer needs both halves: which blocks the day holds, and which of them carry an
instant. A reader over the log alone could only say "some rows in this week are confirmed", which is
not a per-date answer at all.

**One read per week, whatever the week's shape.** The whole week's dates are answered from one plan
of record and one outcome read, which is what keeps the count off the request path's critical cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.outcomes.ledger import settled_at
from syncr_api.outcomes.planned_days import spanning
from syncr_api.user_settings.zone_reading import as_domain, zone_profile

if TYPE_CHECKING:
    from syncr_api.outcomes.planned_days import PlannedDayReader
    from syncr_api.plans.reality import BlockOutcomeRepository
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date


class RecordedDayConfirmations:
    """The dates of a week the user has answered for, over the outcome log."""

    def __init__(
        self,
        days: PlannedDayReader,
        outcomes: BlockOutcomeRepository,
        settings: SettingsRepository,
        overrides: TravelOverrideRepository,
    ) -> None:
        self._days = days
        self._outcomes = outcomes
        self._settings = settings
        self._overrides = overrides

    async def confirmed_dates(self, iso_week: IsoWeek) -> frozenset[Date]:
        """The week's dates whose every block carries a confirmation. Reads only, never writes."""
        dates = iso_week.dates()
        profile = zone_profile(
            (await self._settings.read()).home_zone, as_domain(await self._overrides.list_all())
        )
        planned = await self._days.read(dates[0], dates[-1], profile)
        window = spanning(planned)
        if window is None:
            return frozenset()
        recorded = {row.block_id: row for row in await self._outcomes.for_span(window)}
        return frozenset(
            day.on
            for day in planned
            if day.blocks
            and settled_at([recorded.get(block.id) for block in day.blocks]) is not None
        )
