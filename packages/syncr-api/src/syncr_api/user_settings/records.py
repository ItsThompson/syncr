"""The immutable views of a settings row and a travel-override row.

A repository hands back one of these rather than a mapped instance, so a service cannot
trigger a load it did not ask for, a fake repository in a service test is a function
returning a frozen dataclass, and nothing downstream can change a row by assigning to it.

These are not the wire shapes: ``schemas.py`` owns those, so a column added here does not
appear in a response by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from syncr_domain.zones import TravelOverride

if TYPE_CHECKING:
    from datetime import date, time

    from syncr_api.user_settings.config import ReviewCadence
    from syncr_domain.identifiers import TenantId

type TravelOverrideId = UUID


@dataclass(frozen=True, slots=True)
class SettingsRecord:
    """One tenant's settings, as persistence knows them.

    A tenant who has never saved settings has no row, and the repository composes one of
    these from the declared defaults instead. Nothing distinguishes the two on the wire,
    which is deliberate: the alternative is a read that writes.
    """

    tenant_id: TenantId
    visible_hours: int
    day_start: time
    day_end: time
    review_cadence: ReviewCadence
    home_zone: str


@dataclass(frozen=True, slots=True)
class TravelOverrideRecord:
    """One travel override, as persistence knows it."""

    id: TravelOverrideId
    tenant_id: TenantId
    start_date: date
    end_date: date
    zone: str

    def as_domain(self) -> TravelOverride:
        """The domain value zone resolution is stated over.

        Identity and tenancy stay on the row: zone resolution needs neither, and the
        domain deliberately carries neither, so this is where the two shapes part.
        """
        return TravelOverride(start_date=self.start_date, end_date=self.end_date, zone=self.zone)
