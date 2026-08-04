"""What an all-day span occupies, in one place, for every provider that publishes one.

An all-day event names dates rather than instants, so it occupies whole LOCAL days: from
local midnight on its first date to local midnight on the date after its last. Each end
resolves against the zone active on its OWN date, so a span containing a daylight-saving
transition or a travel boundary is as long as those days really were, which is 23 or 25 hours
rather than 24.

Provider-agnostic on purpose. ICS states the span with ``DTSTART;VALUE=DATE`` and an exclusive
``DTEND``, and Google states it with ``start.date`` and an exclusive ``end.date``: two
spellings of one rule, and a second implementation of it would be a second answer to how long
a transition day is.

The zone comes from the tenant's profile rather than from the publisher. An all-day event
carries no zone in ICS at all, and the reading that makes both providers agree is the user's
own day: "the 9th" means the 9th where the user is.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import TYPE_CHECKING

from syncr_domain.intervals import Interval
from syncr_domain.zones import active_zone, to_instant

if TYPE_CHECKING:
    from datetime import date

    from syncr_domain.zones import ZoneProfile

ONE_DAY = timedelta(days=1)

LOCAL_MIDNIGHT = time(0, 0)


def local_day_span(first: date, days: int, profile: ZoneProfile) -> Interval:
    """``days`` whole local days from local midnight on ``first``.

    The caller has already bounded ``days``: this function is arithmetic over a magnitude
    somebody else validated, and it states no policy about how long an event may be.
    """
    last = first + ONE_DAY * days
    return Interval(
        to_instant(LOCAL_MIDNIGHT, first, active_zone(profile, first)),
        to_instant(LOCAL_MIDNIGHT, last, active_zone(profile, last)),
    )
