"""Google's two time grammars, read against exactly one parser's rules.

This module exists because syncr and Python's own ISO parser do not agree about what a timestamp
is, and Google's contract is a third answer. Where two parsers read one string, the divergence is
one defect per rule they disagree on, so the shape is validated by ONE gate and the arithmetic runs
only on what that gate accepted.

The gate is a pattern for the form RFC 3339 requires and Google documents: four-digit year,
extended form, seconds present, and **an offset that is not optional**. Measured against Python
3.12's ``datetime.fromisoformat``, which is what does the arithmetic, that closes divergences in
both directions:

| Value | RFC 3339 | ``fromisoformat`` | Here |
| --- | --- | --- | --- |
| ``2026-02-09T09:00:00`` | illegal, no offset | accepted, NAIVE | refused |
| ``20260209T090000Z`` | illegal, basic form | accepted | refused |
| ``2026-W07-1T09:00:00Z`` | illegal, week form | accepted | refused |
| ``2026-02-09T09:00:00+0000`` | illegal, no colon | accepted | refused |
| ``2026-02-09t09:00:00z`` | legal, lower case | **raises** | accepted |
| ``2026-02-09T23:59:60Z`` | legal, leap second | **raises** | refused, and says so |
| ``...09:00:00.123456789Z`` | legal, nine digits | accepted, truncated | accepted |

A naive datetime is the dangerous one, and it is why the offset is required rather than defaulted.
Silently reading one as UTC places an event up to thirteen hours from where the provider put it, and
nothing downstream can tell that from a correct answer.

The two accepted divergences are deliberate. Lower case is legal in the standard and refusing it
would lose an event over a letter. A leap second is legal too, and it is refused rather than clamped
because the panel can then say what was wrong with the value; Google smears leap seconds and emits
none, so this is a contract-change guard rather than a live case.

**Nothing here raises.** Every answer is a value, because the adapter has to report a rejection with
a reason on the source rather than lose a whole calendar to one bad field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Final

from syncr_api.calendars.config import MALFORMED_VALUE, MAX_EVENT_DAYS, MISSING_DURATION
from syncr_api.calendars.day_spans import local_day_span
from syncr_domain.errors import DomainError
from syncr_domain.intervals import Interval, as_instant

if TYPE_CHECKING:
    from syncr_api.calendars.config import RejectionKind
    from syncr_api.calendars.google_payloads import GoogleTimePayload
    from syncr_domain.zones import ZoneProfile

# How many characters a timestamp may spend. Google's own longest form is 29; the fractional part
# is the only unbounded field, and a value this wide is a contract change rather than a timestamp.
# Bounded before the pattern runs, because the length is the cheapest thing to check.
MAX_TIMESTAMP_LENGTH: Final = 64

# RFC 3339's `date-time`, restricted to what Google documents: extended form, seconds present,
# optional fraction, and a mandatory offset. Case-insensitive on the two letters the standard
# allows either way.
_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")
# RFC 3339's `full-date`. The extended form only, so neither the basic nor the week form reaches
# the parser that would accept both.
_FULL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True, slots=True)
class ReadSpan:
    """The span an event occupies, with every zone question already answered."""

    interval: Interval
    all_day: bool


@dataclass(frozen=True, slots=True)
class UnreadableSpan:
    """Why an event produced no span, in the vocabulary the source's panel groups by."""

    kind: RejectionKind
    detail: str


type SpanReading = ReadSpan | UnreadableSpan


def read_span(
    start: GoogleTimePayload | None, end: GoogleTimePayload | None, *, profile: ZoneProfile
) -> SpanReading:
    """The interval this event occupies, or why it cannot be read.

    An all-day event's ``end.date`` is exclusive, exactly as ICS's ``DTEND`` is, and its span is
    whole LOCAL days in the zone the user is in on each date. A timed event's offset is
    authoritative, so ``timeZone`` is read and not consulted: it names the zone the event was
    authored in, which matters to recurrence expansion, and Google expands recurrence itself.
    """
    if start is None or end is None:
        return UnreadableSpan(
            MISSING_DURATION,
            "Google returned an event with no start or no end, and syncr cannot reason about "
            "occupancy without a duration",
        )
    if start.date_time is not None and end.date_time is not None:
        return _timed_span(start.date_time, end.date_time)
    if start.date is not None and end.date is not None:
        return _all_day_span(start.date, end.date, profile=profile)
    return UnreadableSpan(
        MALFORMED_VALUE,
        "Google returned an event whose start and end are stated in different forms, one a date "
        "and one a date-time, so the span it occupies is ambiguous",
    )


