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

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from syncr_api.calendars.day_spans import local_day_span
from syncr_api.calendars.ics_errors import MalformedValue
from syncr_api.calendars.ics_values import ZoneKind
from syncr_domain.intervals import Interval
from syncr_domain.zones import active_zone, resolve_zone, to_instant

if TYPE_CHECKING:
    from datetime import date, datetime

    from syncr_api.calendars.ics_values import IcsTime
    from syncr_domain.intervals import Instant
    from syncr_domain.zones import ZoneId, ZoneProfile

ONE_DAY = timedelta(days=1)

# The zone identifier a value with a ``Z`` suffix resolves against. Public because a second reader
# of the same mapping lives in this package: ``ics_recurrence_grammar`` rewrites a UTC ``UNTIL``
# into the series' clock and needs the same spelling.
UTC_ZONE: Final[ZoneId] = "UTC"


def zone_for(moment: IcsTime, on: date, profile: ZoneProfile) -> ZoneId:
    """Which zone resolves ``moment`` on ``on``.

    All three kinds answer here, so which zone reads a value is stated once and both directions
    read it: :func:`resolve` turns wall time into an instant and :func:`as_wall` turns an instant
    back into wall time.

    The date is separate from the value because a weekly series crossing a travel boundary
    resolves each occurrence against the zone active on that occurrence's own date.
    """
    if moment.kind is ZoneKind.UTC:
        return UTC_ZONE
    if moment.kind is ZoneKind.NAMED and moment.zone is not None:
        return moment.zone
    return active_zone(profile, on)


def resolve(moment: IcsTime, profile: ZoneProfile, *, wall: datetime | None = None) -> Instant:
    """The instant this occurrence names. ``wall`` defaults to the series' own value."""
    at = moment.wall if wall is None else wall
    return to_instant(at.time(), at.date(), zone_for(moment, at.date(), profile))


def as_wall(instant: Instant, *, zone_of: IcsTime, profile: ZoneProfile) -> datetime:
    """``instant`` as the wall time the zone ``zone_of`` resolves against reads it.

    The other direction from :func:`resolve`, for a value that states an instant of its own and has
    to join a series expanded in wall time. What comes back is naive, because that is what a wall
    time is.

    The zone is chosen against the instant's own UTC date rather than the local date it is about to
    name, because that date does not exist until the conversion is done. The two differ only where
    a travel override begins or ends between them.

    Not every instant has a wall time that resolves back to it. Two instants inside a repeated hour
    share one wall time and :func:`syncr_domain.zones.to_instant` takes the earlier of them, so an
    instant in the second hour restates onto a wall time that resolves an hour before it. That is a
    property of expanding in wall time, not of this conversion.
    """
    zone = zone_for(zone_of, instant.date(), profile)
    return instant.astimezone(resolve_zone(zone)).replace(tzinfo=None)


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
        raise MalformedValue(message)
    return local_day_span(wall.date(), days, profile)
