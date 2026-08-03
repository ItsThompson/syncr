"""Why one component of a feed produced no event, as a class the panel can group by.

A rejection is not an exception the caller handles and forgets: it is reported to the user on
the source's panel, grouped by class, with the component and line named. So the class travels
ON the exception rather than being recovered from its message. Reading a kind back out of a
string would make the panel's grouping depend on wording nobody thinks of as a contract.

``UnmappedZone`` extends the domain's own ``UnknownZoneError`` as well as this hierarchy, so a
caller that already handles an unresolvable zone handles this too, and this package's single
``except`` still catches it.

:data:`UNREPRESENTABLE` and :func:`as_rejection` are the other half of the same idea. A feed also
controls the MAGNITUDES it states, and a magnitude that arithmetic cannot represent is the feed's
doing as much as a malformed value is. Naming that set once, here, is what makes "the adapter never
raises" a property of the boundary rather than a promise each call site has to keep.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from syncr_api.calendars.config import (
    MALFORMED_VALUE,
    MISSING_DURATION,
    UNKNOWN_ZONE,
    UNPARSEABLE_RECURRENCE,
)
from syncr_domain.errors import DomainError
from syncr_domain.intervals import IntervalError
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


# Failures that are a property of the VALUES a feed supplied rather than of syncr's own logic.
#
# ``OverflowError`` is a magnitude date arithmetic cannot represent, and ``IntervalError`` is a span
# the domain refuses. A feed controls the numbers that produce either, so both are the feed's doing
# and belong on the panel as rejections. Neither is an ``IcsRejection``, so without this set they
# escape the adapter and break the contract that none of its answers raises: the cost measured is a
# whole tenant's sync pass aborted and the sync state already written in that transaction rolled
# back.
#
# The set is deliberately narrow. A ``KeyError`` or an ``AttributeError`` down here is syncr's bug,
# not the publisher's, and converting one into a rejection would hide it behind a message blaming
# the feed.
UNREPRESENTABLE: Final = (OverflowError, IntervalError)


def as_rejection(error: BaseException) -> IcsRejection:
    """``error`` as the rejection it should be reported as.

    A rejection passes through unchanged, keeping its specific kind and message. A magnitude failure
    becomes a ``MalformedValue``, so a value nobody thought to bound is still answered with a
    component and a line rather than with a fault.

    Bounding the magnitude where it is READ is still the better answer, because only there can the
    message name the property. This is the net under those bounds, not a substitute for them.
    """
    if isinstance(error, IcsRejection):
        return error
    return MalformedValue(f"a value in this component is too large for syncr to place: {error}")