def _timed_span(start: str, end: str) -> SpanReading:
    """A timed event, from two instants the provider stated absolutely."""
    first = read_instant(start)
    if isinstance(first, UnreadableSpan):
        return first
    last = read_instant(end)
    if isinstance(last, UnreadableSpan):
        return last
    return _bounded(first, last, all_day=False)


def _all_day_span(start: str, end: str, *, profile: ZoneProfile) -> SpanReading:
    """An all-day event, from two dates whose second is exclusive."""
    first = read_date(start)
    if isinstance(first, UnreadableSpan):
        return first
    last = read_date(end)
    if isinstance(last, UnreadableSpan):
        return last
    days = (last - first).days
    if days < 1:
        return UnreadableSpan(
            MISSING_DURATION,
            f"an all-day event ending on {end} does not outlast its start on {start}, so it "
            "occupies no day at all",
        )
    if days > MAX_EVENT_DAYS:
        return UnreadableSpan(
            MALFORMED_VALUE,
            f"an all-day event spanning {days} days is longer than the {MAX_EVENT_DAYS} days "
            "syncr can place",
        )
    try:
        return ReadSpan(interval=local_day_span(first, days, profile), all_day=True)
    except (DomainError, OverflowError, ValueError) as unrepresentable:
        # The magnitudes are bounded above, so this is the net rather than the guard: a zone whose
        # transition arithmetic cannot represent a bound must be a rejection, not an escape.
        return UnreadableSpan(
            MALFORMED_VALUE,
            f"an all-day event on {start} names a day syncr cannot resolve to instants: "
            f"{type(unrepresentable).__name__}",
        )


def read_instant(value: str) -> datetime | UnreadableSpan:
    """The instant an RFC 3339 date-time names, or why it names none."""
    if len(value) > MAX_TIMESTAMP_LENGTH:
        return UnreadableSpan(
            MALFORMED_VALUE,
            f"Google returned a timestamp of {len(value)} characters, and no timestamp is longer "
            f"than {MAX_TIMESTAMP_LENGTH}",
        )
    if _DATE_TIME.match(value) is None:
        return UnreadableSpan(
            MALFORMED_VALUE,
            "Google returned a timestamp that is not an RFC 3339 date-time with an offset, which "
            "is the form its own contract states",
        )
    try:
        # Upper-cased because `fromisoformat` refuses the lower-case separator and suffix the
        # standard permits. The pattern above admits no other letter, so the whole value is safe
        # to fold: there is nothing else in it a case change could alter.
        return as_instant(datetime.fromisoformat(value.upper()))
    except (ValueError, DomainError, OverflowError) as unreadable:
        # Reachable from a value the pattern accepts: a leap second, an impossible day, or a
        # year the arithmetic cannot represent. Each is a stated rejection rather than a raise
        # out of a fetch.
        return UnreadableSpan(
            MALFORMED_VALUE,
            f"Google returned a timestamp that is well formed and not a real instant: "
            f"{type(unreadable).__name__}",
        )


def read_date(value: str) -> date | UnreadableSpan:
    """The date an RFC 3339 full-date names, or why it names none."""
    if len(value) > MAX_TIMESTAMP_LENGTH:
        return UnreadableSpan(
            MALFORMED_VALUE,
            f"Google returned a date of {len(value)} characters, and no date is longer than "
            f"{MAX_TIMESTAMP_LENGTH}",
        )
    if _FULL_DATE.match(value) is None:
        return UnreadableSpan(
            MALFORMED_VALUE,
            "Google returned a date that is not an RFC 3339 full-date, which is the form its own "
            "contract states",
        )
    try:
        return date.fromisoformat(value)
    except ValueError as unreadable:
        return UnreadableSpan(
            MALFORMED_VALUE,
            f"Google returned a date that is well formed and not a real day: "
            f"{type(unreadable).__name__}",
        )


def _bounded(start: datetime, end: datetime, *, all_day: bool) -> SpanReading:
    """The interval between two instants, once it is one syncr can hold.

    An interval needs ``start < end``, so a zero-length event is a rejection rather than an
    exception: Google permits one, and syncr cannot reason about occupancy that occupies nothing.
    """
    if (end - start).days > MAX_EVENT_DAYS:
        return UnreadableSpan(
            MALFORMED_VALUE,
            f"an event spanning {(end - start).days} days is longer than the {MAX_EVENT_DAYS} "
            "days syncr can place",
        )
    try:
        return ReadSpan(interval=Interval(start, end), all_day=all_day)
    except DomainError:
        return UnreadableSpan(
            MISSING_DURATION,
            "Google returned an event whose end does not follow its start, so it occupies no time "
            "and syncr cannot reason about it as occupancy",
        )
