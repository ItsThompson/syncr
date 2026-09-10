"""``hostile_ics``: feed bodies drawn from what real publishers actually emit.

Every row of the ICS ingest table appears somewhere in this corpus, and each body
carries the quirks of ONE publisher rather than a synthetic mixture, because a publisher's
defects come in sets: a Celcat timetable folds and uses a named zone, a published Outlook
calendar sends Windows zone names and LF line endings, an assessments feed sends whole days.
Mixing them into one file would test a feed nobody publishes.

Three further bodies are not any one publisher's: an empty feed, a rule that expands without
end, and one that nests without end. Each is a shape a reader has to survive rather than a
shape a reader has to understand. :data:`HOSTILE_MAGNITUDES` is a fourth kind again: a matrix of
extreme NUMBERS, because a value that parses perfectly can still overflow the arithmetic that would
place it, and no amount of grammar catches that.

**These bodies carry no expected figures.** A test that read its assertions from the fixture
would assert the fixture rather than the adapter. Every expected instant and count is written
out by hand in the test that makes the claim.

The dates sit in February 2026, the same period the repository's other fixtures use, so a
question about a plan and a question about a feed can be asked about one week. Two bodies sit
elsewhere because a real zone transition is what they are about, and those dates are not the
repository's to choose.
"""

from __future__ import annotations

from typing import Final

from syncr_api.calendars.config import MAX_EVENT_DAYS
from tests.ics_construction_sites import (
    AT_INT_CONVERSION,
    PADDED_PAST_INT_CONVERSION,
    PAST_INT_CONVERSION,
)

# A university timetable, Celcat-style. CRLF throughout, a folded SUMMARY, a named TZID, a
# weekly RRULE whose UNTIL is in UTC while DTSTART is not (which is what the standard
# requires and what dateutil refuses to expand without conversion), an EXDATE for reading
# week, an escaped comma in LOCATION, and a RECURRENCE-ID override moving one week's lecture
# by an hour into a different room.
UNIVERSITY_TIMETABLE: Final = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Celcat//Timetable//EN\r\n"
    "CALSCALE:GREGORIAN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:celcat-CS3009-LEC-01@example.ac.uk\r\n"
    "DTSTAMP:20260115T121500Z\r\n"
    "SEQUENCE:0\r\n"
    "SUMMARY:CS3009 Advanced Computer Architecture - Lecture (Group\r\n"
    "  A)\r\n"
    "LOCATION:Block MD\\, room MD108\r\n"
    "DTSTART;TZID=Europe/London:20260202T090000\r\n"
    "DTEND;TZID=Europe/London:20260202T110000\r\n"
    "RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20260427T085959Z\r\n"
    "EXDATE;TZID=Europe/London:20260216T090000\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:celcat-CS3009-LEC-01@example.ac.uk\r\n"
    "DTSTAMP:20260206T094500Z\r\n"
    "SEQUENCE:2\r\n"
    "RECURRENCE-ID;TZID=Europe/London:20260209T090000\r\n"
    "SUMMARY:CS3009 Advanced Computer Architecture - Lecture (Group A)\r\n"
    "LOCATION:Block BC\\, room BC-01-014\r\n"
    "DTSTART;TZID=Europe/London:20260209T100000\r\n"
    "DTEND;TZID=Europe/London:20260209T120000\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:celcat-CS3009-LAB-01@example.ac.uk\r\n"
    "DTSTAMP:20260115T121500Z\r\n"
    "SUMMARY:CS3009 Lab\r\n"
    "DTSTART;TZID=Europe/London:20260210T140000\r\n"
    "DURATION:PT1H30M\r\n"
    "RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=6\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

# An assessments feed. Whole-day deadlines with VALUE=DATE, one spanning three days with an
# exclusive DTEND, one with no DTEND at all (which the standard reads as a single day), and
# one timed component with neither DTEND nor DURATION, which is the row syncr rejects.
ASSESSMENTS_FEED: Final = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//example.ac.uk//Assessments//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:assessment-CS3009-CW1@example.ac.uk\r\n"
    "SUMMARY:CS3009 Coursework 1 due\r\n"
    "DTSTART;VALUE=DATE:20260213\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:assessment-CS3012-EXAM-WINDOW@example.ac.uk\r\n"
    "SUMMARY:CS3012 exam window\r\n"
    "DTSTART;VALUE=DATE:20260217\r\n"
    "DTEND;VALUE=DATE:20260220\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:assessment-CS3020-VIVA@example.ac.uk\r\n"
    "SUMMARY:CS3020 viva - time to be confirmed\r\n"
    "DTSTART;TZID=Europe/London:20260219T140000\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

