"""How the boundary reads a zone, and how it states a rejection.

Three small pieces the service uses and nothing else does. They sit here rather than in
``service.py`` so that file holds the operations and their authorization, and so the one
question a reader asks about zones at this layer, "which zone, for which date, and what
happens when the answer is refused", is answered in one place.

Nothing here compares a date against a range. ``active_zone`` does that, in the domain,
and it is the only implementation.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from syncr_api.core.errors import Conflict, ValidationFailed
from syncr_domain.zones import (
    OverlappingTravelError,
    TravelOverride,
    ZoneError,
    ZoneProfile,
    resolve_zone,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from datetime import date, datetime

    from syncr_api.user_settings.records import TravelOverrideRecord
    from syncr_domain.zones import ZoneId


def zone_profile(home_zone: str, overrides: Sequence[TravelOverride]) -> ZoneProfile:
    """The domain value zone resolution is stated over.

    A declaration is checked by building the profile it WOULD produce, including it among
    the stored ones, which is what makes the overlap rule the domain's alone.
    """
    return ZoneProfile(home_zone=home_zone, travel_overrides=tuple(overrides))


def as_domain(overrides: Sequence[TravelOverrideRecord]) -> tuple[TravelOverride, ...]:
    """The stored rows as the domain values zone resolution takes."""
    return tuple(override.as_domain() for override in overrides)


def local_date(moment: datetime, zone: ZoneId) -> date:
    """The local date ``moment`` falls on in ``zone``.

    The zone is the HOME zone wherever this is called, never the active one: the date is
    what selects a travel override, so resolving the date in the override's own zone would
    need the answer before it could be computed. The two differ only for a few hours either
    side of a date change at the start or end of a trip.
    """
    return moment.astimezone(resolve_zone(zone)).date()


@contextmanager
def stated_rejection(*, field: str) -> Iterator[None]:
    """Turn a domain zone rejection into the status the boundary owes it.

    An overlap is a state conflict, so 409. Anything else the zone layer rejects is a bad
    value in the request, so 422. Every rejection ``resolve_zone`` can produce arrives as a
    ``ZoneError``, whatever shape the identifier had, which is why one clause covers an
    absent zone, a malformed one, an over-length one, and one naming a directory in the tz
    database.
    """
    try:
        yield
    except OverlappingTravelError as error:
        raise Conflict(
            f"That range overlaps one already declared: {error}. Nothing was changed. "
            "Shorten or remove the overlapping override and declare this range again. "
            "Two ranges that abut exactly are accepted, because adjacency is not overlap."
        ) from error
    except ZoneError as error:
        raise ValidationFailed(
            f"The {field} was not accepted: {error}. Nothing was changed. "
            "Use an IANA identifier such as 'Europe/London'."
        ) from error
