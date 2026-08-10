"""Feeds generated over a stated component count, for the tests about the rejection sample.

Shared by the unit tests and the integration test, because the integration claim is that the sample
a parse kept is the sample the panel reads back, and two different bodies could not prove that.

Each refused component here fails while it is being READ, before any recurrence is expanded, so a
feed of fifty thousand of them costs a lexer pass rather than fifty thousand expansions. That is
what makes the count worth bounding the list against: refusals are cheap to provoke and a publisher
chooses how many of them a feed carries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syncr_api.calendars.config import MALFORMED_VALUE, MISSING_DURATION, UNKNOWN_ZONE
from syncr_api.calendars.events import RejectedComponent

if TYPE_CHECKING:
    from syncr_api.calendars.config import RejectionKind

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

# The three properties, and the kind each one is refused as. Cycled over a feed so more than one
# kind reaches the sample: a bound stated per kind cannot be told from a bound on the whole list by
# a feed whose every component fails the same way.
_REFUSALS: tuple[tuple[RejectionKind, str], ...] = (
    # No DTEND and no DURATION, so nothing says how long it lasts.
    (MISSING_DURATION, "DTSTART:20260210T090000Z\r\n"),
    # A TZID that maps to no IANA zone.
    (
        UNKNOWN_ZONE,
        "DTSTART;TZID=Mars/Olympus:20260210T090000\r\nDTEND;TZID=Mars/Olympus:20260210T100000\r\n",
    ),
    # A DTSTART that will not convert at all.
    (MALFORMED_VALUE, "DTSTART:the-tenth-of-february\r\nDTEND:20260210T100000Z\r\n"),
)

KINDS_REFUSED_CHEAPLY: tuple[RejectionKind, ...] = tuple(kind for kind, _ in _REFUSALS)


def refused_feed(components: int) -> str:
    """A feed of ``components`` events, every one refused while it is read, cycling three kinds."""
    body = "".join(
        f"BEGIN:VEVENT\r\nUID:refused-{index}@example.org\r\nSUMMARY:Refused {index}\r\n"
        f"{_REFUSALS[index % len(_REFUSALS)][1]}END:VEVENT\r\n"
        for index in range(components)
    )
    return f"BEGIN:VCALENDAR\r\n{body}END:VCALENDAR\r\n"


def ordinary_feed(components: int) -> str:
    """A feed of ``components`` unremarkable one-hour meetings, none of them refusable.

    Read with a spent budget, every one of them is refused for the one reason that is not a fault in
    the component: the feed ran out of the time syncr will spend reading it.
    """
    body = "".join(
        f"BEGIN:VEVENT\r\nUID:real-{index}@example.org\r\nSUMMARY:Lecture {index}\r\n"
        "DTSTART:20260210T090000Z\r\nDTEND:20260210T100000Z\r\nEND:VEVENT\r\n"
        for index in range(components)
    )
    return f"BEGIN:VCALENDAR\r\n{body}END:VCALENDAR\r\n"


def rejection(kind: RejectionKind, *, line: int) -> RejectedComponent:
    """One rejection of a stated kind, for the tests that accumulate them directly."""
    return RejectedComponent(
        kind=kind,
        line=line,
        component="VEVENT",
        detail=f"line {line} was refused as {kind}",
        uid=f"component-{line}@example.org",
    )
