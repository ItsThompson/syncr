"""The ``elastic_sleep`` fixture: a sleep routine with give in it, and a week that needs the give.

The one fixture where a routine's minimum is BELOW its target, which is the state that makes a
``reduce_routine`` tradeoff offerable at all. By default a routine's minimum equals its target and
none of them is elastic, so the concession the PRD names ("reduce the sleep floor by 1h across
three nights") has no subject unless a fixture states one.

``Europe/London`` 2026-W07, which is on GMT that month, so a local wall time and its UTC spelling
coincide and an assertion about ``23:00`` is not also an assertion about an offset.

| What | Value |
|---|---|
| the routine | ``Sleep``, target 23:00, 8h long, minimum 7h40m |
| the give, per night | 20 minutes, which is the target less the minimum |
| ``now`` | Tuesday 10 February at 09:00 |
| the gap the week holds | 60 minutes |
| the nights a concession would touch | Tuesday, Wednesday and Thursday, 20 minutes each |

**Why the gap is 60 and the give is 20.** Three nights is the number the PRD's own phrasing names,
and it is a consequence rather than a coincidence: an hour cannot come off one night that has only
twenty minutes to give, so the fewest nights that can supply the gap is three. A fixture whose give
was an hour a night would recover the whole gap from Tuesday and would never exercise the
distribution.

**Why ``now`` is Tuesday morning.** Monday night's occurrence is wholly behind it, so shortening
that night would hand back a span the probe counts no capacity in: capacity starts at ``now``. The
three earliest nights a concession may touch are therefore Tuesday, Wednesday and Thursday, which
is what makes the label read ``on Tue, Wed and Thu``.

**The gap itself is stated rather than built.** What produces 60 minutes of shortfall is a floor, a
deadline, or a declared span, and each of those is a stored row in another package: a consumer
builds the week that yields it and asserts against ``GAP_MINUTES``. What this fixture owns is the
routine, the instant, and the nights, because those are what the concession is about.

Every instant is a **literal**, as in the other fixtures here, and
``tests/test_elastic_sleep_fixture.py`` re-derives each from the stated wall time above.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.zones import Date

WEEK: Final = IsoWeek(2026, 7)
ZONE: Final = "Europe/London"

TITLE: Final = "Sleep"
TARGET_TIME: Final = time(23, 0)
DURATION_MINUTES: Final = 8 * 60
MIN_DURATION_MINUTES: Final = 7 * 60 + 40
# What one night could be shortened by: the target less the minimum R6 clamps to.
GIVE_MINUTES: Final = DURATION_MINUTES - MIN_DURATION_MINUTES

# Tuesday 10 February 2026 at 09:00 local, which is 09:00Z. Monday night's occurrence ended two
# hours earlier, so it is not a night a concession may still shorten.
NOW: Final = datetime(2026, 2, 10, 9, 0, tzinfo=UTC)

# The shortfall the week holds, in minutes. Three nights of give, exactly.
GAP_MINUTES: Final = 60
# What one night gives up when the gap is spread over the fewest nights that can supply it.
REDUCTION_EACH: Final = GAP_MINUTES // 3

TUESDAY: Final[Date] = date(2026, 2, 10)
WEDNESDAY: Final[Date] = date(2026, 2, 11)
THURSDAY: Final[Date] = date(2026, 2, 12)

# The nights a concession would name, earliest first, as the enumerator would distribute the gap.
# Read-only in fact rather than by convention: two packages' suites share this object, and `Final`
# stops a rebinding while leaving a mutation open.
REDUCTIONS: Final[Mapping[Date, int]] = MappingProxyType(
    {
        TUESDAY: REDUCTION_EACH,
        WEDNESDAY: REDUCTION_EACH,
        THURSDAY: REDUCTION_EACH,
    }
)

# How the label reads, which names the nights because the concession stores them.
LABEL: Final = "Reduce Sleep by 20m on Tue, Wed and Thu"

# Monday night's occurrence, which is wholly behind `NOW`: 23:00 Monday to 07:00 Tuesday.
MONDAY_NIGHT: Final = Interval(
    datetime(2026, 2, 9, 23, 0, tzinfo=UTC), datetime(2026, 2, 10, 7, 0, tzinfo=UTC)
)
# Tuesday night's, the earliest a concession may shorten.
TUESDAY_NIGHT: Final = Interval(
    datetime(2026, 2, 10, 23, 0, tzinfo=UTC), datetime(2026, 2, 11, 7, 0, tzinfo=UTC)
)
# Tuesday night at its reduced length, which is the minimum plus what is left of the give.
TUESDAY_NIGHT_REDUCED: Final = Interval(
    TUESDAY_NIGHT.start, TUESDAY_NIGHT.end - timedelta(minutes=REDUCTION_EACH)
)
