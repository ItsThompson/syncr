"""The `dst_weeks` fixture, checked against the algebra that reads it.

The fixture holds literals so that a later ticket asserting `week_span`, a grid axis,
or a projector emission against it is making a real claim. That only works if the
literals are right, so this suite is what earns them: every figure in the fixture is
re-derived here from `to_instant`, `week_span`, and the fixture's own stated routine.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from syncr_domain.fixtures.dst_weeks import DST_WEEKS, FALL_BACK, SPRING_FORWARD, DstWeek
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.weeks import LOCAL_MIDNIGHT, IsoWeek, week_span
from syncr_domain.zones import resolve_zone, to_instant

ONE_DAY = timedelta(days=1)


def test_the_fixture_holds_one_week_of_each_kind(dst_weeks: tuple[DstWeek, ...]) -> None:
    assert dst_weeks == (SPRING_FORWARD, FALL_BACK)
    assert SPRING_FORWARD.span_minutes == 167 * 60
    assert FALL_BACK.span_minutes == 169 * 60
    assert {week.zone for week in dst_weeks} == {"Europe/London"}


@pytest.mark.parametrize("week", DST_WEEKS, ids=lambda week: week.label)
class TestEveryDstWeek:
    def test_its_transition_falls_on_the_sunday_of_its_own_week(self, week: DstWeek) -> None:
        assert week.transition_date.isoweekday() == 7
        assert week.iso_week.monday() == week.transition_date - timedelta(days=6)

    def test_the_span_literal_is_what_week_span_derives(self, week: DstWeek) -> None:
        assert week_span(week.iso_week, week.profile) == week.span
        assert week.span.total_minutes() == week.span_minutes

    def test_the_local_transition_day_literal_is_a_local_midnight_pair(self, week: DstWeek) -> None:
        derived = Interval(
            to_instant(LOCAL_MIDNIGHT, week.transition_date, week.zone),
            to_instant(LOCAL_MIDNIGHT, week.transition_date + ONE_DAY, week.zone),
        )

        assert derived == week.local_transition_day
        assert week.local_transition_day.total_minutes() == week.local_transition_day_minutes

    def test_the_transition_day_is_not_24_hours(self, week: DstWeek) -> None:
        assert week.local_transition_day_minutes != 24 * 60

    def test_the_sunday_night_frame_is_the_stated_routine(self, week: DstWeek) -> None:
        start = to_instant(week.frame_target_time, week.transition_date, week.zone)

        assert week.sunday_night_frame == Interval(
            start, start + timedelta(minutes=week.frame_duration_minutes)
        )
        assert week.sunday_night_frame.total_minutes() == week.frame_duration_minutes

    def test_the_frame_starts_in_its_week_and_ends_in_the_next(self, week: DstWeek) -> None:
        following = week_span(week.iso_week.following(), week.profile)

        assert week.span.overlaps(week.sunday_night_frame)
        assert week.sunday_night_frame.end > week.span.end
        assert following.overlaps(week.sunday_night_frame)

    def test_the_overhang_is_the_next_week_occupancy(self, week: DstWeek) -> None:
        following = week_span(week.iso_week.following(), week.profile)
        frame = IntervalSet([week.sunday_night_frame])

        overhang = frame.clip(following)

        assert overhang.total_minutes() > 0
        assert overhang.total_minutes() < week.frame_duration_minutes
        assert frame.clip(week.span).total_minutes() + overhang.total_minutes() == (
            week.frame_duration_minutes
        )

    def test_the_frame_is_owned_by_the_week_its_start_falls_in(self, week: DstWeek) -> None:
        zone = resolve_zone(week.zone)
        frame = week.sunday_night_frame

        assert IsoWeek.containing(frame.start.astimezone(zone).date()) == week.iso_week
        assert IsoWeek.containing(frame.end.astimezone(zone).date()) == week.iso_week.following()