# A published Outlook calendar. LF-only line endings, Windows zone names rather than IANA
# keys, one component naming a zone no table maps, one cancelled master, one cancelled
# OCCURRENCE of a live series, a cancelled series that kept one of its overrides, and a duplicate
# UID pair produced by an export covering two overlapping windows: the same meeting at two SEQUENCE
# values, the later of which moved it.
PUBLISHED_OUTLOOK: Final = (
    "BEGIN:VCALENDAR\n"
    "VERSION:2.0\n"
    "PRODID:Microsoft Exchange Server 2010\n"
    "BEGIN:VEVENT\n"
    "UID:AAMkAGI2-standup@example.com\n"
    "SUMMARY:Placement standup\n"
    "DTSTART;TZID=GMT Standard Time:20260209T081500\n"
    "DTEND;TZID=GMT Standard Time:20260209T083000\n"
    "RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR\n"
    "END:VEVENT\n"
    "BEGIN:VEVENT\n"
    "UID:AAMkAGI2-review@example.com\n"
    "SUMMARY:Sprint review\n"
    "SEQUENCE:0\n"
    "DTSTART;TZID=GMT Standard Time:20260212T130000\n"
    "DTEND;TZID=GMT Standard Time:20260212T140000\n"
    "END:VEVENT\n"
    "BEGIN:VEVENT\n"
    "UID:AAMkAGI2-review@example.com\n"
    "SUMMARY:Sprint review\n"
    "SEQUENCE:3\n"
    "DTSTART;TZID=GMT Standard Time:20260212T150000\n"
    "DTEND;TZID=GMT Standard Time:20260212T160000\n"
    "END:VEVENT\n"
    "BEGIN:VEVENT\n"
    "UID:AAMkAGI2-offsite@example.com\n"
    "SUMMARY:Team offsite\n"
    "DTSTART;TZID=Cheshire Standard Time:20260218T090000\n"
    "DTEND;TZID=Cheshire Standard Time:20260218T170000\n"
    "END:VEVENT\n"
    "BEGIN:VEVENT\n"
    "UID:AAMkAGI2-cancelled@example.com\n"
    "SUMMARY:Cancelled: budget sign-off\n"
    "STATUS:CANCELLED\n"
    "DTSTART;TZID=GMT Standard Time:20260211T110000\n"
    "DTEND;TZID=GMT Standard Time:20260211T120000\n"
    "END:VEVENT\n"
    # One occurrence of the standup, cancelled the way Exchange expresses a deleted occurrence: a
    # RECURRENCE-ID naming it, on a component whose STATUS is CANCELLED, while the master stays
    # live. Read as the absence of an override, the master's rule places 16 February anyway.
    "BEGIN:VEVENT\n"
    "UID:AAMkAGI2-standup@example.com\n"
    "RECURRENCE-ID;TZID=GMT Standard Time:20260216T081500\n"
    "SEQUENCE:1\n"
    "STATUS:CANCELLED\n"
    "SUMMARY:Placement standup\n"
    "DTSTART;TZID=GMT Standard Time:20260216T081500\n"
    "DTEND;TZID=GMT Standard Time:20260216T083000\n"
    "END:VEVENT\n"
    # A cancelled series that kept one of its overrides, which an export cancelling a whole meeting
    # while its moved occurrence is still in the window produces. The override has nothing live to
    # attach to: placing it would turn the cancellation back into occupancy.
    "BEGIN:VEVENT\n"
    "UID:AAMkAGI2-workshop@example.com\n"
    "SUMMARY:Cancelled: onboarding workshop\n"
    "STATUS:CANCELLED\n"
    "DTSTART;TZID=GMT Standard Time:20260217T090000\n"
    "DTEND;TZID=GMT Standard Time:20260217T110000\n"
    "RRULE:FREQ=WEEKLY\n"
    "END:VEVENT\n"
    "BEGIN:VEVENT\n"
    "UID:AAMkAGI2-workshop@example.com\n"
    "RECURRENCE-ID;TZID=GMT Standard Time:20260217T090000\n"
    "SUMMARY:Onboarding workshop\n"
    "DTSTART;TZID=GMT Standard Time:20260217T140000\n"
    "DTEND;TZID=GMT Standard Time:20260217T160000\n"
    "END:VEVENT\n"
    "END:VCALENDAR\n"
)

# A holiday feed. Floating whole days with no TZID at all, a yearly rule, and an RDATE
# adding one extra day the rule does not produce.
HOLIDAY_FEED: Final = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//example.org//Holidays//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:holiday-valentines@example.org\r\n"
    "SUMMARY:Valentine's Day\r\n"
    "DTSTART;VALUE=DATE:20200214\r\n"
    "RRULE:FREQ=YEARLY\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:holiday-half-term@example.org\r\n"
    "SUMMARY:School half term\r\n"
    "DTSTART;VALUE=DATE:20260216\r\n"
    "DTEND;VALUE=DATE:20260221\r\n"
    "RDATE;VALUE=DATE:20260601\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

# A feed with no events at all, which is what a publisher answers before a term is loaded. A
# valid feed reporting zero events must read as a success rather than as a failure.
EMPTY_FEED: Final = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//example.ac.uk//Timetable//EN\r\nEND:VCALENDAR\r\n"
)

# The two container names :func:`nested_feed` alternates between. Neither is `VEVENT`, so the buried
# event's own `BEGIN` cannot be read as repeating its wrapper's name.
_NESTING_NAMES: Final = ("VCALENDAR", "VTIMEZONE")

# A rule with neither COUNT nor UNTIL at a frequency no calendar publisher means. Bounded
# expansion is what stops it holding a worker tick open.
RUNAWAY_RECURRENCE: Final = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:runaway@example.org\r\n"
    "SUMMARY:Broken export\r\n"
    "DTSTART:20100101T000000Z\r\n"
    "DTEND:20100101T000100Z\r\n"
    "RRULE:FREQ=SECONDLY\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

