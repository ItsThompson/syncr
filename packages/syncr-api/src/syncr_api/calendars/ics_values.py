"""Reading an ICS date, time, and duration into a wall time plus how to resolve it.

The point of this module is that a feed's DTSTART names one of **three** different things,
and conflating them is how an event lands in the wrong hour:

``20260209T090000Z``           an instant. The zone is UTC and nothing else applies.
``TZID=Europe/London:...``     wall time in a named zone, resolved through the tz database.
``20260209T090000``            floating: wall time in whatever zone the user is in that day.
``VALUE=DATE:20260209``        a whole local day, in the zone active on that date.

So parsing answers with a wall time and a **zone kind**, and resolution to an instant
happens later, against the tenant's zone profile, in :mod:`syncr_api.calendars.ics_times`.
Keeping them apart is what lets a floating time and an all-day event both be "resolved in
the active zone for that date" without either one reimplementing the DST rules the domain
already owns.

Recurrence is expanded in WALL time for the same reason. RFC 5545 recurs in the local time
of the series' own zone, so a 09:00 lecture stays at 09:00 across a spring-forward
boundary. Expanding in UTC would move it to 08:00 for half the year.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Final

from syncr_api.calendars.config import MAX_EVENT_DAYS
from syncr_api.calendars.ics_errors import MalformedValue
from syncr_api.calendars.ics_zones import resolve_tzid

# `20260209T090000` with an optional trailing Z, and the date-only form.
_DATE_TIME: Final = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)$")
_DATE_ONLY: Final = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

_SECONDS_PER_MINUTE: Final = 60
_SECONDS_PER_HOUR: Final = 60 * _SECONDS_PER_MINUTE
_SECONDS_PER_DAY: Final = 24 * _SECONDS_PER_HOUR
_SECONDS_PER_WEEK: Final = 7 * _SECONDS_PER_DAY

# RFC 5545 duration: `P` then weeks, or days with an optional time part. A leading `-`
# makes it negative, which a DURATION on an event must not be.
_DURATION: Final = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<weeks>\d+)W|(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)

VALUE_PARAM: Final = "VALUE"
TZID_PARAM: Final = "TZID"
DATE_VALUE: Final = "DATE"


class ZoneKind(Enum):
    """How a parsed wall time becomes an instant.

    Three members, because three different rules apply and each is stated where it is
    resolved rather than inferred from whether a field happens to be set.
    """

    UTC = "utc"
    NAMED = "named"
    FLOATING = "floating"


@dataclass(frozen=True, slots=True)
class IcsTime:
    """A wall time from a feed, and what resolves it to an instant.

    ``wall`` is naive by construction: a value that carried a zone would have already been
    resolved, and mixing the two is what makes a recurrence expansion drift.

    ``all_day`` is carried rather than derived from the time being midnight, because a
    timed event genuinely at 00:00 is not an all-day event and occupies its own duration
    rather than the whole day.
    """

    wall: datetime
    kind: ZoneKind
    zone: str | None
    all_day: bool

    def __post_init__(self) -> None:
        if self.wall.tzinfo is not None:
            message = f"{self.wall!r} carries a zone, but an ICS wall time names none"
            raise MalformedValue(message)
        if (self.zone is None) is (self.kind is ZoneKind.NAMED):
            message = f"a {self.kind.value} time and a zone of {self.zone!r} disagree"
            raise MalformedValue(message)

    @property
    def on(self) -> date:
        """The local date this time falls on: what selects a travel override."""
        return self.wall.date()


def parse_time(value: str, *, params: tuple[tuple[str, str], ...]) -> IcsTime:
    """One DTSTART, DTEND, RECURRENCE-ID, or EXDATE value as a wall time and a zone kind.

    Either the ``VALUE=DATE`` parameter or a date-shaped value makes this an all-day time, so a
    publisher that omits the parameter is still understood: iCloud omits it. A publisher that
    declares ``VALUE=DATE`` and then emits a date-TIME is rejected rather than reinterpreted,
    because the two halves of the property disagree and neither is more authoritative.
    """
    declared = _param(params, VALUE_PARAM)
    tzid = _param(params, TZID_PARAM)
    text = value.strip()

    if declared == DATE_VALUE or _DATE_ONLY.fullmatch(text):
        return IcsTime(wall=_parse_date(text), kind=ZoneKind.FLOATING, zone=None, all_day=True)

    matched = _DATE_TIME.fullmatch(text)
    if matched is None:
        message = f"{value!r} is neither an ICS date nor an ICS date-time"
        raise MalformedValue(message)
    year, month, day, hour, minute, second, utc_suffix = matched.groups()
    wall = _build(int(year), int(month), int(day), int(hour), int(minute), int(second), text)

    if utc_suffix:
        # The `Z` suffix is absolute and outranks a TZID: RFC 5545 forbids carrying both,
        # and a publisher that does has stated the instant unambiguously in the value.
        return IcsTime(wall=wall, kind=ZoneKind.UTC, zone=None, all_day=False)
    if tzid:
        return IcsTime(wall=wall, kind=ZoneKind.NAMED, zone=resolve_tzid(tzid), all_day=False)
    return IcsTime(wall=wall, kind=ZoneKind.FLOATING, zone=None, all_day=False)


def parse_duration(value: str) -> timedelta:
    """One DURATION value as a positive timedelta inside the bound syncr can place.

    A negative or zero duration is rejected. An interval needs a positive length, and an
    event that claims to end before it starts tells syncr nothing about occupancy, which
    is the same failure a missing DTEND is.

    The magnitude is bounded, and the total is summed as INTEGER SECONDS before a ``timedelta``
    exists. The constructor refuses a day count over 999,999,999 with an ``OverflowError``, which is
    not a rejection and would escape the adapter; and even a span it accepts can overflow the
    arithmetic that places it. Summing first means one bound covers every unit and no intermediate
    value can overflow, because Python integers do not.
    """
    matched = _DURATION.fullmatch(value.strip())
    if matched is None:
        message = f"{value!r} is not an ICS duration"
        raise MalformedValue(message)
    parts = matched.groupdict()
    seconds = (
        _number(parts["weeks"]) * _SECONDS_PER_WEEK
        + _number(parts["days"]) * _SECONDS_PER_DAY
        + _number(parts["hours"]) * _SECONDS_PER_HOUR
        + _number(parts["minutes"]) * _SECONDS_PER_MINUTE
        + _number(parts["seconds"])
    )
    if parts["sign"] == "-" or seconds <= 0:
        message = f"{value!r} is a duration of {seconds} seconds, and an event needs a positive one"
        raise MalformedValue(message)
    if seconds > MAX_EVENT_DAYS * _SECONDS_PER_DAY:
        message = (
            f"{value!r} is a duration of about {seconds // _SECONDS_PER_DAY} days, longer than the "
            f"{MAX_EVENT_DAYS} days syncr will place for one event"
        )
        raise MalformedValue(message)
    return timedelta(seconds=seconds)


def parse_sequence(value: str) -> int:
    """One SEQUENCE value, or a rejection.

    Read rather than defaulted on a bad value, because SEQUENCE is what resolves a
    duplicate UID: silently reading an unparseable one as 0 would let an older revision
    win over a newer one.
    """
    try:
        return int(value.strip())
    except ValueError as error:
        message = f"{value!r} is not a SEQUENCE number"
        raise MalformedValue(message) from error


def _param(params: tuple[tuple[str, str], ...], key: str) -> str | None:
    return next((value for name, value in params if name == key), None)


def _parse_date(text: str) -> datetime:
    matched = _DATE_ONLY.fullmatch(text)
    if matched is None:
        message = f"{text!r} is not an ICS date"
        raise MalformedValue(message)
    year, month, day = (int(part) for part in matched.groups())
    return _build(year, month, day, 0, 0, 0, text)


def _build(
    year: int, month: int, day: int, hour: int, minute: int, second: int, text: str
) -> datetime:
    """The naive datetime these fields name, or a rejection naming the value.

    Feeds carry impossible dates (a 31st of February from a bad export, an hour of 24 from
    a midnight rollover), and the constructor's own message names neither the property nor
    the feed, so it is replaced with one that does.
    """
    try:
        return datetime(year, month, day, hour, minute, second)  # noqa: DTZ001 - wall time
    except ValueError as error:
        message = f"{text!r} names no real date and time: {error}"
        raise MalformedValue(message) from error


def _number(part: str | None) -> int:
    return 0 if part is None else int(part)
