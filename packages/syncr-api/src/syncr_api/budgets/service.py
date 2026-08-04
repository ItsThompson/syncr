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
for either.

The read writes nothing at all: no row, no version bump, and no verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.core.errors import FieldError, ValidationFailed
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.offplan.reading import off_plan_reading
from syncr_api.user_settings.zone_reading import as_domain, stated_rejection, zone_profile
from syncr_common.metrics import measured
from syncr_domain.budgets import budget_report
from syncr_domain.discretionary import discretionary_intervals
from syncr_domain.weeks import IsoWeek, IsoWeekError, week_span

if TYPE_CHECKING:
    from syncr_api.areas.repository import AreaRepository
    from syncr_api.budgets.occupancy import WeekOccupancyReader
    from syncr_api.core.principal import Principal
    from syncr_api.offplan.reading import OffPlanReading
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_domain.budgets import BudgetReport
    from syncr_domain.intervals import Interval


@dataclass(frozen=True, slots=True)
class BudgetView:
    """One period's budget report, the span its denominator was derived from, and time off."""

    period: IsoWeek
    span: Interval
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
        span = await self._span_of(iso_week)
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
            report=report,
            off_plan=off_plan_reading(span, held.off_plan),
        )

    async def _span_of(self, iso_week: IsoWeek) -> Interval:
        """The week's real span, bounded by the zone active on each of its two Mondays."""
        settings = await self._settings.read()
        overrides = await self._overrides.list_all()
        with stated_rejection(field="home zone"):
            profile = zone_profile(settings.home_zone, as_domain(overrides))
        return week_span(iso_week, profile)


def _require_an_iso_week(period: str) -> IsoWeek:
    """``period`` as an ISO week, or a 422 naming the parameter and the shape it takes.

    Parsed by the domain, which is the only reader of the identifier's shape, so the route
    declares no pattern of its own that could drift from it.
    """
    try:
        return IsoWeek.parse(period)
    except IsoWeekError as error:
        raise ValidationFailed(
            f"The period was not accepted: {error}. Nothing was changed, and every other "
            "period still reports as it did.",
            errors=[_period_error(str(error))],
        ) from error


def _period_error(message: str) -> FieldError:
    return FieldError(field="period", message=message)