# A rule that stays inside the per-series step bound while producing more events than syncr reads
# from one feed. One component, so nothing about its size is visible from the component count.
OVERRUNNING_RECURRENCE: Final = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:every-minute@example.org\r\n"
    "SUMMARY:Minute by minute\r\n"
    "DTSTART:20260209T000000Z\r\n"
    "DTEND:20260209T000100Z\r\n"
    "RRULE:FREQ=MINUTELY\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def nested_feed(depth: int) -> str:
    """A feed in which the one ``VEVENT`` sits at nesting depth ``depth``.

    ``depth`` counts the event itself, so ``nested_feed(3)`` is the shape a real feed has:
    a container holding a container holding the event. Stated that way round so a caller can write
    the bound it is testing rather than the bound minus one.

    The wrappers ALTERNATE between two component names, because a repeated ``BEGIN`` closes the
    component of the same name it repeats: RFC 5545 defines no component that contains another of
    its own kind, so a repeat means a missing ``END`` rather than nesting. A same-name fixture
    would therefore build a flat feed and test the sibling rule instead of the depth bound.

    A function rather than a constant, because the depth that matters is the one past the reader's
    own bound and several hundred literal lines would say less than the number does. A publisher
    controls nesting depth as much as it controls anything else in a body, so a reader that walked
    it recursively would turn a 21 KB feed into a ``RecursionError`` and take a worker tick with it.
    """
    wrappers = [_NESTING_NAMES[level % len(_NESTING_NAMES)] for level in range(max(depth - 1, 0))]
    opens = "".join(f"BEGIN:{name}\r\n" for name in wrappers)
    closes = "".join(f"END:{name}\r\n" for name in reversed(wrappers))
    event = (
        "BEGIN:VEVENT\r\n"
        "UID:buried@example.org\r\n"
        "SUMMARY:Buried deep\r\n"
        "DTSTART:20260209T090000Z\r\n"
        "DTEND:20260209T100000Z\r\n"
        "END:VEVENT\r\n"
    )
    return f"{opens}{event}{closes}"


# The depth a recursive reader failed at, kept as a corpus member so the no-raise property is
# asserted over it like every other body.
DEEPLY_NESTED: Final = nested_feed(1_000)


def _one_event(*lines: str) -> str:
    """A well-formed calendar holding one event with the given property lines."""
    body = "".join(f"{line}\r\n" for line in lines)
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        f"BEGIN:VEVENT\r\nUID:magnitude@example.org\r\nSUMMARY:Extreme\r\n{body}"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )


TIMED_START: Final = "DTSTART:20260209T090000Z"
ZONED_START: Final = "DTSTART;TZID=Pacific/Kiritimati:20260209T090000"
DAY_START: Final = "DTSTART;VALUE=DATE:20260209"

# The axes a magnitude body is crossed from.
#
# A feed states NUMBERS as well as syntax, and a number that parses perfectly can still overflow the
# arithmetic that places it or the conversion that reads it. `DTEND;VALUE=DATE:99991231` is how some
# publishers express an open-ended all-day event and an over-long `DURATION` is a routine broken
# export, so neither needs malice and neither is a syntax error.
#
# CROSSED rather than listed, and that distinction is the whole point: a list holds the instances
# somebody found, while a cross product includes the body nobody would have thought to write. The
# values that decide an outcome are derived from a bound this code owns or from the interpreter's
# own conversion limit, so the corpus follows either when it moves.
_STARTS: Final[dict[str, str]] = {
    "a timed start": TIMED_START,
    "a zoned start": ZONED_START,
    "a whole-day start": DAY_START,
    "a start at the first representable date": "DTSTART;VALUE=DATE:00010101",
    "a zoned start at the first representable date": (
        "DTSTART;TZID=Pacific/Midway:00010101T000000"
    ),
    "a zoned start at the last representable date": (
        "DTSTART;TZID=Pacific/Kiritimati:99991231T235959"
    ),
}

