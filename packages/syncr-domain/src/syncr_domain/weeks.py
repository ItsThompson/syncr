"""ISO week identity and the week span every downstream figure derives from.

An ISO week is not 168 hours. It is 167, 168, or 169, and it starts at a local
midnight that resolves against the zone active on that Monday, which may differ from
the zone active on the following Monday if the user travels mid-week. Because every
downstream figure derives from ``span.total_minutes()``, a transition week needs no
special case anywhere: a spring-forward week simply has one hour less discretionary
time than the week before it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError
from syncr_domain.intervals import Interval
from syncr_domain.zones import active_zone, to_instant

if TYPE_CHECKING:
    from syncr_domain.zones import Date, ZoneProfile

LOCAL_MIDNIGHT: Final = time(0, 0)

_IDENTIFIER = re.compile(r"\A(?P<year>\d{4})-W(?P<week>\d{2})\Z")

_MONDAY: Final = 1


class IsoWeekError(DomainError):
    """The value names no ISO week."""


@dataclass(frozen=True, order=True)
class IsoWeek:
    """One ISO week, identified as ``2026-W07`` on the wire and in logs.

    ``year`` is the ISO year, which differs from the calendar year in the days either
    side of January 1st.
    """

    year: int
    week: int

    def __post_init__(self) -> None:
        try:
            date.fromisocalendar(self.year, self.week, _MONDAY)
        except ValueError as error:
            raise IsoWeekError(f"{self.year}-W{self.week:02d} is not an ISO week") from error

    @classmethod
    def parse(cls, value: str) -> IsoWeek:
        matched = _IDENTIFIER.match(value)
        if matched is None:
            raise IsoWeekError(f"{value!r} is not an ISO week identifier such as '2026-W07'")
        return cls(int(matched["year"]), int(matched["week"]))

    @classmethod
    def containing(cls, on: Date) -> IsoWeek:
        year, week, _ = on.isocalendar()
        return cls(year, week)

    def monday(self) -> Date:
        return date.fromisocalendar(self.year, self.week, _MONDAY)

    def following(self) -> IsoWeek:
        return IsoWeek.containing(self.monday() + timedelta(days=7))

    def __str__(self) -> str:
        return f"{self.year}-W{self.week:02d}"


def week_span(iso_week: IsoWeek, profile: ZoneProfile) -> Interval:
    """From local Monday 00:00 to local Monday 00:00 of the following week.

    Monday's zone bounds the start and the following Monday's zone bounds the end, so
    a travel override taking effect mid-week shortens or lengthens the span by the
    offset difference. Days inside resolve their own zone.
    """
    monday = iso_week.monday()
    next_monday = iso_week.following().monday()
    return Interval(
        to_instant(LOCAL_MIDNIGHT, monday, active_zone(profile, monday)),
        to_instant(LOCAL_MIDNIGHT, next_monday, active_zone(profile, next_monday)),
    )
