"""Which weeks a span reaches into, at the boundary where the answer changes.

Every case here is a Monday. A period is half-open, so one ending at a Monday's local midnight
reaches nothing inside the week that starts there, and one ending a quarter of an hour later
reaches into it. Those two are the only interesting inputs, and they differ by fifteen minutes.

The zone is real (``Europe/London``) and one case sits over the autumn transition, because the
answer is resolved against real week spans and a span whose UTC and local dates disagree is
where a derivation that skipped the zone would still look right. Under a travel override the
spans themselves move, which is why the range is asked of ``week_span`` over the whole profile:
the property test holds the overlap reading against the range for generated zones and offsets,
and the measured London-to-Auckland example is its named case.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import assume, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from syncr_api.offplan.weeks import weeks_touching
from syncr_api.user_settings.solve_inputs import WeekRange
from syncr_domain.fixtures.off_plan_week import OFF_PLAN_WEEK
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek, week_span
from syncr_domain.zones import TravelOverride, ZoneProfile

LONDON = "Europe/London"
AUCKLAND = "Pacific/Auckland"

# 2026-W10 in London: an ordinary week, in GMT, so its local Mondays are 00:00 UTC.
WEEK_10 = IsoWeek.parse("2026-W10")
WEEK_11 = IsoWeek.parse("2026-W11")
MONDAY_OF_WEEK_11 = datetime(2026, 3, 9, 0, 0, tzinfo=UTC)

QUARTER_HOUR = timedelta(minutes=15)

# Zones whose offsets spread the plausible space: half-hour, quarter-hour and whole-hour
# shifts, both directions, plus Lord Howe's thirty-minute transition and Chatham's forty-five.
ZONES = (
    LONDON,
    AUCKLAND,
    "America/New_York",
    "Asia/Kolkata",
    "Australia/Lord_Howe",
    "Pacific/Chatham",
)


def only(week: IsoWeek) -> WeekRange:
    return WeekRange(first=week, last=week)


def home_profile(zone: str) -> ZoneProfile:
    return ZoneProfile(home_zone=zone)


def test_a_span_inside_one_week_touches_that_week_alone() -> None:
    friday_afternoon = Interval(
        datetime(2026, 3, 6, 14, 0, tzinfo=UTC), datetime(2026, 3, 6, 18, 0, tzinfo=UTC)
    )

    assert weeks_touching(friday_afternoon, profile=home_profile(LONDON)) == only(WEEK_10)


def test_a_span_ending_exactly_at_a_weeks_first_instant_does_not_touch_that_week() -> None:
    # The boundary the half-open reading exists for. The last instant this span covers is
    # 23:59 on the Sunday, so the week beginning at that midnight holds none of it and its
    # denominator did not change.
    ending_at_the_boundary = Interval(datetime(2026, 3, 6, 14, 0, tzinfo=UTC), MONDAY_OF_WEEK_11)

    assert weeks_touching(ending_at_the_boundary, profile=home_profile(LONDON)) == only(WEEK_10)


def test_a_span_ending_one_quarter_hour_later_does_touch_it() -> None:
    # The other side of the same boundary, fifteen minutes away: the first grid instant inside
    # the following week, which is the shortest period that can reach into it.
    crossing_the_boundary = Interval(
        datetime(2026, 3, 6, 14, 0, tzinfo=UTC), MONDAY_OF_WEEK_11 + QUARTER_HOUR
    )

    assert weeks_touching(crossing_the_boundary, profile=home_profile(LONDON)) == WeekRange(
        first=WEEK_10, last=WEEK_11
    )


def test_a_span_beginning_exactly_at_a_weeks_first_instant_touches_it() -> None:
    # And the opposite end: `start` IS inside the period, so a span beginning at the Monday's
    # local midnight belongs to the week that begins there and not to the one before it.
    beginning_at_the_boundary = Interval(MONDAY_OF_WEEK_11, MONDAY_OF_WEEK_11 + timedelta(hours=9))

    assert weeks_touching(beginning_at_the_boundary, profile=home_profile(LONDON)) == only(WEEK_11)


def test_a_whole_weeks_span_touches_that_week_alone() -> None:
    # `week_span` runs from one local Monday to the next, so a period covering a week exactly
    # ends where the following week begins and must not bump it.
    span = week_span(WEEK_10, OFF_PLAN_WEEK.profile)

    assert weeks_touching(span, profile=OFF_PLAN_WEEK.profile) == only(WEEK_10)


def test_the_friday_to_monday_span_touches_both_of_its_weeks() -> None:
    # The fixture's own span, over the week the clocks go back: the local date of its end is a
    # Monday in the following ISO week, and the transition inside it changes nothing here.
    assert weeks_touching(OFF_PLAN_WEEK.off_plan, profile=OFF_PLAN_WEEK.profile) == WeekRange(
        first=OFF_PLAN_WEEK.iso_week, last=OFF_PLAN_WEEK.following_week
    )


def test_a_span_of_several_weeks_touches_every_week_between_its_ends() -> None:
    fortnight = Interval(
        datetime(2026, 3, 6, 14, 0, tzinfo=UTC), datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
    )

    assert weeks_touching(fortnight, profile=home_profile(LONDON)) == WeekRange(
        first=WEEK_10, last=IsoWeek.parse("2026-W13")
    )


def test_a_span_shorter_than_the_grid_still_names_the_week_it_sits_in() -> None:
    # The clamp. Such a span cannot be declared, because both bounds land on the quarter hour,
    # but this function does not require that, and without the clamp its last-covered instant
    # would fall a quarter of an hour before its own start and name the week before it.
    a_minute_after_midnight = Interval(MONDAY_OF_WEEK_11, MONDAY_OF_WEEK_11 + timedelta(minutes=1))

    assert weeks_touching(a_minute_after_midnight, profile=home_profile(LONDON)) == only(WEEK_11)


@pytest.mark.parametrize(
    ("zone", "expected"),
    [(LONDON, "2026-W11"), (AUCKLAND, "2026-W12")],
    ids=["london", "auckland"],
)
def test_the_week_is_resolved_in_the_tenants_own_zone(zone: str, expected: str) -> None:
    # 2026-03-15 23:30 UTC is Sunday night in London and Monday lunchtime in Auckland, so the
    # same instant sits in two different ISO weeks. A derivation reading UTC dates would answer
    # London's for both.
    sunday_night = Interval(
        datetime(2026, 3, 15, 23, 30, tzinfo=UTC), datetime(2026, 3, 15, 23, 45, tzinfo=UTC)
    )

    assert weeks_touching(sunday_night, profile=home_profile(zone)) == only(IsoWeek.parse(expected))


# The measured example. Home Europe/London, an override to Pacific/Auckland over 2026-03-01 to
# 2026-03-22, and a fifteen-minute span at 2026-03-08 11:00Z: in London that is Sunday 11:00,
# inside W10, but the override makes Auckland's Monday of W11 begin at exactly 11:00Z (UTC+13),
# so the span is the first quarter hour of Auckland's W11 and W11 is what must be bumped. The
# home-zone reading named W10, whose denominator never changed.
AUCKLAND_OVERRIDE = TravelOverride(
    start_date=date(2026, 3, 1), end_date=date(2026, 3, 22), zone=AUCKLAND
)
LONDON_TO_AUCKLAND = ZoneProfile(home_zone=LONDON, travel_overrides=(AUCKLAND_OVERRIDE,))
FIRST_QUARTER_HOUR_OF_AUCKLANDS_MONDAY = Interval(
    datetime(2026, 3, 8, 11, 0, tzinfo=UTC), datetime(2026, 3, 8, 11, 15, tzinfo=UTC)
)


def test_a_span_at_an_override_seam_bumps_the_active_zone_week() -> None:
    assert weeks_touching(
        FIRST_QUARTER_HOUR_OF_AUCKLANDS_MONDAY, profile=LONDON_TO_AUCKLAND
    ) == only(IsoWeek.parse("2026-W11"))


# Spans are generated on the quarter-hour grid, because those are the spans a user can declare:
# both bounds on grid means the span is a whole number of quarter hours, which is what makes
# "the week holding the last covered instant" and "every overlapping week" the same question.
SEAM_ANCHOR = datetime(2026, 3, 8, 11, 0, tzinfo=UTC)


def _overlapping_range(span: Interval, profile: ZoneProfile) -> WeekRange:
    """The property's own reading: every week whose span overlaps ``span``, as one range."""
    overlapping = [week for week in _weeks_around(span) if week_span(week, profile).overlaps(span)]
    return WeekRange(first=min(overlapping), last=max(overlapping))


