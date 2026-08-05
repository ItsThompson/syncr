"""Which weeks the horizon covers, and when it next moves. Pure, over literals.

The horizon is a window of LOCAL dates, so two things can be wrong in ways no integration test would
show: the count of weeks a window touches depends on the weekday it starts on, and a window computed
in UTC is a day out for half the world. Both are driven here against dates chosen for the boundary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from syncr_api.horizon.weeks import (
    horizon_dates,
    horizon_weeks,
    next_local_midnight,
    weeks_reaching_the_horizon,
)
from syncr_api.user_settings.zone_reading import local_date
from syncr_domain.weeks import IsoWeek

LONDON = "Europe/London"
AUCKLAND = "Pacific/Auckland"
LOS_ANGELES = "America/Los_Angeles"

HORIZON_DAYS_DEFAULT = 14

MONDAY = date(2026, 2, 9)
SUNDAY = date(2026, 2, 15)


def test_the_horizon_starts_today_and_is_half_open_at_the_far_end() -> None:
    covered = horizon_dates(today=MONDAY, horizon_days=3)

    assert covered == (MONDAY, date(2026, 2, 10), date(2026, 2, 11))


def test_a_one_day_horizon_covers_today() -> None:
    """The stored floor is one day, so the shortest horizon a tenant can set still holds a week."""
    assert horizon_dates(today=MONDAY, horizon_days=1) == (MONDAY,)
    assert horizon_weeks(today=MONDAY, horizon_days=1) == (IsoWeek(2026, 7),)


def test_a_fortnight_from_a_monday_touches_two_weeks() -> None:
    assert horizon_weeks(today=MONDAY, horizon_days=HORIZON_DAYS_DEFAULT) == (
        IsoWeek(2026, 7),
        IsoWeek(2026, 8),
    )


def test_the_weeks_that_can_reach_the_horizon_include_the_one_before_it() -> None:
    """A block belongs to the week its start falls in, and that week may have left the horizon.

    The Sunday-night ``Sleep`` occurrence of the week that is ending runs into the Monday the
    horizon begins on. Read over the horizon's own weeks alone it is not desired, while the
    provider's window-bounded read does return it, so the diff deletes it: the in-progress sleep
    event would leave the phone at local midnight every Monday.
    """
    assert weeks_reaching_the_horizon(today=MONDAY, horizon_days=HORIZON_DAYS_DEFAULT) == (
        IsoWeek(2026, 6),
        IsoWeek(2026, 7),
        IsoWeek(2026, 8),
    )


def test_the_week_before_is_not_added_twice_when_the_horizon_already_holds_it() -> None:
    """On every day but a Monday, yesterday is in the horizon's first week already."""
    tuesday = MONDAY + timedelta(days=1)

    assert weeks_reaching_the_horizon(today=tuesday, horizon_days=HORIZON_DAYS_DEFAULT) == (
        horizon_weeks(today=tuesday, horizon_days=HORIZON_DAYS_DEFAULT)
    )


@pytest.mark.parametrize("offset", range(7))
def test_the_reaching_weeks_are_the_horizon_weeks_plus_at_most_one(offset: int) -> None:
    """Whatever weekday it starts on: never fewer, never more than one extra, chronological."""
    today = MONDAY + timedelta(days=offset)
    covered = horizon_weeks(today=today, horizon_days=HORIZON_DAYS_DEFAULT)

    reaching = weeks_reaching_the_horizon(today=today, horizon_days=HORIZON_DAYS_DEFAULT)

    assert set(covered) <= set(reaching)
    assert len(reaching) - len(covered) in {0, 1}
    assert list(reaching) == sorted(reaching)
    # And the earliest one holds the day before the horizon starts, which is the whole point.
    assert IsoWeek.containing(today - timedelta(days=1)) == reaching[0]


def test_a_fortnight_from_a_sunday_touches_three() -> None:
    """Which of two or three is the weekday's doing rather than a caller's choice."""
    assert horizon_weeks(today=SUNDAY, horizon_days=HORIZON_DAYS_DEFAULT) == (
        IsoWeek(2026, 7),
        IsoWeek(2026, 8),
        IsoWeek(2026, 9),
    )


@pytest.mark.parametrize("offset", range(7), ids=[f"weekday_{offset}" for offset in range(7)])
def test_the_weeks_are_chronological_whatever_weekday_the_horizon_starts_on(offset: int) -> None:
    """Chronological order is what plans the current week before next week on first run."""
    weeks = horizon_weeks(today=MONDAY + timedelta(days=offset), horizon_days=HORIZON_DAYS_DEFAULT)

    assert list(weeks) == sorted(weeks)
    assert weeks[0] == IsoWeek.containing(MONDAY + timedelta(days=offset))


def test_a_horizon_crossing_a_year_boundary_names_both_years_weeks() -> None:
    """2026 holds 53 ISO weeks, so the week after its last is the first of 2027 rather than W54."""
    weeks = horizon_weeks(today=date(2026, 12, 28), horizon_days=HORIZON_DAYS_DEFAULT)

    assert weeks == (IsoWeek(2026, 53), IsoWeek(2027, 1))


def test_every_week_the_horizon_names_holds_one_of_its_dates() -> None:
    """The invariant the derivation rests on, so a week is never named for a date outside it."""
    covered = set(horizon_dates(today=SUNDAY, horizon_days=HORIZON_DAYS_DEFAULT))
    weeks = horizon_weeks(today=SUNDAY, horizon_days=HORIZON_DAYS_DEFAULT)

    for week in weeks:
        assert covered & set(week.dates())