_EXTREMES: Final[dict[str, tuple[str, ...]]] = {
    # Durations, at and past both bounds: the digit count `int()` will convert, and the day count
    # syncr will place.
    "a duration past the conversion limit": (f"DURATION:PT{PAST_INT_CONVERSION}S",),
    "a duration at the conversion limit": (f"DURATION:PT{AT_INT_CONVERSION}S",),
    "a duration padded past the conversion limit": (f"DURATION:PT{PADDED_PAST_INT_CONVERSION}S",),
    "a duration past the day bound": (f"DURATION:P{MAX_EVENT_DAYS + 1}D",),
    "a duration at the day bound": (f"DURATION:P{MAX_EVENT_DAYS}D",),
    "a duration mixing units past the bound": (f"DURATION:P{MAX_EVENT_DAYS}DT24H",),
    "a duration in weeks past the constructor": ("DURATION:P999999999W",),
    "a legitimate duration": ("DURATION:PT1H",),
    # Whole-day ranges, which reach the day count through DTEND rather than through DURATION.
    "a whole-day range to the end of time": ("DTEND;VALUE=DATE:99991231",),
    "a whole-day range of one day": ("DTEND;VALUE=DATE:20260210",),
    # Recurrence, where the magnitude reaches dateutil rather than a constructor here.
    "an until past the end of time": (
        "DURATION:PT1H",
        "RRULE:FREQ=DAILY;UNTIL=99991231T235959Z",
    ),
    "an interval past the conversion limit": (
        "DURATION:PT1H",
        f"RRULE:FREQ=DAILY;INTERVAL={PAST_INT_CONVERSION}",
    ),
    # The DEGENERATE end of the same axis, which is the end an exporter's sign slip reaches. A zero
    # interval never advances, so the parent-enforced deadline has to stop its expansion.
    "an interval of zero": ("DURATION:PT1H", "RRULE:FREQ=DAILY;INTERVAL=0"),
    "a padded interval of zero": ("DURATION:PT1H", "RRULE:FREQ=DAILY;INTERVAL=00"),
    "a negative interval": ("DURATION:PT1H", "RRULE:FREQ=DAILY;INTERVAL=-1"),
    "a negative monthly interval": ("DURATION:PT1H", "RRULE:FREQ=MONTHLY;INTERVAL=-1"),
    "a count of zero": ("DURATION:PT1H", "RRULE:FREQ=DAILY;COUNT=0"),
    # A BYDAY ordinal past the weeks a period holds. dateutil indexes its own weekday mask with it
    # and walks off the end, raising IndexError: not a value error, so not in the caught set.
    "a byday ordinal past the period": ("DURATION:PT1H", "RRULE:FREQ=MONTHLY;BYDAY=8MO"),
    "a byday ordinal far past the period": ("DURATION:PT1H", "RRULE:FREQ=YEARLY;BYDAY=99MO"),
    # The accepting mirror on the same axis: one member of the list lands, so the rule yields and
    # must not be refused.
    "a setpos list where only one member lands": (
        "DURATION:PT1H",
        "RRULE:FREQ=HOURLY;BYMINUTE=0,30;BYSETPOS=1,5",
    ),
    "a rule value past the readable width": (
        "DURATION:PT1H",
        f"RRULE:FREQ=DAILY;COUNT={PADDED_PAST_INT_CONVERSION}",
    ),
    # A separator `int` accepts and `str.isdecimal` refuses. The corpus crossed padding with a rule
    # value and never SEPARATORS, which is how a readability predicate that disagreed with the
    # library's own conversion shipped twice.
    "a set member written with a digit separator": (
        "DURATION:PT1H",
        "RRULE:FREQ=HOURLY;BYMINUTE=0,2_0;BYSETPOS=2",
    ),
    # Values outside the range RFC 5545 gives their property. Each can never match, so the rule
    # yields nothing while dateutil walks looking for it: one measured past twenty minutes.
    "a month day no month reaches": (
        "DURATION:PT1H",
        "RRULE:FREQ=SECONDLY;BYMONTHDAY=53;BYHOUR=2",
    ),
    # Whitespace inside a rule value. dateutil splits the value on any whitespace and reads each
    # token as its own content line, so a space smuggles a second RRULE past guards that split on
    # ";". No body carried whitespace inside a rule before, which is why nine passes agreed with
    # guards that read a different grammar from the expander they guard.
    "a second rule hidden behind a space": (
        "DURATION:PT1H",
        "RRULE:FREQ=DAILY INTERVAL=0;FREQ=DAILY",
    ),
    "a second rule hidden behind a tab": ("DURATION:PT1H", "RRULE:FREQ=DAILY\tINTERVAL=0"),
    "a rule name split by a space": ("DURATION:PT1H", "RRULE:FREQ=DAILY;INT ERVAL=0"),
    # A property NAME carrying a colon. dateutil splits `name:value` before it reads properties, so
    # each of these is a second content line: a rule, an exclusion rule, a date, or a start that
    # overrides the one syncr resolved. The exclusion form is silent rather than slow.
    "a second rule behind a colon": (
        "DURATION:PT1H",
        "RRULE:RRULE:FREQ=SECONDLY;BYSETPOS=300",
    ),
    "an exclusion rule behind a colon": ("DURATION:PT1H", "RRULE:EXRULE:FREQ=DAILY;COUNT=3"),
    "a date behind a colon": ("DURATION:PT1H", "RRULE:RDATE:20260212T090000Z"),
    "a start behind a colon": ("DURATION:PT1H", "RRULE:DTSTART:20260101T000000Z;FREQ=DAILY"),
    # And the case axis: dateutil upper-cases every name and value.
    "an until in lower case": ("DURATION:PT1H", "RRULE:FREQ=DAILY;UNTIL=20260220T000000z"),
    # And the accepting mirror: padding around a separator is a real publisher idiom.
    "separator padding a publisher writes": ("DURATION:PT1H", "RRULE:FREQ=WEEKLY; BYDAY=MO"),
    # And a magnitude wider than the digits syncr will act on, which is where the range check was
    # skipped entirely rather than applied.
    "a month day past every magnitude": (
        "DURATION:PT1H",
        "RRULE:FREQ=SECONDLY;BYMONTHDAY=999999999999;BYHOUR=2",
    ),
    "a count past the conversion limit": (
        "DURATION:PT1H",
        f"RRULE:FREQ=DAILY;COUNT={PAST_INT_CONVERSION}",
    ),
    "a yearly rule from the start of time": ("DURATION:PT1H", "RRULE:FREQ=YEARLY"),
    "an exclusion past the end of time": (
        "DURATION:PT1H",
        "RRULE:FREQ=DAILY",
        "EXDATE:99991231T235959Z",
    ),
    "an extra date past the end of time": ("DURATION:PT1H", "RDATE:99991231T235959Z"),
    # Values read by their own converters rather than by the duration path.
    "a sequence past the conversion limit": (
        "DURATION:PT1H",
        f"SEQUENCE:{PAST_INT_CONVERSION}",
    ),
    "a recurrence id past the end of time": (
        "DURATION:PT1H",
        "RECURRENCE-ID:99991231T235959Z",
    ),
    "a timed end": ("DTEND:20260210T090000Z",),
}