def _weeks_around(span: Interval) -> list[IsoWeek]:
    """Six weeks either side of the week holding ``span``'s start, earliest first.

    No zone's local date disagrees with the UTC date by more than a day, so no bound of any
    week the span can overlap falls outside this window.
    """
    middle = IsoWeek.containing(span.start.astimezone(UTC).date())
    first = middle
    for _ in range(6):
        first = first.preceding()
    weeks = [first]
    for _ in range(12):
        weeks.append(weeks[-1].following())
    return weeks


@hyp_settings(max_examples=200)
@given(
    home=st.sampled_from(ZONES),
    away=st.sampled_from(ZONES),
    day_offset=st.integers(min_value=-14, max_value=14),
    window_days=st.integers(min_value=0, max_value=28),
    steps_from_anchor=st.integers(min_value=-32, max_value=96),
    length_steps=st.integers(min_value=1, max_value=96),
)
def test_the_range_names_exactly_the_weeks_whose_spans_the_interval_overlaps(
    home: str,
    away: str,
    day_offset: int,
    window_days: int,
    steps_from_anchor: int,
    length_steps: int,
) -> None:
    assume(home != away)
    profile = ZoneProfile(
        home_zone=home,
        travel_overrides=(
            TravelOverride(
                start_date=date(2026, 3, 8) + timedelta(days=day_offset),
                end_date=date(2026, 3, 8) + timedelta(days=day_offset + window_days),
                zone=away,
            ),
        ),
    )
    start = SEAM_ANCHOR + steps_from_anchor * QUARTER_HOUR
    span = Interval(start, start + length_steps * QUARTER_HOUR)

    assert weeks_touching(span, profile=profile) == _overlapping_range(span, profile)
