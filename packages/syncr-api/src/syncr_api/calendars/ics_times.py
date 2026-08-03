"""Turning a feed's wall time into an instant, against the zone active on that date.

The rules this module applies are the domain's, not its own. ``to_instant`` resolves a wall
time against a zone and a date, including both daylight-saving cases, and ``active_zone``
answers which zone the user is in on a given date. Nothing here compares a date to a travel
range or reasons about a transition, so there is no second implementation to disagree with
the one the solver and the assembler read.

What IS decided here is which zone each of the three kinds resolves against:

*A ``Z`` suffix* is already an instant. The value states it; no profile is consulted.

*A named ``TZID``* resolves in the zone the feed named. A lecture published in
``Europe/London`` is at 09:00 London whether or not the user is in Tokyo that week.

*A floating time* resolves in the zone **active on that date**, per the user's profile.
That is the only reading that makes "09:00, wherever I am" mean what it says.

An all-day event is a floating span rather than a floating instant: it occupies the full
local day, so each end resolves against the zone active on ITS own date. A day containing a
transition is therefore 23 or 25 hours long, which is what the day actually was.

Every function takes the occurrence's own wall datetime rather than deriving one from the
series. A recurrence rule may move the time of day as well as the date (``BYHOUR``), so
reusing the series' time would silently place such an occurrence at the wrong hour.
"""

from __future__ import annotations

from datetime import UTC, timedelta
from typing import TYPE_CHECKING

from syncr_api.calendars.ics_values import IcsValueError, ZoneKind
from syncr_domain.intervals import Interval, as_instant
from syncr_domain.zones import active_zone, to_instant

if TYPE_CHECKING:
    from datetime import date, datetime

    from syncr_api.calendars.ics_values import IcsTime
    from syncr_domain.intervals import Instant
    from syncr_domain.zones import ZoneId, ZoneProfile

ONE_DAY = timedelta(days=1)

_LOCAL_MIDNIGHT = 0


def zone_for(moment: IcsTime, on: date, profile: ZoneProfile) -> ZoneId:
    """Which zone resolves ``moment`` on ``on``.

    The date is separate from the value because a weekly series crossing a travel boundary
    resolves each occurrence against the zone active on that occurrence's own date.
    """
    if moment.kind is ZoneKind.NAMED and moment.zone is not None:
        return moment.zone
    return active_zone(profile, on)


def resolve(moment: IcsTime, profile: ZoneProfile, *, wall: datetime | None = None) -> Instant:
    """The instant this occurrence names. ``wall`` defaults to the series' own value."""
    at = moment.wall if wall is None else wall
    if moment.kind is ZoneKind.UTC:
        return as_instant(at.replace(tzinfo=UTC))
    return to_instant(at.time(), at.date(), zone_for(moment, at.date(), profile))


def resolve_span(
    moment: IcsTime, profile: ZoneProfile, *, wall: datetime, span: timedelta
) -> Interval:
    """A timed occurrence at ``wall``, lasting the series' absolute ``span``.

    The duration is applied in ABSOLUTE time rather than re-resolved from a wall-clock end.
    Resolving both ends independently can invert them: on a spring-forward date a 01:30 start
    shifts to 02:30 while a 02:00 end does not move, and an interval needs start < end.
    Adding the span the series declared cannot invert, and keeps every occurrence the length
    the publisher stated.
    """
    start = resolve(moment, profile, wall=wall)
    return Interval(start, start + span)


def resolve_day_span(
    moment: IcsTime, profile: ZoneProfile, *, wall: datetime, days: int
) -> Interval:
    """An all-day occurrence: ``days`` whole local days from local midnight on ``wall``.

    Each end resolves against the zone active on its OWN date, so a range spanning a travel
    boundary or a transition is as long as those days really were.
    """
    if days < 1:
        message = f"an all-day event needs at least one day, got {days}"
        raise IcsValueError(message)
    first = wall.date()
    last = first + ONE_DAY * days
    midnight = wall.time().replace(hour=_LOCAL_MIDNIGHT, minute=0, second=0, microsecond=0)
    return Interval(
        to_instant(midnight, first, active_zone(profile, first)),
        to_instant(midnight, last, active_zone(profile, last)),
    )
