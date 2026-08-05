"""The budget service: one period, five separately named quantities.

Every figure here comes from ``syncr_domain``. This module resolves the week's span, reads the
Areas, asks what the week already holds, and hands all of it to one function; it performs no
arithmetic of its own. That is the point of the section's rule that there is exactly one
implementation of the budget arithmetic: the pie review, the deviation bars, the verdict panel,
the feasibility probe, and the solver's capacity check all consume the same computation, and a
second implementation here would be the one that quietly disagreed.

Three properties are worth stating.

**The denominator is discretionary time, never scheduled time.** Measuring against scheduled
time would inflate every Area's share by excluding exactly the hours the user never planned.

**``unallocated`` and ``oversubscription`` are different quantities and are reported
separately.** ``unallocated`` is discretionary time in no block carrying an Area.
``oversubscription`` is how far Area targets exceed discretionary time. One is never rendered as
the other, and neither is ever negative.

**A week that was entirely off-plan says so.** Its denominator is zero and so is every
percentage target, which on the wire is indistinguishable from a week nobody planned, and the two
mean opposite things. The off-plan reading is acquired through the same occupancy the denominator
subtracted, so the statement and the figure it explains cannot disagree.

**The span is the week's real span.** It comes from ``week_span`` over the tenant's own zone
profile, so a transition week is 167 or 169 hours and a travel week resolves two zones across
its days. Every figure derives from ``span.total_minutes()``, so no figure needs a special case
for either. The zone active on each day inside the week and the home zone the week's dates are
resolved in both come from the same profile and are carried on the view, because the three are one
question asked three times and a second reader of the profile in one request would be a second
answer to how long that week was.

The read writes nothing at all: no row, no version bump, and no verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.budgets.config import PERIOD_PARAMETER
from syncr_api.core.iso_weeks import require_an_iso_week
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.offplan.reading import off_plan_reading
from syncr_api.user_settings.zone_reading import as_domain, stated_rejection, zone_profile
from syncr_common.metrics import measured
from syncr_domain.budgets import budget_report
from syncr_domain.discretionary import discretionary_intervals
from syncr_domain.weeks import active_zone_by_date, week_span

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.budgets.occupancy import WeekOccupancyReader
    from syncr_api.core.principal import Principal
    from syncr_api.offplan.reading import OffPlanReading
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_domain.budgets import BudgetReport
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date, ZoneId, ZoneProfile


@dataclass(frozen=True, slots=True)
class BudgetView:
    """One period's budget report, the span its denominator was derived from, and time off.

    ``zone_by_date`` and ``home_zone`` are beside the span because all three are one resolution
    asked three times: the span resolves the two Mondays bounding the week, the mapping resolves the
    days inside it, and the home zone is the one every "which date is it" question in this
    application is answered in. The report needs none of the three beyond the span, and a second
    caller needs all of them: the week view renders the zones and resolves the horizon's local date,
    and a profile read twice in one request is two answers to how long that week was.
    """

    period: IsoWeek
    span: Interval
    zone_by_date: Mapping[Date, ZoneId]
    home_zone: ZoneId
    report: BudgetReport
    off_plan: OffPlanReading


class BudgetService:
    """Report one period's discretionary time and how the Areas divide it."""

    def __init__(
        self,
        areas: AreaRepository,
        settings: SettingsRepository,
        overrides: TravelOverrideRepository,
        occupancy: WeekOccupancyReader,
    ) -> None:
        self._areas = areas
        self._settings = settings
        self._overrides = overrides
        self._occupancy = occupancy

    @measured("budgets")
    async def read(self, principal: Principal, period: str) -> BudgetView:
        """The budget report for ``period``, which is an ISO week identifier."""
        require_scope(principal, Scope.PLAN_READ)
        iso_week = _require_an_iso_week(period)
        profile = await self._profile()
        span = week_span(iso_week, profile)
        held = await self._occupancy.read(iso_week, span)
        declared = await self._areas.list_all()

        discretionary = discretionary_intervals(
            span, held.frame, held.anchors, held.absolute_forbidden, held.off_plan
        )
        report = budget_report(
            discretionary=discretionary,
            shares=[area.as_share() for area in declared],
            covered=held.by_area,
        )
        return BudgetView(
            period=iso_week,
            span=span,
            zone_by_date=active_zone_by_date(iso_week, profile),
            home_zone=profile.home_zone,
            report=report,
            off_plan=off_plan_reading(span, held.off_plan),
        )

    async def _profile(self) -> ZoneProfile:
        """The tenant's zone profile, which every wall time in the week resolves against."""
        settings = await self._settings.read()
        overrides = await self._overrides.list_all()
        with stated_rejection(field="home zone"):
            return zone_profile(settings.home_zone, as_domain(overrides))


def _require_an_iso_week(period: str) -> IsoWeek:
    """``period`` as an ISO week, or a 422 naming the parameter and the shape it takes.

    The reading is shared with the week and concession routes, which address the same identifier as
    a path segment: one parse, one wording, and the field name each caller's own.
    """
    return require_an_iso_week(period, field=PERIOD_PARAMETER)
