"""Which of a week's days the user has confirmed, as the week view asks for it.

A block is PRESUMED complete until the user says otherwise, and a day becomes fact when they
confirm it: ``BlockOutcome.confirmed_at`` is where that instant lands, and a day with none is
excluded from reviews and from learning, because a day the user disengaged from entirely must not
be recorded as perfect.

A protocol rather than an import, for the same reason the week placement reader is one: the
concern that owns the outcome log owns its storage and the rule for reading a date out of it, and
the week view should acquire the answer rather than reach into a table another feature writes. The
implementation is :class:`~syncr_api.outcomes.confirmations.RecordedDayConfirmations`, so the count
the Week screen renders and the count the Today surface renders come from one rule.
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
