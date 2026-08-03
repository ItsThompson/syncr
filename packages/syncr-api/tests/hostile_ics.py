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
question about a plan and a question about a feed can be asked about one week.
"""

from __future__ import annotations

from typing import Final

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
# OCCURRENCE of a live series, and a duplicate UID pair produced by an export covering two
# overlapping windows: the same meeting at two SEQUENCE values, the later of which moved it.
# UID pair produced by an export covering two overlapping windows: the same meeting at two
# SEQUENCE values, the later of which moved it.
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

# Magnitudes, as a matrix rather than a list.
#
# A feed states NUMBERS as well as syntax, and a number that parses perfectly can still overflow the
# date arithmetic that would place it: `DTEND;VALUE=DATE:99991231` is how some publishers express an
# open-ended all-day event, and an over-long `DURATION` is a routine broken-export value. Neither
# needs malice, and neither is a syntax error, so neither is caught by any amount of grammar.
#
# One entry per place a publisher-controlled magnitude reaches date, time, or timedelta
# construction, so the boundary test that reads this covers the CLASS rather than the two instances
# that happened to be found. Some of these are legitimate and produce events; that is the point of a
# matrix over a list of known-bad values.
HOSTILE_MAGNITUDES: Final[dict[str, str]] = {
    "duration over a billion days": _one_event(TIMED_START, "DURATION:P9999999999D"),
    "duration in weeks": _one_event(TIMED_START, "DURATION:P999999999W"),
    "duration in seconds": _one_event(TIMED_START, "DURATION:PT99999999999999S"),
    "duration at the constructor's own edge": _one_event(TIMED_START, "DURATION:P999999999D"),
    "duration of a century": _one_event(TIMED_START, "DURATION:P36600D"),
    "duration of a decade": _one_event(TIMED_START, "DURATION:P3650D"),
    "whole days to the end of time": _one_event(DAY_START, "DTEND;VALUE=DATE:99991231"),
    "whole days from the start of time": _one_event(
        "DTSTART;VALUE=DATE:00010101", "DTEND;VALUE=DATE:99991231"
    ),
    "whole days by duration": _one_event(DAY_START, "DURATION:P999999999D"),
    "a start at the first representable date": _one_event(
        "DTSTART;VALUE=DATE:00010101", "DTEND;VALUE=DATE:00010102"
    ),
    "a start at the last representable date": _one_event(
        "DTSTART;VALUE=DATE:99991230", "DTEND;VALUE=DATE:99991231"
    ),
    "a zoned start at the last representable date": _one_event(
        "DTSTART;TZID=Pacific/Kiritimati:99991231T235959", "DURATION:PT1H"
    ),
    "a zoned start at the first representable date": _one_event(
        "DTSTART;TZID=Pacific/Midway:00010101T000000", "DURATION:PT1H"
    ),
    "an until past the end of time": _one_event(
        ZONED_START, "DURATION:PT1H", "RRULE:FREQ=DAILY;UNTIL=99991231T235959Z"
    ),
    "an interval nothing can walk": _one_event(
        TIMED_START, "DURATION:PT1H", "RRULE:FREQ=DAILY;INTERVAL=999999999"
    ),
    "a count nothing can walk": _one_event(
        TIMED_START, "DURATION:PT1H", "RRULE:FREQ=DAILY;COUNT=999999999"
    ),
    "a yearly rule from the first representable year": _one_event(
        "DTSTART:00010101T000000Z", "DURATION:PT1H", "RRULE:FREQ=YEARLY"
    ),
    "an exclusion past the end of time": _one_event(
        TIMED_START, "DURATION:PT1H", "RRULE:FREQ=DAILY", "EXDATE:99991231T235959Z"
    ),
    "an extra date past the end of time": _one_event(
        TIMED_START, "DURATION:PT1H", "RDATE:99991231T235959Z"
    ),
    "a sequence of four hundred digits": _one_event(
        TIMED_START, "DURATION:PT1H", f"SEQUENCE:{'9' * 400}"
    ),
    "a recurrence id past the end of time": _one_event(
        TIMED_START, "DURATION:PT1H", "RECURRENCE-ID:99991231T235959Z"
    ),
}

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
    **HOSTILE_MAGNITUDES,
}
