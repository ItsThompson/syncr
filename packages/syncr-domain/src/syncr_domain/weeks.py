"""ISO week identity and the week span every downstream figure derives from.

An ISO week is not 168 hours. It starts at a local midnight that resolves against the
zone active on that Monday, which may differ from the zone active on the following
Monday if the user travels mid-week. Because every downstream figure derives from
``span.total_minutes()``, a transition week needs no special case anywhere: a
spring-forward week simply has one hour less discretionary time than the week before it.

The weekday vocabulary is here as well. A weekday is a position inside a week rather than a
template concern, and the week pattern that maps all seven of them is not its only reader:
materializing a day asks which weekday its date is.

Most weeks are 167, 168, or 169 hours, and none of those three is a rule. A zone whose
transition is not an hour gives something else: ``Antarctica/Troll`` shifts two hours, so
its 2026 weeks are 166 and 170, and ``Australia/Lord_Howe`` shifts thirty minutes, so its
weeks are 167.5 and 168.5 and are not a whole number of hours at all. **Read
``total_minutes()``.** A check that enumerates hour counts, or that assumes the span
divides by 60, is wrong for a real user in a real zone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from syncr_domain.errors import DomainError
from syncr_domain.intervals import Interval
from syncr_domain.zones import active_zone, to_instant

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from syncr_domain.zones import Date, ZoneId, ZoneProfile

LOCAL_MIDNIGHT: Final = time(0, 0)

_IDENTIFIER = re.compile(r"\A(?P<year>\d{4})-W(?P<week>\d{2})\Z")

_MONDAY: Final = 1


class IsoWeekError(DomainError):
    """The value names no ISO week."""


class Weekday(StrEnum):
    """One day of the week, named rather than numbered.

    Declared in ISO order, Monday first, so iterating the enum IS that order and nothing
    restates it. Named rather than numbered because the wire and the week-pattern editor both
    read one, and because Monday is ``0`` in ``date.weekday()`` and ``1`` in
    ``date.isoweekday()``: a stored number would be right against one of them and wrong
    against the other.
    """

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


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

    def dates(self) -> tuple[Date, ...]:
        """The seven local dates this week covers, Monday first.

        A week is seven dates whatever its length in minutes, so this is the one place a
        per-date collection is checked for covering the week. ``week_span`` answers the other
        question, how long the week is, and that one needs a zone profile while this does not.
        """
        return tuple(
            date.fromisocalendar(self.year, self.week, weekday)
            for weekday in range(_MONDAY, _MONDAY + len(Weekday))
        )

    def following(self) -> IsoWeek:
        return IsoWeek.containing(self.monday() + timedelta(days=7))

    def preceding(self) -> IsoWeek:
        """The week before this one, derived through the calendar rather than by subtracting one.

        ``2027-W01`` precedes into ``2026-W53`` and ``2026-W01`` into ``2025-W52``, so the week
        number alone does not decide the answer and neither does the ISO year.
        """
        return IsoWeek.containing(self.monday() - timedelta(days=7))

    def __str__(self) -> str:
        return f"{self.year}-W{self.week:02d}"


def longest_consecutive_run(weeks: Iterable[IsoWeek]) -> tuple[IsoWeek, ...]:
    """The longest run of consecutive ISO weeks in ``weeks``, earliest run winning a tie.

    Two raises in this product are counts of consecutive weeks: a repeated pin becomes a template
    promotion, and an item skipped week after week is escalated. Both ask this question and neither
    may answer it differently, because a user reading "four consecutive weeks" on one surface and
    "three" on another has no way to tell which is right. A repeated collision is deliberately NOT
    one of them: its story says "three or more weeks", so it counts distinct weeks instead.

    Consecutive is checked against the week's own successor rather than by counting distinct weeks.
    Weeks 7, 9 and 11 are a repeated behaviour rather than a run, and counting three of them would
    report a pattern from three unrelated weeks. Resolving through :meth:`IsoWeek.following` is also
    what makes a run across a year boundary a run: ``2026-W53`` is followed by ``2027-W01``, so
    neither the week number nor the ISO year alone decides the answer.

    Duplicates collapse, so a week contributing twice is one week of evidence.
    """
    longest: tuple[IsoWeek, ...] = ()
    current: list[IsoWeek] = []
    for week in sorted(set(weeks)):
        if current and current[-1].following() != week:
            current = []
        current.append(week)
        if len(current) > len(longest):
            longest = tuple(current)
    return longest


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


@dataclass(frozen=True, slots=True)
class LocalDay:
    """One of a week's dates, and the span that date occupies as instants."""

    on: Date
    interval: Interval


def local_days(
    iso_week: IsoWeek, zone_by_date: Mapping[Date, ZoneId], span: Interval
) -> tuple[LocalDay, ...]:
    """Each of the week's dates as the span it really occupies, bounded by its own midnight.

    A per-day figure has to be measured against the day the USER had, so a cap or a ledger reads
    this rather than a 24-hour slice of the span: a spring-forward date is 23 hours long and a
    travel boundary makes one 14 hours long. Each date's start resolves against the zone active
    on that date and its end against the next date's, which is what makes both lengths fall out
    with no special case.

    ``span``'s end bounds the last date, because the following Monday's zone is the span's
    business and is not in the mapping. Every day is clipped to the span for the same reason:
    a per-day figure taken over these may not charge a minute the week does not hold.

    ``zone_by_date`` covers the week's seven dates. Every shape that carries the mapping as a
    field validates that through ``plan.require_a_zone_for_every_day``, so a date missing here
    is a caller that built the mapping rather than data that arrived wrong.

    **A date whose bounds do not run forward contributes nothing, and consecutive dates can
    overlap.** Both follow from the offsets rather than from a choice: two dates' midnights are
    24 hours apart plus the difference between their offsets, which spans -14:00 to +14:00, so a
    mid-week move between the extremes moves a midnight backwards past the one before it. The
    day that cannot be built is dropped rather than reordered, because which date owns an instant
    is what the mapping states; and a placement inside an overlap is charged to both dates, which
    is the safe direction for a cap.
    """
    dates = iso_week.dates()
    midnights = [to_instant(LOCAL_MIDNIGHT, on, zone_by_date[on]) for on in dates]
    bounds = (*midnights, span.end)
    days = []
    for on, opens, closes in zip(dates, midnights, bounds[1:], strict=True):
        if opens >= closes:
            continue
        inside = Interval(opens, closes).clipped_to(span)
        if inside is not None:
            days.append(LocalDay(on=on, interval=inside))
    return tuple(days)


def active_zone_by_date(iso_week: IsoWeek, profile: ZoneProfile) -> dict[Date, ZoneId]:
    """The zone active on each of the week's seven dates.

    A week is not one zone. A travel override taken mid-week makes the days either side of it
    resolve their wall times against different offsets, so every shape that carries a week's
    wall-time resolutions carries this mapping rather than a single zone.

    Stated here, beside the span, because the two are the same question asked twice: the span
    resolves the two Mondays that bound the week and this resolves the days inside it.
    """
    return {on: active_zone(profile, on) for on in iso_week.dates()}
