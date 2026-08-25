"""The settings service: authorization, the zone reading, and the version bump.

Three rules live here rather than anywhere else.

**Zone resolution is the domain's, not this module's.** The active zone for a date comes
from ``syncr_domain.zones.active_zone`` over a ``ZoneProfile`` built from the stored rows.
Nothing here compares a date against a range, so there is no second implementation to
disagree with the one the solver and the assembler read. ``zone_reading.py`` holds the
three helpers that reading needs, and the mapping from a refused zone to a status.

**The overlap rejection is a caught domain error.** ``ZoneProfile`` refuses an overlapping
pair at construction, so declaring an override builds the profile the declaration would
produce and answers 409 when it will not build. Adjacency is not overlap, which follows
from the domain rather than from a rule restated here.

**A zone change is a solve-input mutation.** Changing the home zone or declaring an
override re-derives the frame, so the week input version is bumped for the weeks it
affects, from the current week onwards. Past weeks are not touched: an approved revision
is immutable and keeps the span it was computed with.

Visible hours, the day bounds, and the review cadence are NOT solve inputs. The first two
set the Week grid's default axis extent and the third decides when the pie review is
offered, so changing any of them bumps nothing and triggers no solve.

``authorize_tenant`` is called once here, on the one row a caller addresses by identifier.
Every row these methods touch was fetched through a repository scoped to the principal's
own tenant, so its ``tenant_id`` IS the principal's. The scoped ``SELECT`` never returns a
foreign row, and that is what turns another tenant's override identifier into a 404 rather
than a deletion. The one call is defense in depth rather than the check producing that 404,
and it sits where the caller supplies an identifier because that is the only place an
unscoped read could ever be introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syncr_api.core.errors import NotFound, ValidationFailed
from syncr_api.core.principal import authorize_tenant
from syncr_api.user_settings.config import VISIBLE_HOURS_MAX, VISIBLE_HOURS_MIN
from syncr_api.user_settings.solve_inputs import weeks_covering, weeks_from
from syncr_api.user_settings.zone_reading import (
    as_domain,
    local_date,
    stated_rejection,
    zone_profile,
)
from syncr_common.logging import get_logger
from syncr_common.metrics import measured
from syncr_domain.zones import TravelOverride, active_zone

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime, time

    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.user_settings.config import ReviewCadence
    from syncr_api.user_settings.records import (
        SettingsRecord,
        TravelOverrideId,
        TravelOverrideRecord,
    )
    from syncr_api.user_settings.repository import SettingsRepository, TravelOverrideRepository
    from syncr_api.user_settings.solve_inputs import WeekInputVersions
    from syncr_domain.zones import ZoneId

TRAVEL_OVERRIDE_RESOURCE = "travel override"

_log = get_logger("syncr.user_settings")


@dataclass(frozen=True, slots=True)
class SettingsChange:
    """What one ``PATCH`` asked to change. ``None`` means leave the value alone.

    No settings value is nullable, so there is nothing for an explicit null to clear: a
    field sent as ``null`` and a field left out both mean unchanged.
    """

    visible_hours: int | None = None
    day_start: time | None = None
    day_end: time | None = None
    review_cadence: ReviewCadence | None = None
    home_zone: str | None = None

    def applied_to(self, current: SettingsRecord) -> SettingsRecord:
        """``current`` with every field this change set replaced."""
        return replace(
            current,
            visible_hours=_or_current(self.visible_hours, current.visible_hours),
            day_start=_or_current(self.day_start, current.day_start),
            day_end=_or_current(self.day_end, current.day_end),
            review_cadence=_or_current(self.review_cadence, current.review_cadence),
            home_zone=_or_current(self.home_zone, current.home_zone),
        )


@dataclass(frozen=True, slots=True)
class SettingsView:
    """The settings, plus the zone reading the screen states.

    One zone, for one date. Rendering is single-zone throughout the product, so nothing
    here offers a second reading of the same moment.
    """

    visible_hours: int
    day_start: time
    day_end: time
    review_cadence: ReviewCadence
    home_zone: ZoneId
    active_zone: ZoneId
    active_zone_date: date


class SettingsService:
    """Read and change one tenant's settings, and manage its travel overrides."""

    def __init__(
        self,
        settings: SettingsRepository,
        overrides: TravelOverrideRepository,
        versions: WeekInputVersions,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._overrides = overrides
        self._versions = versions
        self._clock = clock

    @measured("user_settings")
    async def read(self, principal: Principal) -> SettingsView:
        """The settings and the zone active today. Writes nothing."""
        record = await self._settings.read()
        return self._view(record, await self._overrides.list_all(), now=self._clock())

    @measured("user_settings")
    async def update(self, principal: Principal, change: SettingsChange) -> SettingsView:
        """Apply a partial update, and bump the input version if the home zone moved."""
        now = self._clock()
        current = await self._settings.lock(created_at=now)
        merged = change.applied_to(current)
        _require_a_renderable_grid(merged)

        overrides = await self._overrides.list_all()
        # Built before the write, so an unknown zone is rejected rather than stored.
        view = self._view(merged, overrides, now=now)
        await self._settings.write(
            visible_hours=merged.visible_hours,
            day_start=merged.day_start,
            day_end=merged.day_end,
            review_cadence=merged.review_cadence,
            home_zone=merged.home_zone,
        )

        if merged.home_zone != current.home_zone:
            # Not ``BacklogWideBump``, though this is an open-ended bump: the collaborator resolves
            # its floor by reading the stored settings row again, while this method holds that row
            # under ``lock`` and resolved ``view.active_zone_date`` against the MERGED zone before
            # the write, so an unknown zone is refused rather than stored. Bumping from the view
            # invalidates exactly what was written; a second read could disagree with it.
            affected = weeks_from(view.active_zone_date)
            # The zone identifier is deliberately absent from this line: it is coarse
            # location data, and identifiers are logged while content is not.
            _log.info(
                "user_settings.home_zone.changed",
                tenant_id=str(principal.tenant_id),
                first_week=str(affected.first),
            )
            await self._versions.bump(affected)
        return view

    @measured("user_settings")
    async def list_travel_overrides(self, principal: Principal) -> tuple[TravelOverrideRecord, ...]:
        """Every override this tenant has declared, in date order."""
        return await self._overrides.list_all()

    @measured("user_settings")
    async def declare_travel_override(
        self, principal: Principal, *, start_date: date, end_date: date, zone: ZoneId
    ) -> TravelOverrideRecord:
        """Declare a range in another zone, or state why it cannot be declared.

        The settings row is locked first, so two declarations racing are serialized and
        the second one sees the first. Without that, both would pass an overlap check
        against the same rows and both would insert, leaving a tenant for whom no single
        zone is active on a date.
        """
        now = self._clock()
        settings = await self._settings.lock(created_at=now)
        existing = await self._overrides.list_all()

        with stated_rejection(field="zone"):
            candidate = TravelOverride(start_date=start_date, end_date=end_date, zone=zone)
            zone_profile(settings.home_zone, (*as_domain(existing), candidate))

        created = await self._overrides.create(
            start_date=start_date, end_date=end_date, zone=zone, created_at=now
        )
        _log.info(
            "user_settings.travel_override.declared",
            tenant_id=str(principal.tenant_id),
            override_id=str(created.id),
        )
        await self._bump_for(created, today=local_date(now, settings.home_zone))
        return created

    @measured("user_settings")
    async def remove_travel_override(
        self, principal: Principal, override_id: TravelOverrideId
    ) -> None:
        """Remove one override, so the home zone governs its dates again."""
        now = self._clock()
        found = await self._overrides.find(override_id)
        if found is None:
            raise NotFound(f"No {TRAVEL_OVERRIDE_RESOURCE} matches that identifier.")
        authorize_tenant(principal, found.tenant_id, resource=TRAVEL_OVERRIDE_RESOURCE)

        await self._overrides.remove(override_id)
        _log.info(
            "user_settings.travel_override.removed",
            tenant_id=str(principal.tenant_id),
            override_id=str(override_id),
        )
        settings = await self._settings.read()
        await self._bump_for(found, today=local_date(now, settings.home_zone))

    async def _bump_for(self, override: TravelOverrideRecord, *, today: date) -> None:
        """Bump the future weeks this override's range covers, if it covers any."""
        affected = weeks_covering(override.start_date, override.end_date, today=today)
        if affected is not None:
            await self._versions.bump(affected)

    def _view(
        self,
        record: SettingsRecord,
        overrides: Sequence[TravelOverrideRecord],
        *,
        now: datetime,
    ) -> SettingsView:
        with stated_rejection(field="home zone"):
            profile = zone_profile(record.home_zone, as_domain(overrides))
        on = local_date(now, record.home_zone)
        return SettingsView(
            visible_hours=record.visible_hours,
            day_start=record.day_start,
            day_end=record.day_end,
            review_cadence=record.review_cadence,
            home_zone=record.home_zone,
            active_zone=active_zone(profile, on),
            active_zone_date=on,
        )


def _or_current[ValueT](change: ValueT | None, current: ValueT) -> ValueT:
    return current if change is None else change


def _require_a_renderable_grid(merged: SettingsRecord) -> None:
    """Reject grid geometry the Week screen cannot draw.

    Both rules are stated over the MERGED record rather than the request, because a patch
    may set one value and inherit the other, and it is the resulting pair that has to make
    sense. The Week grid derives its default extent as the interval between the day bounds,
    and an interval needs a positive length.

    Visible hours is bounded by the request schema as well. It is restated here because
    ``SettingsService`` is a public interface: a caller reaching it without FastAPI would
    otherwise get an ``IntegrityError`` from the CHECK constraint where the day bounds give
    a stated 422.
    """
    if not VISIBLE_HOURS_MIN <= merged.visible_hours <= VISIBLE_HOURS_MAX:
        raise ValidationFailed(
            f"Visible hours is {merged.visible_hours}, outside the grid's zoom range of "
            f"{VISIBLE_HOURS_MIN} to {VISIBLE_HOURS_MAX} hours. Nothing was changed; every "
            "other setting still reads as it did."
        )
    if merged.day_start >= merged.day_end:
        raise ValidationFailed(
            f"The day starts at {merged.day_start:%H:%M} and ends at {merged.day_end:%H:%M}, "
            "so it has no length. Day start must be earlier than day end. Nothing was "
            "changed; every other setting still reads as it did."
        )
