"""The weeks a tenant's current projection horizon covers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from syncr_api.calendars.horizons import read_horizon_days
from syncr_api.horizon.weeks import horizon_weeks
from syncr_api.user_settings.zone_reading import local_date

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import ZoneId


class HorizonTarget(Protocol):
    """The horizon field the write target exposes."""

    @property
    def horizon_days(self) -> int | None: ...


class HorizonSources(Protocol):
    """The calendar-source reading needed to resolve a horizon length."""

    async def write_target(self) -> HorizonTarget | None: ...


class HorizonSettingsRecord(Protocol):
    """The home-zone field the settings row exposes."""

    @property
    def home_zone(self) -> ZoneId: ...


class HorizonSettings(Protocol):
    """The settings reading needed to resolve the tenant's local date."""

    async def read(self) -> HorizonSettingsRecord: ...


class ProjectionHorizon(Protocol):
    """The future weeks one mutation can change."""

    async def weeks_at(self, now: datetime) -> tuple[IsoWeek, ...]: ...


class CurrentProjectionHorizon:
    """Resolve the horizon from the tenant's current settings and write target."""

    def __init__(self, sources: HorizonSources, settings: HorizonSettings) -> None:
        self._sources = sources
        self._settings = settings

    async def weeks_at(self, now: datetime) -> tuple[IsoWeek, ...]:
        settings = await self._settings.read()
        return horizon_weeks(
            today=local_date(now, settings.home_zone),
            horizon_days=await read_horizon_days(self._sources),
        )
