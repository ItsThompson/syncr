"""The pie review's service: one read that writes nothing, and one apply that writes shares.

**The read writes nothing at all.** No row, no input version bump, and no verdict. It reads the
plan of record, the outcome log, the off-plan periods and the Areas, and hands them to the review's
own arithmetic.

**The denominator is the plan of record's own stored figure.** Not a recomputation. See
``reviews.history`` for why, and for what a recomputation gets wrong in each direction.

**The apply is one lock, one write per changed Area, and one version bump.** The lock is the Areas'
own, for the same reason a declaration takes it: the whole set is read, checked and written in one
transaction, so a concurrent declaration cannot land between the check and the write. One bump
rather than one per Area, because the bump is open-ended and monotonic: thirteen increments of one
counter say exactly what one says, and cost twelve more statements.

**A share replaced by the value it already held is not applied.** Nothing is written for it and it
is not counted, so approving the same proposal twice does not invalidate a running solve the second
time. That is the same gate `preferences` applies to a replacement storing what was already stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.core.iso_weeks import require_an_iso_week
from syncr_api.core.principal import require_scope
from syncr_api.core.scopes import Scope
from syncr_api.reviews.config import PERIOD_PARAMETER, TREND_WEEKS
from syncr_api.reviews.readings import budget_review_reading
from syncr_api.reviews.rules import require_declared_areas
from syncr_api.user_settings.zone_reading import as_domain, stated_rejection, zone_profile
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.reviews.declarations import AppliedShares
    from syncr_api.reviews.history import ReviewHistoryReader
    from syncr_api.reviews.readings import BudgetReviewReading
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_api.user_settings.solve_inputs import BacklogWideBump
    from syncr_domain.identifiers import AreaId
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneProfile

_log = get_logger("syncr.reviews")


@dataclass(frozen=True, slots=True)
class AppliedRevision:
    """What one apply changed. ``at`` is ``None`` when nothing did."""

    declared: tuple[AreaId, ...]
    at: datetime | None


class BudgetReviewService:
    """Report one quarter's behaviour against its budget, and apply a revision of it."""

    def __init__(
        self,
        areas: AreaRepository,
        settings: SettingsRepository,
        overrides: TravelOverrideRepository,
        history: ReviewHistoryReader,
        bump: BacklogWideBump,
        clock: Clock,
    ) -> None:
        self._areas = areas
        self._settings = settings
        self._overrides = overrides
        self._history = history
        self._bump = bump
        self._clock = clock

    @measured("reviews")
    async def read(self, principal: Principal, period: str) -> BudgetReviewReading:
        """The review anchored at ``period``, over the quarter ending with it. Writes nothing."""
        require_scope(principal, Scope.PLAN_READ)
        anchor = require_an_iso_week(period, field=PERIOD_PARAMETER)
        profile = await self._profile()
        quarter = await self._history.read(_quarter_ending_at(anchor), profile)
        declared = await self._areas.list_all()
        return budget_review_reading(quarter, shares=[area.as_share() for area in declared])

    @measured("reviews")
    async def apply(self, principal: Principal, asked: AppliedShares) -> AppliedRevision:
        """Declare the shares the caller sent, whole or adjusted, or refuse the whole request."""
        require_scope(principal, Scope.ADMIN)
        now = self._clock()
        existing = await self._areas.lock_all()
        require_declared_areas(asked.by_area, {area.id for area in existing})

        moved = [
            area
            for area in existing
            if area.id in asked.by_area and area.budget_percent != asked.by_area[area.id]
        ]
        for area in moved:
            await self._areas.write(
                area.id,
                name=area.name,
                pigment_index=area.pigment_index,
                budget_percent=asked.by_area[area.id],
                floor_hours=area.floor_hours,
            )
        _log.info(
            "reviews.budget.applied",
            tenant_id=str(principal.tenant_id),
            areas_asked=len(asked.by_area),
            areas_changed=len(moved),
        )
        if moved:
            await self._bump.from_the_week_holding(now)
        return AppliedRevision(declared=tuple(area.id for area in moved), at=now if moved else None)

    async def _profile(self) -> ZoneProfile:
        """The tenant's zone profile, which every wall time in the quarter resolves against."""
        settings = await self._settings.read()
        overrides = await self._overrides.list_all()
        with stated_rejection(field="home zone"):
            return zone_profile(settings.home_zone, as_domain(overrides))


def _quarter_ending_at(anchor: IsoWeek) -> tuple[IsoWeek, ...]:
    """The quarter of ISO weeks ending with ``anchor``, oldest first.

    Walked through :meth:`IsoWeek.preceding`, which resolves through the calendar rather than by
    subtracting one from a week number: ``2027-W01`` precedes into ``2026-W53``, so neither the week
    number nor the ISO year alone decides the answer.
    """
    weeks = [anchor]
    for _ in range(TREND_WEEKS - 1):
        weeks.append(weeks[-1].preceding())
    return tuple(reversed(weeks))