def _crossed() -> dict[str, str]:
    """Every start crossed with every extreme value, as one body each.

    Some combinations are legitimate and produce events, and some are nonsense a publisher would
    never emit. Both belong: what the corpus asserts is that each is ANSWERED, not that each is
    refused, and a cross product is how a body nobody would have thought to write gets included. The
    site that justified the whole ``UNREPRESENTABLE`` net was found exactly that way.
    """
    return {
        f"{extreme} with {start}": _one_event(_STARTS[start], *_EXTREMES[extreme])
        for extreme in _EXTREMES
        for start in _STARTS
    }


def _orphan(*lines: str) -> str:
    """A replacement of a series this feed does not carry."""
    body = "\r\n".join(lines)
    return (
        "BEGIN:VEVENT\r\nUID:absent@example.org\r\n"
        "RECURRENCE-ID:20260217T100000Z\r\n" + body + "\r\nEND:VEVENT\r\n"
    )


# Two orphaned replacements of ONE occurrence. The same SEQUENCE rule settles these as settles the
# ones whose master is present: both surviving gives one commitment two events under one uid.
DUPLICATE_ORPHANS: Final = (
    "BEGIN:VCALENDAR\r\n"
    + _orphan(
        "SEQUENCE:1",
        "SUMMARY:Orphan moved to 14:00",
        "DTSTART:20260217T140000Z",
        "DTEND:20260217T150000Z",
    )
    + _orphan(
        "SEQUENCE:3",
        "SUMMARY:Orphan moved to 16:00",
        "DTSTART:20260217T160000Z",
        "DTEND:20260217T170000Z",
    )
    + "END:VCALENDAR\r\n"
)

# An orphaned cancellation and an orphaned live override of the same occurrence. Cancellation wins
# here as it does when the master is present, or a cancelled hour becomes hard occupancy.
CANCELLED_ORPHAN: Final = (
    "BEGIN:VCALENDAR\r\n"
    + _orphan(
        "STATUS:CANCELLED",
        "SUMMARY:Cancelled",
        "DTSTART:20260217T100000Z",
        "DTEND:20260217T110000Z",
    )
    + _orphan(
        "SUMMARY:...and here it is, moved",
        "DTSTART:20260217T140000Z",
        "DTEND:20260217T150000Z",
    )
    + "END:VCALENDAR\r\n"
)

# Two revisions of one series, the newer of which is a cancellation. The higher SEQUENCE has to win
# whether or not it is the cancelled one, or a superseded revision places a whole series.
CANCELLED_NEWER_REVISION: Final = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\nUID:rev@example.org\r\nSEQUENCE:1\r\nSUMMARY:Live older revision\r\n"
    "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:rev@example.org\r\nSEQUENCE:7\r\nSTATUS:CANCELLED\r\n"
    "SUMMARY:Cancelled newer revision\r\n"
    "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)

# London springs forward on 2026-03-29: 01:00 GMT becomes 02:00 BST, so no wall time in the 01:xx
# hour exists and one resolves onto the same instant as the real wall time an hour later. So two
# occurrences of an hourly series share an instant, and a key made of the instant named both at
# once.
SPRING_FORWARD_GAP: Final = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\nUID:gap@example.org\r\nSUMMARY:Hourly across the gap\r\n"
    "DTSTART;TZID=Europe/London:20260329T003000\r\n"
    "DTEND;TZID=Europe/London:20260329T005500\r\n"
    "RRULE:FREQ=HOURLY;COUNT=4\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:gap@example.org\r\nSUMMARY:Moved from the gap hour\r\n"
    "RECURRENCE-ID;TZID=Europe/London:20260329T013000\r\n"
    "DTSTART;TZID=Europe/London:20260329T190000\r\n"
    "DTEND;TZID=Europe/London:20260329T195500\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:gap@example.org\r\nSUMMARY:Moved from the hour after\r\n"
    "RECURRENCE-ID;TZID=Europe/London:20260329T023000\r\n"
    "DTSTART;TZID=Europe/London:20260329T200000\r\n"
    "DTEND;TZID=Europe/London:20260329T205500\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


HOSTILE_MAGNITUDES: Final[dict[str, str]] = _crossed()


