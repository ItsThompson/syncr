"""The all-day span rule, shared by both providers that publish one.

An all-day event occupies whole LOCAL days, and the only interesting cases are the days that are
not 24 hours long. Both providers state such a span the same way (a first date and an exclusive
last), so the rule has one implementation and this is its test.

Real zones and real transition dates, because a fixture zone with a made-up rule would assert the
arithmetic against itself.
"""

from __future__ import annotations

from datetime import date

from syncr_api.calendars.day_spans import local_day_span
from syncr_domain.zones import ZoneProfile

LONDON = ZoneProfile(home_zone="Europe/London")
# 2026-03-29 is the spring-forward date in Europe/London: 01:00 becomes 02:00.
SPRING_FORWARD = date(2026, 3, 29)
# 2026-10-25 is the fall-back date: 02:00 happens twice.
FALL_BACK = date(2026, 10, 25)

HOURS_IN_A_DAY = 24


def test_an_ordinary_day_is_twenty_four_hours() -> None:
    span = local_day_span(date(2026, 2, 9), 1, LONDON)

    assert span.duration.total_seconds() / 3600 == HOURS_IN_A_DAY


def test_a_spring_forward_day_is_twenty_three_hours() -> None:
    # The day really was 23 hours long, and a budget denominator that said 24 would be wrong by an
    # hour for every reader of that week.
    span = local_day_span(SPRING_FORWARD, 1, LONDON)

    assert span.duration.total_seconds() / 3600 == HOURS_IN_A_DAY - 1


def test_a_fall_back_day_is_twenty_five_hours() -> None:
    span = local_day_span(FALL_BACK, 1, LONDON)

    assert span.duration.total_seconds() / 3600 == HOURS_IN_A_DAY + 1


def test_a_span_crossing_a_transition_is_as_long_as_those_days_were() -> None:
    # Each end resolves against the zone active on its OWN date, which is what makes a range
    # containing a transition come out at the real elapsed time rather than a multiple of 24.
    span = local_day_span(date(2026, 3, 28), 3, LONDON)

    assert span.duration.total_seconds() / 3600 == 3 * HOURS_IN_A_DAY - 1


def test_a_span_starts_and_ends_at_local_midnight() -> None:
    span = local_day_span(date(2026, 7, 1), 1, LONDON)

    # July is BST, one hour ahead, so local midnight is 23:00 UTC the day before.
    assert span.start.isoformat() == "2026-06-30T23:00:00+00:00"
    assert span.end.isoformat() == "2026-07-01T23:00:00+00:00"
