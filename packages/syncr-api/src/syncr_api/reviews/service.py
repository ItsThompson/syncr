"""The review services: the pie review's read and apply, and the weekly session's one read.

**Neither read writes anything at all.** No row, no input version bump, and no verdict event. Each
reads the plan of record, the outcome log, the off-plan periods and the Areas, and hands them to the
review's own arithmetic. The apply is the one write in this module, and it is what US-REV-03's
"syncr never re-cuts the budget on its own" means in code: nothing moves a share except a request
the user made.

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
from syncr_api.reviews.config import (
    ISO_WEEK_FIELD,
    PERIOD_PARAMETER,
    SESSION_LOOKBACK_WEEKS,
    TREND_WEEKS,
)
from syncr_api.reviews.readings import budget_review_reading
from syncr_api.reviews.rules import require_declared_areas
from syncr_api.reviews.session import (
    WeeklySessionReading,
    promotions_of,
    raised_of,
    retro_of,
    titles_of,
)
from syncr_api.user_settings.zone_reading import as_domain, stated_rejection, zone_profile
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.promotion import detect_repeated_pins

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from syncr_api.areas.repository import AreaRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.plans.service import WeekService
    from syncr_api.reviews.declarations import AppliedShares
    from syncr_api.reviews.history import ReviewHistoryReader
    from syncr_api.reviews.readings import BudgetReviewReading
    from syncr_api.reviews.session_sources import SessionSources
    from syncr_api.user_settings.records import SettingsRecord, TravelOverrideRecord
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
        profile = _zone_profile(await self._settings.read(), await self._overrides.list_all())
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


class WeeklySessionService:
    """Compose the weekly session's payload. One method, and it writes nothing at all."""

    def __init__(
        self,
        *,
        weeks: WeekService,
        areas: AreaRepository,
        settings: SettingsRepository,
        overrides: TravelOverrideRepository,
        history: ReviewHistoryReader,
        sources: SessionSources,
        clock: Clock,
    ) -> None:
        self._weeks = weeks
        self._areas = areas
        self._settings = settings
        self._overrides = overrides
        self._history = history
        self._sources = sources
        self._clock = clock

    @measured("reviews")
    async def read(self, principal: Principal, iso_week: str) -> WeeklySessionReading:
        """The session for the week ``iso_week`` plans, reviewing the week before it.

        **The week view is reached through its own service rather than reassembled here**, and that
        is the whole reason the verdict on this payload and the verdict on the Week screen cannot
        disagree: there is one composition, one served-verdict rule, and one instant. It also means
        this read inherits that read's guarantee that it writes nothing.

        The window is read once and used three times: as the retrospective's own week, as the weeks
        a chronic-skip run is walked over, and as the weeks a repeated pin is grouped across.
        Reading it three times would be three answers to how long each of those weeks was.

        ``VE6``: no row, no operation, no version bump, and no ``VerdictEvent``. The guard that
        holds it is stated over the response shapes that carry a verdict, so this payload is covered
        by having declared the field.
        """
        require_scope(principal, Scope.PLAN_READ)
        planned = require_an_iso_week(iso_week, field=ISO_WEEK_FIELD)
        now = self._clock()
        settings = await self._settings.read()
        profile = _zone_profile(settings, await self._overrides.list_all())
        view = await self._weeks.read(principal, str(planned))
        window = _window_ending_at(planned.preceding(), weeks=SESSION_LOOKBACK_WEEKS)
        reviewed = await self._history.read(window, profile)
        shares = [area.as_share() for area in await self._areas.list_all()]
        facts = await self._sources.read(
            planned=planned,
            reviewed=window,
            profile=profile,
            home_zone=settings.home_zone,
            now=now,
        )
        titles = titles_of(reviewed, view.live)
        return WeeklySessionReading(
            iso_week=planned,
            span=view.span,
            retro=retro_of(reviewed[-1], shares=shares),
            raised=raised_of(view, reviewed, facts, titles=titles, now=now),
            verdict=view.verdict,
            concessions=view.adjustments,
            promotions=promotions_of(detect_repeated_pins(facts.pins), titles=titles),
            input_version=view.input_version,
        )


def _zone_profile(
    settings: SettingsRecord, overrides: Sequence[TravelOverrideRecord]
) -> ZoneProfile:
    """The tenant's zone profile, which every wall time in a reviewed period resolves against.

    A function rather than a method on either service, because both reviews resolve the same thing
    from the same two rows and a second copy is how one of them comes to read a stale zone. The
    settings row arrives already read, so a caller that also wants the home zone reads the row once.
    """
    with stated_rejection(field="home zone"):
        return zone_profile(settings.home_zone, as_domain(overrides))


def _window_ending_at(anchor: IsoWeek, *, weeks: int) -> tuple[IsoWeek, ...]:
    """The run of ``weeks`` ISO weeks ending with ``anchor``, oldest first.

    Walked through :meth:`IsoWeek.preceding`, which resolves through the calendar rather than by
    subtracting one from a week number: ``2027-W01`` precedes into ``2026-W53``, so neither the week
    number nor the ISO year alone decides the answer.
    """
    walked = [anchor]
    for _ in range(weeks - 1):
        walked.append(walked[-1].preceding())
    return tuple(reversed(walked))


def _quarter_ending_at(anchor: IsoWeek) -> tuple[IsoWeek, ...]:
    """The quarter of ISO weeks ending with ``anchor``, oldest first."""
    return _window_ending_at(anchor, weeks=TREND_WEEKS)