def calendar_of(*components: str) -> str:
    """The given components wrapped in one ``VCALENDAR``, in the order given.

    Public because declaration ORDER is what one body below is about: a test composes the same
    components every way round and asserts the answer does not move.
    """
    return "BEGIN:VCALENDAR\r\n" + "".join(components) + "END:VCALENDAR\r\n"


# `Pacific/Apia` skipped 30 December 2011 entirely when it crossed the date line: 29 December ended
# at UTC-10 and 31 December began at UTC+14. So a daily series at 09:00 produces a wall time on the
# skipped date, and it resolves onto the same instant as 09:00 on the 31st, which the series also
# produces. A ONE-HOUR gap cannot make that shape: the two walls it collapses are an hour apart on
# one date, and no daily rule yields both.
_ACROSS_THE_SKIPPED_DATE: Final = (
    "BEGIN:VEVENT\r\nUID:apia@example.org\r\nSUMMARY:Daily across the skipped date\r\n"
    "DTSTART;TZID=Pacific/Apia:20111229T090000\r\n"
    "DTEND;TZID=Pacific/Apia:20111229T093000\r\n"
    "RRULE:FREQ=DAILY;COUNT=3\r\nEND:VEVENT\r\n"
)
# The skipped date's occurrence, named in the UTC form RFC 5545 permits. Its wall stamp is a time
# the series never produces, so nothing but the instant connects it to the occurrence it replaces.
SKIPPED_DATE_IN_UTC_FORM: Final = (
    "BEGIN:VEVENT\r\nUID:apia@example.org\r\nSUMMARY:Moved from the skipped date\r\n"
    "RECURRENCE-ID:20111230T190000Z\r\n"
    "DTSTART;TZID=Pacific/Apia:20111231T160000\r\n"
    "DTEND;TZID=Pacific/Apia:20111231T163000\r\nEND:VEVENT\r\n"
)
# The next day's occurrence, named in its own wall time. Same instant as the one above.
SKIPPED_DATE_IN_WALL_FORM: Final = (
    "BEGIN:VEVENT\r\nUID:apia@example.org\r\nSUMMARY:Moved from the day after\r\n"
    "RECURRENCE-ID;TZID=Pacific/Apia:20111231T090000\r\n"
    "DTSTART;TZID=Pacific/Apia:20111231T180000\r\n"
    "DTEND;TZID=Pacific/Apia:20111231T183000\r\nEND:VEVENT\r\n"
)
# A further spelling of that same instant: a `RECURRENCE-ID` naming a zone that is neither the
# series' nor UTC, which the standard permits as readily as the other two. `Asia/Tokyo` was UTC+9,
# so this states the instant above with a wall time that matches nothing else in the body.
SKIPPED_DATE_IN_A_FOREIGN_ZONE: Final = (
    "BEGIN:VEVENT\r\nUID:apia@example.org\r\nSUMMARY:Moved, named in Tokyo\r\n"
    "RECURRENCE-ID;TZID=Asia/Tokyo:20111231T040000\r\n"
    "DTSTART;TZID=Pacific/Apia:20111231T200000\r\n"
    "DTEND;TZID=Pacific/Apia:20111231T203000\r\nEND:VEVENT\r\n"
)

# Two occurrences on one instant, each carrying a replacement of its own.
SKIPPED_DATE_COMPONENTS: Final = (
    _ACROSS_THE_SKIPPED_DATE,
    SKIPPED_DATE_IN_UTC_FORM,
    SKIPPED_DATE_IN_WALL_FORM,
)
SKIPPED_DATE_GAP: Final = calendar_of(*SKIPPED_DATE_COMPONENTS)

# The same two occurrences with a third replacement on that instant, so the instant carries more
# keys than there are occurrences to claim them.
CROWDED_INSTANT_COMPONENTS: Final = (
    *SKIPPED_DATE_COMPONENTS,
    SKIPPED_DATE_IN_A_FOREIGN_ZONE,
)
CROWDED_INSTANT: Final = calendar_of(*CROWDED_INSTANT_COMPONENTS)


def _series_with(*replacements: str) -> str:
    """A weekly master, plus whatever replacements of its second occurrence are given."""
    master = (
        "BEGIN:VEVENT\r\nUID:conflict@example.org\r\nSUMMARY:Weekly\r\n"
        "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
    )
    return calendar_of(master, *replacements)


def _replacement(*lines: str) -> str:
    body = "\r\n".join(lines)
    return (
        "BEGIN:VEVENT\r\nUID:conflict@example.org\r\n"
        "RECURRENCE-ID:20260217T100000Z\r\n" + body + "\r\nEND:VEVENT\r\n"
    )


# Two replacements of ONE occurrence. An export that overlaps two edits repeats an override as
# readily as it repeats a master, so the same SEQUENCE rule has to settle it and the discard has to
# be counted.
DUPLICATE_REPLACEMENTS: Final = _series_with(
    _replacement(
        "SEQUENCE:1",
        "SUMMARY:Moved to 14:00",
        "DTSTART:20260217T140000Z",
        "DTEND:20260217T150000Z",
    ),
    _replacement(
        "SEQUENCE:3",
        "SUMMARY:Moved to 16:00",
        "DTSTART:20260217T160000Z",
        "DTEND:20260217T170000Z",
    ),
)

