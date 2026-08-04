"""Which weeks a span reaches into, at the boundary where the answer changes.

Every case here is a Monday. A period is half-open, so one ending at a Monday's local midnight
reaches nothing inside the week that starts there, and one ending a quarter of an hour later
reaches into it. Those two are the only interesting inputs, and they differ by fifteen minutes.

The zone is real (``Europe/London``) and one case sits over the autumn transition, because the
answer is a LOCAL date question and a span whose UTC and local dates disagree is where a
derivation that skipped the zone would still look right.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from syncr_api.offplan.weeks import weeks_touching
from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_domain.fixtures.off_plan_week import OFF_PLAN_WEEK
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek, week_span

LONDON = "Europe/London"

# 2026-W10 in London: an ordinary week, in GMT, so its local Mondays are 00:00 UTC.
WEEK_10 = IsoWeek.parse("2026-W10")
WEEK_11 = IsoWeek.parse("2026-W11")
MONDAY_OF_WEEK_11 = datetime(2026, 3, 9, 0, 0, tzinfo=UTC)

QUARTER_HOUR = timedelta(minutes=15)


def only(week: IsoWeek) -> WeekRange:
    return WeekRange(first=week, last=week)


def test_a_span_inside_one_week_touches_that_week_alone() -> None:
    friday_afternoon = Interval(
        datetime(2026, 3, 6, 14, 0, tzinfo=UTC), datetime(2026, 3, 6, 18, 0, tzinfo=UTC)
    )

    assert weeks_touching(friday_afternoon, home_zone=LONDON) == only(WEEK_10)


def test_a_span_ending_exactly_at_a_weeks_first_instant_does_not_touch_that_week() -> None:
    # The boundary the half-open reading exists for. The last instant this span covers is
    # 23:59 on the Sunday, so the week beginning at that midnight holds none of it and its
    # denominator did not change.
    ending_at_the_boundary = Interval(datetime(2026, 3, 6, 14, 0, tzinfo=UTC), MONDAY_OF_WEEK_11)

    assert weeks_touching(ending_at_the_boundary, home_zone=LONDON) == only(WEEK_10)


def test_a_span_ending_one_quarter_hour_later_does_touch_it() -> None:
    # The other side of the same boundary, fifteen minutes away: the first grid instant inside
    # the following week, which is the shortest period that can reach into it.
    crossing_the_boundary = Interval(
        datetime(2026, 3, 6, 14, 0, tzinfo=UTC), MONDAY_OF_WEEK_11 + QUARTER_HOUR
    )

    assert weeks_touching(crossing_the_boundary, home_zone=LONDON) == WeekRange(
        first=WEEK_10, last=WEEK_11
    )


def test_a_span_beginning_exactly_at_a_weeks_first_instant_touches_it() -> None:
    # And the opposite end: `start` IS inside the period, so a span beginning at the Monday's
    # local midnight belongs to the week that begins there and not to the one before it.
    beginning_at_the_boundary = Interval(MONDAY_OF_WEEK_11, MONDAY_OF_WEEK_11 + timedelta(hours=9))

    assert weeks_touching(beginning_at_the_boundary, home_zone=LONDON) == only(WEEK_11)


def test_a_whole_weeks_span_touches_that_week_alone() -> None:
    # `week_span` runs from one local Monday to the next, so a period covering a week exactly
    # ends where the following week begins and must not bump it.
    span = week_span(WEEK_10, OFF_PLAN_WEEK.profile)

    assert weeks_touching(span, home_zone=LONDON) == only(WEEK_10)


def test_the_friday_to_monday_span_touches_both_of_its_weeks() -> None:
    # The fixture's own span, over the week the clocks go back: the local date of its end is a
    # Monday in the following ISO week, and the transition inside it changes nothing here.
    assert weeks_touching(OFF_PLAN_WEEK.off_plan, home_zone=LONDON) == WeekRange(
        first=OFF_PLAN_WEEK.iso_week, last=OFF_PLAN_WEEK.following_week
    )


def test_a_span_of_several_weeks_touches_every_week_between_its_ends() -> None:
    fortnight = Interval(
        datetime(2026, 3, 6, 14, 0, tzinfo=UTC), datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
    )

    assert weeks_touching(fortnight, home_zone=LONDON) == WeekRange(
        first=WEEK_10, last=IsoWeek.parse("2026-W13")
    )


def test_a_span_shorter_than_the_grid_still_names_the_week_it_sits_in() -> None:
    # The clamp. Such a span cannot be declared, because both bounds land on the quarter hour,
    # but this function does not require that, and without the clamp its last-covered instant
    # would fall a quarter of an hour before its own start and name the week before it.
    a_minute_after_midnight = Interval(MONDAY_OF_WEEK_11, MONDAY_OF_WEEK_11 + timedelta(minutes=1))

    assert weeks_touching(a_minute_after_midnight, home_zone=LONDON) == only(WEEK_11)


@pytest.mark.parametrize(
    ("zone", "expected"),
    [(LONDON, "2026-W11"), ("Pacific/Auckland", "2026-W12")],
    ids=["london", "auckland"],
)
def test_the_week_is_resolved_in_the_tenants_own_zone(zone: str, expected: str) -> None:
    # 2026-03-15 23:30 UTC is Sunday night in London and Monday lunchtime in Auckland, so the
    # same instant sits in two different ISO weeks. A derivation reading UTC dates would answer
    # London's for both.
    sunday_night = Interval(
        datetime(2026, 3, 15, 23, 30, tzinfo=UTC), datetime(2026, 3, 15, 23, 45, tzinfo=UTC)
    )

    assert weeks_touching(sunday_night, home_zone=zone) == only(IsoWeek.parse(expected))
