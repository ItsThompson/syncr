"""Which weeks the projection horizon covers, and when it next moves.

The horizon is ``[today_local, today_local + horizon_days)``: a rolling window of LOCAL dates, so it
advances with the date rather than being extended by hand, and a week is inside it when any of the
week's own dates is.

**The weeks are answered in chronological order**, which matters on first run: the current week is
planned before next week, so a user who opens the product for the first time gets this week's plan
first rather than whichever week a set iterated to first.

**Local, not UTC.** A user in London at 00:30 is on a date that UTC still calls yesterday, so a
horizon computed in UTC would advance half an hour late for them and, east of Greenwich, a day
early. The date is resolved in the HOME zone, which is the same zone every other "which week is it"
question in this application is answered in.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import TYPE_CHECKING

from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.weeks import IsoWeek
from syncr_domain.zones import to_instant

if TYPE_CHECKING:
    from datetime import date, datetime

    from syncr_domain.zones import Date, ZoneId

_ONE_DAY = timedelta(days=1)

MIDNIGHT = time(0, 0)


def horizon_dates(*, today: date, horizon_days: int) -> tuple[Date, ...]:
    """Every local date the horizon covers, starting today. Half-open at the far end.

    ``horizon_days`` is bounded to at least one where it is stored, so the horizon always covers
    today: a zero-day horizon would read as configured while projecting nothing.
    """
    return tuple(today + _ONE_DAY * offset for offset in range(horizon_days))


def horizon_weeks(*, today: date, horizon_days: int) -> tuple[IsoWeek, ...]:
    """Every ISO week overlapping the horizon, earliest first.

    At the default fourteen days this is two or three weeks, and which of the two depends on the
    weekday today falls on rather than on anything a caller chooses.

    Derived from the dates rather than by walking weeks from a start to an end, because a week is in
    the horizon exactly when it holds one of its dates: counting weeks would need its own reading of
    the half-open bound, and two readings of one bound is how an off-by-one week appears.
    """
    weeks: list[IsoWeek] = []
    for day in horizon_dates(today=today, horizon_days=horizon_days):
        week = IsoWeek.containing(day)
        if week not in weeks:
            weeks.append(week)
    return tuple(weeks)


def next_local_midnight(now: datetime, zone: ZoneId) -> datetime:
    """The instant the local date next changes in ``zone``.

    Resolved through the zone layer's one wall-time-to-instant function, so a midnight a transition
    skips or repeats is answered the same way every other declared wall time is rather than by date
    arithmetic that assumes a day is 24 hours.
    """
    return to_instant(MIDNIGHT, local_date(now, zone) + _ONE_DAY, zone)