# The higher SEQUENCE declared FIRST, so a rule that kept whichever arrived last would answer this
# body differently from the one above.
DUPLICATE_REPLACEMENTS_REVERSED: Final = _series_with(
    _replacement(
        "SEQUENCE:3",
        "SUMMARY:Moved to 16:00",
        "DTSTART:20260217T160000Z",
        "DTEND:20260217T170000Z",
    ),
    _replacement(
        "SEQUENCE:1",
        "SUMMARY:Moved to 14:00",
        "DTSTART:20260217T140000Z",
        "DTEND:20260217T150000Z",
    ),
)

# One occurrence both moved and cancelled. The cancellation is what the feed means, and the override
# it displaces is a component that has to be accounted for.
MOVED_AND_CANCELLED: Final = _series_with(
    _replacement("SUMMARY:Moved", "DTSTART:20260217T140000Z", "DTEND:20260217T150000Z"),
    _replacement(
        "STATUS:CANCELLED",
        "SUMMARY:Gone",
        "DTSTART:20260217T100000Z",
        "DTEND:20260217T110000Z",
    ),
)

# Two identical cancellations of one occurrence. A repeated tombstone carries no SEQUENCE question,
# but the second component still has to be counted or it leaves the arithmetic.
DUPLICATE_TOMBSTONES: Final = _series_with(
    _replacement(
        "STATUS:CANCELLED",
        "SUMMARY:Cancelled",
        "DTSTART:20260217T100000Z",
        "DTEND:20260217T110000Z",
    ),
    _replacement(
        "STATUS:CANCELLED",
        "SUMMARY:Cancelled again",
        "DTSTART:20260217T100000Z",
        "DTEND:20260217T110000Z",
    ),
)

# A live master and a duplicate that moved the series, plus the override the losing revision left
# behind. That override names an occurrence the winning rule never produces, so placing it as well
# would put two events on one hour.
SHIFTED_BY_A_DUPLICATE_MASTER: Final = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\nUID:shift@example.org\r\nSEQUENCE:1\r\nSUMMARY:Weekly at 10\r\n"
    "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:shift@example.org\r\nSEQUENCE:2\r\nSUMMARY:Weekly at 12\r\n"
    "DTSTART:20260210T120000Z\r\nDTEND:20260210T130000Z\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:shift@example.org\r\nSUMMARY:Moved to 14:00\r\n"
    "RECURRENCE-ID:20260217T100000Z\r\n"
    "DTSTART:20260217T140000Z\r\nDTEND:20260217T150000Z\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


# A live master AND a cancelled one under one UID, with an override. The override belongs to the
# live series: a cancelled duplicate must not take the live master's occurrences down with it.
CANCELLED_DUPLICATE_MASTER: Final = _series_with(
    "BEGIN:VEVENT\r\nUID:conflict@example.org\r\nSTATUS:CANCELLED\r\n"
    "SUMMARY:Cancelled duplicate\r\nDTSTART:20260210T100000Z\r\n"
    "DTEND:20260210T110000Z\r\nEND:VEVENT\r\n",
    _replacement("SUMMARY:Moved hour", "DTSTART:20260217T140000Z", "DTEND:20260217T150000Z"),
)

# The same pair with the cancelled duplicate declared FIRST. Neither master carries a SEQUENCE,
# which is what most publishers emit, so a tie decided by document order answered these two bodies
# differently and lost a whole live series in one of them.
CANCELLED_DUPLICATE_MASTER_REVERSED: Final = (
    "BEGIN:VCALENDAR\r\n"
    "BEGIN:VEVENT\r\nUID:conflict@example.org\r\nSTATUS:CANCELLED\r\n"
    "SUMMARY:Cancelled duplicate\r\nDTSTART:20260210T100000Z\r\n"
    "DTEND:20260210T110000Z\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:conflict@example.org\r\nSUMMARY:Weekly\r\n"
    "DTSTART:20260210T100000Z\r\nDTEND:20260210T110000Z\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=3\r\nEND:VEVENT\r\n"
    + _replacement("SUMMARY:Moved hour", "DTSTART:20260217T140000Z", "DTEND:20260217T150000Z")
    + "END:VCALENDAR\r\n"
)


def _foreign_replacement(*lines: str) -> str:
    """A replacement of the second occurrence, named in a zone the series does not use."""
    body = "\r\n".join(lines)
    return (
        "BEGIN:VEVENT\r\nUID:conflict@example.org\r\n"
        "RECURRENCE-ID;TZID=Asia/Tokyo:20260217T190000\r\n" + body + "\r\nEND:VEVENT\r\n"
    )


