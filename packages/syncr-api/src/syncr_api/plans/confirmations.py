"""Which of a week's days the user has confirmed, and the seam that answers it.

A block is PRESUMED complete until the user says otherwise, and a day becomes fact when they
confirm it: ``BlockOutcome.confirmed_at`` is where that instant lands, and a day with none is
excluded from reviews and from learning, because a day the user disengaged from entirely must not
be recorded as perfect.

``NoConfirmations`` is the production reader today, and it is an honest reading rather than a
placeholder: nothing in this deployment writes an outcome, so no day of any week has been
confirmed. The route that records one and the route that confirms a day are their own piece of
work, and bringing them online changes one line of wiring.

The reader is a protocol for the same reason the week placement reader is one: the concern that
owns the outcome log owns its storage, and the week view should acquire the answer rather than
reach into a table another feature writes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syncr_domain.weeks import IsoWeek
    from syncr_domain.zones import Date


class DayConfirmationReader(Protocol):
    """What the week view asks for the days a user has confirmed."""

    async def confirmed_dates(self, iso_week: IsoWeek) -> frozenset[Date]:
        """The week's dates the user has confirmed. Reads only, and never writes."""
        ...


class NoConfirmations:
    """The reading of a deployment where no outcome has been recorded: no day is confirmed."""

    async def confirmed_dates(self, iso_week: IsoWeek) -> frozenset[Date]:
        return frozenset()
