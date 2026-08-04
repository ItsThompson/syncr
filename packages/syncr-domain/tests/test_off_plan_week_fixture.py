"""The `off_plan_week` fixture, checked against the algebra and the zone rules that read it.

The fixture holds literals so that a later ticket asserting a clipped span, a denominator, or
a projected event against it is making a real claim. That only works if the literals are
right, so this suite is what earns them: every instant is re-derived here from `to_instant`
and `week_span`, and every stated figure from the interval algebra.

Two of its claims are the reason the fixture exists at all, and both are asserted rather than
described. The span's elapsed length is 68 hours where a wall-clock subtraction gives 67,
because the clocks go back inside it. And a frame occurrence sitting inside it leaves the
denominator ONCE: summing the two subtrahends would remove those eight hours twice, and the
wrong figure is stated here beside the right one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from syncr_domain.discretionary import discretionary_intervals, discretionary_time
from syncr_domain.fixtures.off_plan_week import OFF_PLAN_WEEK, OffPlanWeek, WallInterval, WallSpan
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.off_plan import OffPlanPeriod, OverlappingOffPlanError, require_disjoint
from syncr_domain.snap import is_on_snap_grid
from syncr_domain.weeks import week_span
from syncr_domain.zones import resolve_zone, to_instant

EMPTY = IntervalSet()


@pytest.fixture
def week() -> OffPlanWeek:
    return OFF_PLAN_WEEK


def derived(wall: WallInterval, zone: str) -> Interval:
    """The instants a wall-clock declaration names in ``zone``."""
    return Interval(
        to_instant(wall.start_at, wall.start_on, zone),
        to_instant(wall.end_at, wall.end_on, zone),
    )


def derived_span(wall: WallSpan, zone: str) -> Interval:
    start = to_instant(wall.at, wall.on, zone)
    return Interval(start, start + timedelta(minutes=wall.minutes))


def wall_minutes(wall: WallInterval) -> int:
    """What subtracting the two local times gives, ignoring the offset change between them."""
    naive_start = datetime.combine(wall.start_on, wall.start_at)
    naive_end = datetime.combine(wall.end_on, wall.end_at)
    return int((naive_end - naive_start).total_seconds() // 60)


# --------------------------------------------------------------------------------
# The literals
# --------------------------------------------------------------------------------


def test_the_week_span_literal_is_what_week_span_derives(week: OffPlanWeek) -> None:
    assert week_span(week.iso_week, week.profile) == week.week_span
    assert week.week_span.total_minutes() == week.week_span_minutes
    # A 169-hour week, so no figure here may be derived by assuming 168.
    assert week.week_span_minutes != 168 * 60


def test_the_off_plan_literal_is_the_stated_wall_declaration(week: OffPlanWeek) -> None:
    assert derived(week.off_plan_wall, week.zone) == week.off_plan
    assert week.off_plan.total_minutes() == week.off_plan_minutes


def test_the_pin_and_the_frame_literals_are_their_stated_wall_declarations(
    week: OffPlanWeek,
) -> None:
    assert derived_span(week.pin_wall, week.zone) == week.pin
    assert derived_span(week.frame_wall, week.zone) == week.frame_inside


def test_the_abutting_literal_is_its_stated_wall_declaration(week: OffPlanWeek) -> None:
    assert derived(week.abutting_wall, week.zone) == week.abutting


def test_the_whole_week_span_is_the_week_itself(week: OffPlanWeek) -> None:
    assert week.whole_week == week.week_span


def test_every_off_plan_bound_lands_on_the_quarter_hour(week: OffPlanWeek) -> None:
    for interval in (week.off_plan, week.abutting, week.whole_week):
        assert is_on_snap_grid(interval.start)
        assert is_on_snap_grid(interval.end)


# --------------------------------------------------------------------------------
# The three boundaries the span was chosen for
# --------------------------------------------------------------------------------


def test_the_span_starts_in_its_week_and_ends_in_the_following_one(week: OffPlanWeek) -> None:
    assert week.off_plan.start > week.week_span.start
    assert week.off_plan.start < week.week_span.end < week.off_plan.end
    assert week_span(week.following_week, week.profile).start == week.week_span.end


def test_the_span_holds_the_daylight_saving_transition(week: OffPlanWeek) -> None:
    # The clocks go back inside the span, so its elapsed length exceeds the difference of its
    # two wall times by exactly the hour that repeats.
    assert wall_minutes(week.off_plan_wall) == week.off_plan_wall_minutes
    assert week.off_plan_minutes - week.off_plan_wall_minutes == 60
    transition = to_instant(week.off_plan_wall.start_at, week.transition_date, week.zone)
    assert week.off_plan.start < transition < week.off_plan.end


def test_the_span_neither_starts_nor_ends_at_a_local_midnight(week: OffPlanWeek) -> None:
    # A period is not restricted to whole days. A fixture spanning midnight to midnight could
    # not tell a whole-day implementation from an instant-precision one.
    zone = resolve_zone(week.zone)
    for moment in (week.off_plan.start, week.off_plan.end):
        assert moment.astimezone(zone).time() != datetime.min.time()


def test_the_span_is_clipped_to_each_week_and_the_two_parts_are_the_whole(
    week: OffPlanWeek,
) -> None:
    off_plan = IntervalSet([week.off_plan])
    following = week_span(week.following_week, week.profile)

    inside = off_plan.clip(week.week_span).total_minutes()
    inside_following = off_plan.clip(following).total_minutes()

    assert inside == week.off_plan_minutes_inside_the_week
    assert inside_following == week.off_plan_minutes_inside_the_following_week
    assert inside + inside_following == week.off_plan_minutes


# --------------------------------------------------------------------------------
# What the fixture's consumers assert against it
# --------------------------------------------------------------------------------


def test_the_pin_sits_inside_the_off_plan_span(week: OffPlanWeek) -> None:
    assert IntervalSet([week.off_plan]).intersect(IntervalSet([week.pin])) == IntervalSet(
        [week.pin]
    )


def test_the_frame_occurrence_sits_inside_the_off_plan_span(week: OffPlanWeek) -> None:
    assert IntervalSet([week.off_plan]).intersect(IntervalSet([week.frame_inside])) == IntervalSet(
        [week.frame_inside]
    )
    # And it crosses the transition too, so it is eight elapsed hours over seven wall hours.
    assert week.frame_inside.total_minutes() == week.frame_wall.minutes == 8 * 60


def test_a_frame_span_inside_an_off_plan_span_leaves_the_denominator_once(
    week: OffPlanWeek,
) -> None:
    frame = IntervalSet([week.frame_inside])
    off_plan = IntervalSet([week.off_plan])

    unioned = discretionary_time(week.week_span, frame, EMPTY, EMPTY, off_plan)

    subtracted = off_plan.clip(week.week_span).total_minutes()
    assert unioned == week.week_span_minutes - subtracted
    # Summing the two subtrahends instead would remove the frame occurrence a second time,
    # which is a plausible-looking figure rather than a crash: the failure this fixture and
    # the union exist to make visible.
    summed = week.week_span_minutes - (subtracted + frame.total_minutes())
    assert summed == unioned - 8 * 60
    assert unioned > summed


def test_a_week_entirely_off_plan_has_no_discretionary_time(week: OffPlanWeek) -> None:
    whole_week = IntervalSet([week.whole_week])

    free = discretionary_intervals(week.week_span, EMPTY, EMPTY, EMPTY, whole_week)

    assert free == IntervalSet()
    assert free.total_minutes() == 0


def test_the_two_keep_frame_declarations_are_one_span_declared_two_ways(
    week: OffPlanWeek,
) -> None:
    assert week.keeping_frame.interval == week.dropping_frame.interval == week.off_plan
    assert week.keeping_frame.keep_frame is True
    assert week.dropping_frame.keep_frame is False
    assert week.keeping_frame.label != week.dropping_frame.label
    # Alternatives, never a pair: they cover the same instants, so storing both is refused.
    with pytest.raises(OverlappingOffPlanError):
        require_disjoint([week.keeping_frame, week.dropping_frame])


def test_the_abutting_period_may_be_declared_alongside_the_span_it_touches(
    week: OffPlanWeek,
) -> None:
    # The half-open reading, at the one boundary a user will actually hit: back on plan at
    # 09:00 on the Monday, and off again from 09:00 the same morning.
    assert week.abutting.start == week.off_plan.end

    require_disjoint([week.dropping_frame, OffPlanPeriod(interval=week.abutting)])