# One occurrence declared in BOTH legal RECURRENCE-ID forms: the occurrence's own instant written
# as UTC and written in Asia/Tokyo (both name 2026-02-17T10:00Z). An export assembled from two
# windows carries the same edit twice under different spellings, and the higher SEQUENCE has to
# win whichever way round the publisher declares them.
_LOW_IN_THE_OWN_FORM: Final = _replacement(
    "SEQUENCE:1",
    "SUMMARY:Moved to 14:00",
    "DTSTART:20260217T140000Z",
    "DTEND:20260217T150000Z",
)
_HIGH_IN_A_FOREIGN_FORM: Final = _foreign_replacement(
    "SEQUENCE:3",
    "SUMMARY:Moved to 16:00",
    "DTSTART:20260217T160000Z",
    "DTEND:20260217T170000Z",
)
ONE_OCCURRENCE_IN_BOTH_FORMS: Final = _series_with(
    _LOW_IN_THE_OWN_FORM,
    _HIGH_IN_A_FOREIGN_FORM,
)
ONE_OCCURRENCE_IN_BOTH_FORMS_REVERSED: Final = _series_with(
    _HIGH_IN_A_FOREIGN_FORM,
    _LOW_IN_THE_OWN_FORM,
)

# A cancellation in the foreign form against a live replacement in the occurrence's own form.
# The feed's latest word is that the hour does not happen, so the override it displaces is counted
# and nothing places on the 17th, however the two are ordered.
_LIVE_IN_THE_OWN_FORM: Final = _replacement(
    "SEQUENCE:5",
    "SUMMARY:Moved to 14:00",
    "DTSTART:20260217T140000Z",
    "DTEND:20260217T150000Z",
)
_CANCELLED_IN_A_FOREIGN_FORM: Final = _foreign_replacement(
    "STATUS:CANCELLED",
    "SUMMARY:Cancelled from Tokyo",
    "DTSTART:20260217T100000Z",
    "DTEND:20260217T110000Z",
)
CANCELLED_ACROSS_THE_FORMS: Final = _series_with(
    _LIVE_IN_THE_OWN_FORM,
    _CANCELLED_IN_A_FOREIGN_FORM,
)
CANCELLED_ACROSS_THE_FORMS_REVERSED: Final = _series_with(
    _CANCELLED_IN_A_FOREIGN_FORM,
    _LIVE_IN_THE_OWN_FORM,
)

# The mirror: the cancellation in the occurrence's own form, the live override in the foreign one.
# The displaced override cannot be told from a stale one by its key alone, so the displacement has
# to be seen where the two forms meet.
_CANCELLED_IN_THE_OWN_FORM: Final = _replacement(
    "STATUS:CANCELLED",
    "SUMMARY:Cancelled",
    "DTSTART:20260217T100000Z",
    "DTEND:20260217T110000Z",
)
_LIVE_IN_A_FOREIGN_FORM: Final = _foreign_replacement(
    "SEQUENCE:9",
    "SUMMARY:Moved to 16:00",
    "DTSTART:20260217T160000Z",
    "DTEND:20260217T170000Z",
)
CANCELLED_IN_THE_OWN_FORM: Final = _series_with(
    _CANCELLED_IN_THE_OWN_FORM,
    _LIVE_IN_A_FOREIGN_FORM,
)
CANCELLED_IN_THE_OWN_FORM_REVERSED: Final = _series_with(
    _LIVE_IN_A_FOREIGN_FORM,
    _CANCELLED_IN_THE_OWN_FORM,
)


# Every body above, so a test can assert a property over the whole corpus.
ALL_FEEDS: Final = {
    "university_timetable": UNIVERSITY_TIMETABLE,
    "assessments": ASSESSMENTS_FEED,
    "published_outlook": PUBLISHED_OUTLOOK,
    "holidays": HOLIDAY_FEED,
    "empty": EMPTY_FEED,
    "runaway": RUNAWAY_RECURRENCE,
    "overrunning": OVERRUNNING_RECURRENCE,
    "deeply_nested": DEEPLY_NESTED,
    "duplicate_replacements": DUPLICATE_REPLACEMENTS,
    "duplicate_replacements_reversed": DUPLICATE_REPLACEMENTS_REVERSED,
    "moved_and_cancelled": MOVED_AND_CANCELLED,
    "cancelled_duplicate_master": CANCELLED_DUPLICATE_MASTER,
    "cancelled_duplicate_master_reversed": CANCELLED_DUPLICATE_MASTER_REVERSED,
    "duplicate_tombstones": DUPLICATE_TOMBSTONES,
    "shifted_by_a_duplicate_master": SHIFTED_BY_A_DUPLICATE_MASTER,
    "one_occurrence_in_both_forms": ONE_OCCURRENCE_IN_BOTH_FORMS,
    "one_occurrence_in_both_forms_reversed": ONE_OCCURRENCE_IN_BOTH_FORMS_REVERSED,
    "cancelled_across_the_forms": CANCELLED_ACROSS_THE_FORMS,
    "cancelled_across_the_forms_reversed": CANCELLED_ACROSS_THE_FORMS_REVERSED,
    "cancelled_in_the_own_form": CANCELLED_IN_THE_OWN_FORM,
    "cancelled_in_the_own_form_reversed": CANCELLED_IN_THE_OWN_FORM_REVERSED,
    "duplicate_orphans": DUPLICATE_ORPHANS,
    "cancelled_orphan": CANCELLED_ORPHAN,
    "cancelled_newer_revision": CANCELLED_NEWER_REVISION,
    "spring_forward_gap": SPRING_FORWARD_GAP,
    "skipped_date_gap": SKIPPED_DATE_GAP,
    "crowded_instant": CROWDED_INSTANT,
    **HOSTILE_MAGNITUDES,
}
