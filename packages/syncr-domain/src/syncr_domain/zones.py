"""Zone resolution and the wall-time-to-instant mapping, including both DST rules.

The split this module exists to serve: anchors are absolute, so a meeting at 14:00
UTC stays at 14:00 UTC and renders in whatever zone is active, while the frame is
local, so ``Wake 05:00`` means 05:00 wherever the user is. Routines and template
entries therefore store wall time, and it becomes an instant per day, against the
zone active on that day.

Two dates a year break the naive mapping, and each has a stated rule:

*Spring forward, a local time that does not exist.* ``Europe/London``, 2026-03-29:
01:00 jumps to 02:00, so a routine at 01:30 has no instant. It **shifts forward by
the gap length** and resolves to 02:30 local, the instant 01:30 would have been had
the gap not existed. The frame's purpose is ordering, not exact wall time; rejecting
the day or collapsing to the boundary would compress or reorder the morning.

*Fall back, a local time that occurs twice.* ``Europe/London``, 2026-10-25: 02:00
repeats, so a routine at 01:30 has two candidate instants. It takes the **first
occurrence**, the pre-transition offset, which preserves the frame's order within
the day and makes that day 25 hours long rather than silently 24.

Both rules follow from one choice, ``fold=0``. PEP 495 defines that as the offset in
effect *before* a transition: applied to a skipped time it yields the shifted-forward
instant, and applied to a repeated time it yields the earlier of the two.

Zone resolution is per date. A week spanning a travel boundary resolves two zones
across its days, so nothing in this module takes a single zone for a range.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from itertools import pairwise
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from syncr_domain.errors import DomainError
from syncr_domain.intervals import as_instant

if TYPE_CHECKING:
    from datetime import date

    from syncr_domain.intervals import Instant

type ZoneId = str
"""An IANA zone identifier, such as ``Europe/London``."""

type LocalTime = time
"""Wall time: no date, no zone. An instant only once a date and a zone resolve it."""

type Date = date

# PEP 495: fold=0 selects the offset in effect before a transition. Both stated DST
# rules fall out of it, so neither is implemented a second time here.
_EARLIER_OFFSET: Final = 0

# A zone identifier becomes a filesystem path inside `zoneinfo`, and one longer than the
# platform's filename limit fails there as a plain OSError rather than as a missing zone.
# The longest real key is 32 characters, so this bounds the input clear of both. Zone
# identifiers arrive from the wire, so the bound is not theoretical, and a boundary
# validating a zone field can read it from here rather than inventing a second number.
MAX_ZONE_KEY_LENGTH: Final = 64


class ZoneError(DomainError):
    """A zone, a wall time, or a travel override was rejected."""


class UnknownZoneError(ZoneError):
    """The identifier names no IANA zone."""


class OverlappingTravelError(ZoneError):
    """Two travel overrides cover one date, so no single zone is active on it."""


def resolve_zone(zone: ZoneId) -> ZoneInfo:
    """The tz database entry for ``zone``, or a stated rejection.

    Every rejection is an ``UnknownZoneError``, whatever shape the identifier had,
    because these arrive from the wire and a boundary needs exactly one error to catch.
    A key naming a directory in the tz tree is the trap: ``Europe`` and ``America`` are
    directories, so ``zoneinfo`` raises ``IsADirectoryError`` rather than reporting a
    missing zone.

    A genuine filesystem fault, a permission error on the tz database say, propagates
    as itself. Relabelling that as an unknown zone would send a deployment problem to
    the wrong place.
    """
    if len(zone) > MAX_ZONE_KEY_LENGTH:
        raise UnknownZoneError(f"a zone identifier of {len(zone)} characters names no IANA zone")
    try:
        return ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, IsADirectoryError) as error:
        raise UnknownZoneError(f"{zone!r} names no IANA time zone") from error


def to_instant(local: LocalTime, on: Date, zone: ZoneId) -> Instant:
    """Resolve wall time to an instant.

    A nonexistent time shifts forward by the gap; an ambiguous one takes the earlier
    offset. Both come from ``fold=0``; see the module docstring.

    The mapping is not one-to-one across a spring-forward gap. Every wall time inside
    the gap shifts onto a real time later in the day, so on ``Europe/London``,
    2026-03-29, both 01:30 and 02:30 resolve to ``2026-03-29T01:30Z``. Two frame
    entries whose target times straddle a gap therefore start at one instant, and a
    caller needing them distinct must separate them itself.
    """
    if local.tzinfo is not None:
        raise ZoneError(f"{local!r} carries a zone, but a wall time names none")
    if isinstance(on, datetime):
        raise ZoneError(f"{on!r} is a datetime, and combining one would silently drop its time")
    wall = datetime.combine(on, local, tzinfo=resolve_zone(zone))
    return as_instant(wall.replace(fold=_EARLIER_OFFSET))


@dataclass(frozen=True, order=True)
class TravelOverride:
    """A date range, inclusive at both ends, in which another zone is active."""

    start_date: Date
    end_date: Date
    zone: ZoneId

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ZoneError(
                f"a travel override needs start_date <= end_date, "
                f"got {self.start_date} to {self.end_date}"
            )
        resolve_zone(self.zone)

    def covers(self, on: Date) -> bool:
        return self.start_date <= on <= self.end_date

    def overlaps(self, other: TravelOverride) -> bool:
        """Whether both cover a common date. Two that abut exactly do not."""
        return self.start_date <= other.end_date and other.start_date <= self.end_date


@dataclass(frozen=True)
class ZoneProfile:
    """Where a user is: a home zone, plus the travel overrides that displace it.

    Construction sorts the overrides and rejects an overlapping pair, so at most one
    can cover any date and :func:`active_zone` has no ambiguity to resolve. The HTTP
    boundary that accepts a new override catches that rejection and states it.
    """

    home_zone: ZoneId
    travel_overrides: tuple[TravelOverride, ...] = ()

    def __post_init__(self) -> None:
        resolve_zone(self.home_zone)
        ordered = tuple(sorted(self.travel_overrides))
        for earlier, later in pairwise(ordered):
            if earlier.overlaps(later):
                raise OverlappingTravelError(
                    f"travel overrides {earlier.start_date}..{earlier.end_date} and "
                    f"{later.start_date}..{later.end_date} cover a common date"
                )
        object.__setattr__(self, "travel_overrides", ordered)


def active_zone(profile: ZoneProfile, on: Date) -> ZoneId:
    """The travel override covering ``on``, else the home zone."""
    for override in profile.travel_overrides:
        if override.covers(on):
            return override.zone
    return profile.home_zone
