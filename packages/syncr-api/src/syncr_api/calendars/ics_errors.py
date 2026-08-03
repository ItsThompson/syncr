"""Why one component of a feed produced no event, as a class the panel can group by.

A rejection is not an exception the caller handles and forgets: it is reported to the user on
the source's panel, grouped by class, with the component and line named. So the class travels
ON the exception rather than being recovered from its message. Reading a kind back out of a
string would make the panel's grouping depend on wording nobody thinks of as a contract.

``UnmappedZone`` extends the domain's own ``UnknownZoneError`` as well as this hierarchy, so a
caller that already handles an unresolvable zone handles this too, and this package's single
``except`` still catches it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from syncr_api.calendars.config import (
    MALFORMED_VALUE,
    MISSING_DURATION,
    UNKNOWN_ZONE,
    UNPARSEABLE_RECURRENCE,
)
from syncr_domain.errors import DomainError
from syncr_domain.zones import UnknownZoneError

if TYPE_CHECKING:
    from syncr_api.calendars.config import RejectionKind


class IcsRejection(DomainError):
    """A component syncr will not turn into an event.

    ``line`` is set only when the failure is not attributable to a component the caller already
    holds: a depth bound is exceeded part-way through the lexer, before any component closes, so
    the position has to travel with the error or the panel would report line 0.
    """

    kind: ClassVar[RejectionKind] = MALFORMED_VALUE

    def __init__(self, detail: str, *, line: int | None = None) -> None:
        self.line = line
        super().__init__(detail)


class MalformedValue(IcsRejection):
    """A property's value does not parse, so the event cannot be placed."""


class MissingDuration(IcsRejection):
    """Neither ``DTEND`` nor ``DURATION``, so the event states no occupancy."""

    kind = MISSING_DURATION


class UnparseableRecurrence(IcsRejection):
    """An ``RRULE`` that will not expand, or that expands further than syncr will read."""

    kind = UNPARSEABLE_RECURRENCE


class UnmappedZone(IcsRejection, UnknownZoneError):
    """A ``TZID`` naming neither an IANA zone nor a known alias.

    Carries the offending name, because the panel states which zone it was: a count of
    rejected events without the zone leaves the user nothing to act on.
    """

    kind = UNKNOWN_ZONE

    def __init__(self, tzid: str) -> None:
        self.tzid = tzid
        super().__init__(
            f"{tzid!r} names no IANA time zone and no known alias, so syncr cannot tell "
            "when this event happens"
        )
