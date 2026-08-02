"""Instant and interval literals, shared by the interval suites.

Every value sits inside one Monday so a failure message reads as clock times, and no
test in these suites depends on a date at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from syncr_domain.intervals import Instant, Interval

# The Monday of 2026-W10, an ordinary 168-hour week in Europe/London.
MONDAY = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)


def at(hour: int, minute: int = 0, *, day: int = 0) -> Instant:
    return MONDAY + timedelta(days=day, hours=hour, minutes=minute)


def between(start_hour: float, end_hour: float, *, day: int = 0) -> Interval:
    return Interval(
        MONDAY + timedelta(days=day, hours=start_hour),
        MONDAY + timedelta(days=day, hours=end_hour),
    )
