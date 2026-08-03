"""Reading one ``VEVENT`` into the values building an event needs, or rejecting it.

Two of the ICS ingest table's semantic rows are decided here, and both are decided by
refusing to guess.

**An event with neither ``DTEND`` nor ``DURATION`` is rejected.** syncr reasons about
occupancy, and an event with no end states none. Any default would be a claim about the
user's time that the publisher did not make.

**A duration is measured between resolved instants, not between wall clocks.** A feed can
declare a start in one zone and an end in another, and subtracting those wall times answers
a number that means nothing. Resolving both first also catches the event whose ``DTEND``
precedes its ``DTSTART``, which is a real export defect and would otherwise reach interval
construction as a crash rather than as a stated rejection.

An all-day event carries a DAY COUNT rather than a span, because a day is 23, 24, or 25 hours
depending on the date, and the span has to be recomputed per occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.calendars.ics_errors import MalformedValue, MissingDuration
from syncr_api.calendars.ics_lines import unescape
from syncr_api.calendars.ics_recurrence import Recurrence
from syncr_api.calendars.ics_times import ONE_DAY, resolve
from syncr_api.calendars.ics_values import parse_duration, parse_sequence, parse_time

if TYPE_CHECKING:
    from datetime import timedelta

    from syncr_api.calendars.ics_lines import Component, ContentLine
    from syncr_api.calendars.ics_values import IcsTime
    from syncr_domain.zones import ZoneProfile

CANCELLED = "CANCELLED"

# What an event with no SUMMARY is called. A feed that omits one still states occupancy, so
# the event is kept; a title is how the user recognizes it, not how syncr places it.
UNTITLED = "(untitled)"

# RFC 5545 makes DTEND exclusive, so a one-day all-day event's DTEND is the FOLLOWING date. A
# feed that omits it means one day rather than no duration, which is the one place a default
# is right: the standard states it.
ONE_WHOLE_DAY = 1


@dataclass(frozen=True, slots=True)
class EventComponent:
    """One ``VEVENT`` reduced to what expansion and event building read.

    ``span`` and ``days`` are exclusive: a timed event has an absolute span, an all-day event
    has a whole-day count. Exactly one is set, which is what lets the builder ask ``all_day``
    once rather than carrying a nullable in both directions.
    """

    component: Component
    uid: str
    title: str
    location: str | None
    sequence: int
    start: IcsTime
    span: timedelta | None
    days: int | None
    recurrence: Recurrence
    replaces: IcsTime | None
    cancelled: bool

    @property
    def all_day(self) -> bool:
        return self.start.all_day

    @property
    def whole_days(self) -> int:
        return self.days or ONE_WHOLE_DAY

    @property
    def absolute_span(self) -> timedelta:
        if self.span is None:
            message = "a timed event reached expansion with no duration"
            raise MalformedValue(message)
        return self.span


def read_component(component: Component, profile: ZoneProfile) -> EventComponent:
    """One component's values, or a rejection naming the property that would not read."""
    uid = text_of(component, "UID")
    if uid is None:
        message = "the component carries no UID, so syncr cannot reconcile it against a source"
        raise MalformedValue(message)
    start_line = component.first("DTSTART")
    if start_line is None:
        message = "the component carries no DTSTART, so syncr cannot tell when it happens"
        raise MalformedValue(message)
    start = parse_time(start_line.value, params=start_line.params)
    span, days = _extent(start, component, profile)
    replaced = component.first("RECURRENCE-ID")
    sequence = component.first("SEQUENCE")
    return EventComponent(
        component=component,
        uid=uid,
        title=text_of(component, "SUMMARY") or UNTITLED,
        location=text_of(component, "LOCATION"),
        sequence=0 if sequence is None else parse_sequence(sequence.value),
        start=start,
        span=span,
        days=days,
        recurrence=_recurrence(component),
        replaces=None if replaced is None else parse_time(replaced.value, params=replaced.params),
        cancelled=(text_of(component, "STATUS") or "").upper() == CANCELLED,
    )


def text_of(component: Component, name: str) -> str | None:
    """One TEXT property's value, unescaped, or ``None`` when it is absent or blank."""
    line = component.first(name)
    return None if line is None else unescape(line.value).strip() or None


def _extent(
    start: IcsTime, component: Component, profile: ZoneProfile
) -> tuple[timedelta | None, int | None]:
    """How long this event lasts: a whole-day count for an all-day event, else a span."""
    end = _time_of(component.first("DTEND"))
    duration = _duration_of(component.first("DURATION"))
    if start.all_day:
        return None, _whole_days(start, end, duration)
    if duration is not None:
        return duration, None
    if end is None:
        message = (
            "the event has neither DTEND nor DURATION, and syncr cannot reason about "
            "occupancy without a duration"
        )
        raise MissingDuration(message)
    if end.all_day:
        message = "the event starts at a time and ends on a date, so its duration is unstated"
        raise MalformedValue(message)
    span = resolve(end, profile) - resolve(start, profile)
    if span.total_seconds() <= 0:
        message = f"the event's DTEND is {span} from its DTSTART, so it occupies nothing"
        raise MalformedValue(message)
    return span, None


def _whole_days(start: IcsTime, end: IcsTime | None, duration: timedelta | None) -> int:
    """How many local days an all-day event covers, counting at least one."""
    if end is not None:
        return max((end.on - start.on) // ONE_DAY, ONE_WHOLE_DAY)
    if duration is not None:
        return max(duration.days, ONE_WHOLE_DAY)
    return ONE_WHOLE_DAY


def _recurrence(component: Component) -> Recurrence:
    rule = component.first("RRULE")
    return Recurrence(
        rule_text=None if rule is None else rule.value.strip(),
        extra_dates=_times(component, "RDATE"),
        excluded=_times(component, "EXDATE"),
    )


def _times(component: Component, name: str) -> tuple[IcsTime, ...]:
    """Every value of a date-list property, as wall times.

    ``EXDATE`` and ``RDATE`` may repeat AND may carry several comma-separated values on one
    line. Publishers use both forms, and one that used both at once would lose half its
    exclusions to a reading that handled only the other.
    """
    return tuple(
        parse_time(value, params=line.params)
        for line in component.all_values(name)
        for value in line.value.split(",")
        if value.strip()
    )


def _time_of(line: ContentLine | None) -> IcsTime | None:
    return None if line is None else parse_time(line.value, params=line.params)


def _duration_of(line: ContentLine | None) -> timedelta | None:
    return None if line is None else parse_duration(line.value)