def test_no_week_the_horizon_covers_is_left_out() -> None:
    """The other direction: every covered date's week is named."""
    named = set(horizon_weeks(today=SUNDAY, horizon_days=HORIZON_DAYS_DEFAULT))

    for day in horizon_dates(today=SUNDAY, horizon_days=HORIZON_DAYS_DEFAULT):
        assert IsoWeek.containing(day) in named


def test_the_next_midnight_is_the_local_one_rather_than_the_utc_one() -> None:
    """Half past midnight in Auckland is still yesterday in UTC, so the two answers differ by a day.

    Computed in UTC, a horizon would advance thirteen hours late here, and the week it brought in
    would be the week the user stopped looking at yesterday.
    """
    just_past_local_midnight = datetime(2026, 2, 9, 11, 30, tzinfo=UTC)

    assert next_local_midnight(just_past_local_midnight, AUCKLAND) == datetime(
        2026, 2, 10, 11, 0, tzinfo=UTC
    )


def test_the_next_midnight_west_of_greenwich_is_later_the_same_utc_day() -> None:
    evening_in_los_angeles = datetime(2026, 2, 10, 3, 0, tzinfo=UTC)

    assert next_local_midnight(evening_in_los_angeles, LOS_ANGELES) == datetime(
        2026, 2, 10, 8, 0, tzinfo=UTC
    )


def test_the_next_midnight_is_always_ahead_of_now() -> None:
    """Including at the instant of midnight itself, which is the tick that would loop otherwise."""
    at_midnight = datetime(2026, 2, 9, 0, 0, tzinfo=UTC)

    assert next_local_midnight(at_midnight, LONDON) > at_midnight


def test_a_midnight_the_clocks_move_through_resolves_through_the_zone_layer() -> None:
    """London's clocks move at 01:00, so its midnight is never skipped or repeated: a control.

    The zone layer is the one implementation of a gap or a repeat, and this asserts the midnight is
    resolved through it rather than by date arithmetic that assumes a day is 24 hours: the instant
    below is 23 hours after the previous local midnight, not 24.
    """
    spring_forward_eve = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)

    midnight = next_local_midnight(spring_forward_eve, LONDON)

    assert midnight == datetime(2026, 3, 29, 0, 0, tzinfo=UTC)
    assert next_local_midnight(midnight, LONDON) - midnight == timedelta(hours=23)


def test_the_midnight_of_a_zone_is_that_zones_own_wall_time() -> None:
    """A control on the two above: whatever the zone, the instant is local 00:00 on a later date."""
    from zoneinfo import ZoneInfo

    now = datetime(2026, 2, 9, 15, 0, tzinfo=UTC)

    for zone in (LONDON, AUCKLAND, LOS_ANGELES):
        local = next_local_midnight(now, zone).astimezone(ZoneInfo(zone))
        assert local.time() == time(0, 0)


# Egypt reinstated DST in 2023 and moves its clocks AT midnight, on the last Friday of April and
# again in October. So the local midnight of 2023-04-28 in Cairo does not exist, and the local
# midnight of 2023-10-26 happens twice. Both are the case the due-ness gate rests on, and no zone
# whose transition falls at 02:00 can exercise either.
CAIRO = "Africa/Cairo"
CAIRO_SPRING_EVE = datetime(2023, 4, 27, 12, 0, tzinfo=UTC)
CAIRO_AUTUMN_EVE = datetime(2023, 10, 25, 12, 0, tzinfo=UTC)


def test_a_local_midnight_the_clocks_skip_resolves_forward_by_the_gap() -> None:
    """Cairo jumps 23:59:59 to 01:00, so 2023-04-28 00:00 names no instant at all there.

    Date arithmetic that assumed a day is 24 hours would produce that nonexistent wall time. Routed
    through the zone layer, the gap shifts forward, which is the same rule every other declared wall
    time in this product follows.
    """
    midnight = next_local_midnight(CAIRO_SPRING_EVE, CAIRO)

    assert midnight.astimezone(ZoneInfo(CAIRO)).time() == time(1, 0), "shifted by the one-hour gap"
    assert midnight > CAIRO_SPRING_EVE


def test_a_local_midnight_the_clocks_repeat_takes_the_first_occurrence() -> None:
    """The other direction: Cairo's October change replays midnight, and the earlier one wins.

    Taking the second would delay the horizon's advance by the whole repeated hour.
    """
    midnight = next_local_midnight(CAIRO_AUTUMN_EVE, CAIRO)
    local = midnight.astimezone(ZoneInfo(CAIRO))

    assert local.time() == time(0, 0)
    assert local.utcoffset() == timedelta(hours=3), "the first occurrence, still on summer time"


@pytest.mark.parametrize(
    "eve", [CAIRO_SPRING_EVE, CAIRO_AUTUMN_EVE], ids=["clocks forward", "clocks back"]
)
def test_a_transition_still_advances_the_local_date_by_exactly_one(eve: datetime) -> None:
    """The property the due-ness gate actually needs, either side of either transition.

    The horizon is a window of local dates, so what the gate owes is that the next due instant falls
    on the next local date: one earlier and the pass repeats a day, one later and a week entering
    the horizon waits out a whole extra day.
    """
    midnight = next_local_midnight(eve, CAIRO)

    assert local_date(midnight, CAIRO) == local_date(eve, CAIRO) + timedelta(days=1)
