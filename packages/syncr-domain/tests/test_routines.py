"""The Routine's invariants, and what the frame does at a wall-clock boundary.

Two halves. The invariants are literal arithmetic: a duration, a floor that defaults to
equality, and a band that shifts rather than shrinks. The occurrence half is where the
expensive defects live, so every claim here names ``Europe/London`` and a real transition
date, and the two Sunday-night frames are asserted against
``syncr_domain.fixtures.dst_weeks``, whose instants are literals written before this module
existed.

No offset is mocked anywhere. A mocked offset asserts what this package already believes
rather than what the tz database says, which is the failure the fixture exists to prevent.

The reading under test in every occurrence assertion is that **a duration is elapsed
minutes**. The alternative reading, wall-clock arithmetic, is asserted as the wrong answer
rather than merely left out: it produces a plausible interval, so nothing else in the
system would report it as a fault.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest

from syncr_domain.errors import DomainError
from syncr_domain.fixtures.dst_weeks import DST_WEEKS, LONDON, DstWeek
from syncr_domain.routines import (
    MAX_DURATION_MINUTES,
    MAX_FLEX_BAND_MINUTES,
    MIN_DURATION_MINUTES,
    RoutineError,
    RoutineSpan,
    SpanField,
)
from syncr_domain.zones import ZoneError, resolve_zone

if TYPE_CHECKING:
    from syncr_domain.intervals import Instant

TOKYO = "Asia/Tokyo"
# Samoa moved west of the date line and skipped 2011-12-30 entirely: a local date with no
# instants at all.
APIA = "Pacific/Apia"
# Lord Howe Island shifts by thirty minutes rather than an hour, so it is where a rule that
# assumed an hour-long gap would show.
LORD_HOWE = "Australia/Lord_Howe"

SPRING_FORWARD = date(2026, 3, 29)  # 01:00 GMT jumps to 02:00 BST
FALL_BACK = date(2026, 10, 25)  # 02:00 BST repeats as 01:00 GMT
LORD_HOWE_SPRING_FORWARD = date(2026, 10, 4)  # 02:00 jumps to 02:30

SLEEP_TARGET = time(23, 0)
SLEEP_MINUTES = 8 * 60


def sleep(minimum: int = SLEEP_MINUTES, *, flex_band_minutes: int = 0) -> RoutineSpan:
    """The reference frame entry: ``Sleep 23:00 + 8h``, inelastic unless given a floor."""
    return RoutineSpan(
        target_time=SLEEP_TARGET,
        duration_minutes=SLEEP_MINUTES,
        min_duration_minutes=minimum,
        flex_band_minutes=flex_band_minutes,
    )


def local(moment: Instant, zone: str) -> datetime:
    """``moment`` read as wall time in ``zone``, for the assertions about what a user sees."""
    return moment.astimezone(resolve_zone(zone))


# --------------------------------------------------------------------------------
# A routine is a span, not a marker
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("duration", [0, -1, -480])
def test_a_routine_without_a_duration_is_refused(duration: int) -> None:
    # Not defaulted and not clamped. Without a duration on the frame there is nothing to
    # subtract, so every discretionary figure downstream would be computed from an
    # incomplete denominator and would look entirely plausible.
    with pytest.raises(RoutineError, match="nothing to subtract") as refused:
        RoutineSpan(SLEEP_TARGET, duration, 1, 0)

    assert refused.value.field is SpanField.DURATION


def test_a_routine_longer_than_a_day_is_refused() -> None:
    # A routine materializes once per local date, so a longer span would overlap its own
    # next occurrence.
    RoutineSpan(SLEEP_TARGET, MAX_DURATION_MINUTES, MAX_DURATION_MINUTES, 0)

    with pytest.raises(RoutineError) as refused:
        RoutineSpan(SLEEP_TARGET, MAX_DURATION_MINUTES + 1, 1, 0)

    assert refused.value.field is SpanField.DURATION


def test_the_shortest_legal_routine_is_a_minute_of_span() -> None:
    span = RoutineSpan(SLEEP_TARGET, MIN_DURATION_MINUTES, MIN_DURATION_MINUTES, 0)

    assert span.duration_minutes == 1
    assert span.occurrence_on(date(2026, 2, 10), LONDON).total_minutes() == 1


def test_a_routine_carries_no_area() -> None:
    # The entity-level half of "routines are excluded from Area budget arithmetic". A span
    # with an Area could be given a pigment and a budget row, and the frame would start
    # competing for the time it defines.
    named = {field.name for field in fields(RoutineSpan)}

    assert named == {
        "target_time",
        "duration_minutes",
        "min_duration_minutes",
        "flex_band_minutes",
    }
    assert not [name for name in named if "area" in name]


# --------------------------------------------------------------------------------
# The floor, and the default that makes every routine inelastic
# --------------------------------------------------------------------------------


def test_a_minimum_equal_to_the_target_is_inelastic() -> None:
    assert sleep().is_elastic is False


def test_a_minimum_below_the_target_is_what_makes_a_routine_elastic() -> None:
    # The predicate a tradeoff enumerator reads before offering to shorten a routine. It
    # exists here so the rule holds before its consumer does.
    assert sleep(minimum=6 * 60).is_elastic is True


@pytest.mark.parametrize("minimum", [0, -1, SLEEP_MINUTES + 1, SLEEP_MINUTES + 480])
def test_a_minimum_outside_its_target_is_refused(minimum: int) -> None:
    with pytest.raises(RoutineError) as refused:
        sleep(minimum=minimum)

    assert refused.value.field is SpanField.MINIMUM


def test_a_floor_of_one_minute_below_the_target_is_elastic() -> None:
    # The boundary of the predicate, on the tight side: elasticity is a strict comparison,
    # so one minute of give is give.
    assert sleep(minimum=SLEEP_MINUTES - 1).is_elastic is True


# --------------------------------------------------------------------------------
# The band shifts, it does not shrink
# --------------------------------------------------------------------------------


def test_a_band_is_accepted_up_to_half_a_day() -> None:
    assert sleep(flex_band_minutes=0).flex_band_minutes == 0
    assert sleep(flex_band_minutes=MAX_FLEX_BAND_MINUTES).flex_band_minutes == 720


@pytest.mark.parametrize("band", [-1, MAX_FLEX_BAND_MINUTES + 1])
def test_a_band_outside_the_stated_range_is_refused(band: int) -> None:
    with pytest.raises(RoutineError) as refused:
        sleep(flex_band_minutes=band)

    assert refused.value.field is SpanField.FLEX_BAND


def test_a_band_does_not_change_the_span_it_may_move() -> None:
    # The band is how far a placement may MOVE the target. Nothing resizes a routine, so a
    # wide band and no band produce the same occurrence from the same target time.
    on = date(2026, 2, 10)

    assert sleep(flex_band_minutes=0).occurrence_on(on, LONDON) == sleep(
        flex_band_minutes=MAX_FLEX_BAND_MINUTES
    ).occurrence_on(on, LONDON)


# --------------------------------------------------------------------------------
# Target times are local
# --------------------------------------------------------------------------------


def test_the_same_target_time_is_a_different_instant_in_a_different_zone() -> None:
    # `Wake 05:00` means 05:00 wherever the user is, which is the whole reason the target
    # is stored as wall time rather than as an instant.
    wake = RoutineSpan(time(5, 0), 30, 30, 0)
    on = date(2026, 2, 10)

    in_london = wake.occurrence_on(on, LONDON)
    in_tokyo = wake.occurrence_on(on, TOKYO)

    assert in_london.start == datetime(2026, 2, 10, 5, 0, tzinfo=UTC)
    assert in_tokyo.start == datetime(2026, 2, 9, 20, 0, tzinfo=UTC)
    assert local(in_london.start, LONDON).time() == local(in_tokyo.start, TOKYO).time()


def test_the_offset_is_read_for_the_date_rather_than_taken_as_fixed() -> None:
    # Europe/London kept UTC+1 all year from 1968 to 1971, so a zone's offset is a function
    # of the date and not of the zone. A frame that resolved one offset per zone would be
    # an hour out for every day of those years.
    wake = RoutineSpan(time(5, 0), 30, 30, 0)

    assert wake.occurrence_on(date(1970, 1, 1), LONDON).start == datetime(
        1970, 1, 1, 4, 0, tzinfo=UTC
    )
    assert wake.occurrence_on(date(1972, 1, 1), LONDON).start == datetime(
        1972, 1, 1, 5, 0, tzinfo=UTC
    )


def test_a_target_time_carrying_a_zone_is_refused() -> None:
    # A wall time names no zone. One that carries an offset would be stored as a wall time with
    # the offset dropped, which is a frame silently placed in the wrong hour. Refused where the
    # span is built, so no writer can get one in, and refused as a RoutineError rather than
    # late inside `occurrence_on`, where only a ZoneError would name it.
    with pytest.raises(RoutineError, match="names no zone") as refused:
        RoutineSpan(time(5, 0, tzinfo=UTC), 30, 30, 0)

    assert refused.value.field is SpanField.TARGET_TIME


@pytest.mark.parametrize(
    "target",
    [time(5, 0, 30), time(5, 0, 0, 250000), time(5, 0, 30, 1)],
    ids=["a second", "a microsecond", "both"],
)
def test_a_target_time_below_minute_resolution_is_refused(target: time) -> None:
    # Every duration here is a count of minutes, so a span starting mid-minute could not be one
    # of them: `total_minutes` truncates, and the frame would be short by the remainder.
    with pytest.raises(RoutineError, match="minute-resolution") as refused:
        RoutineSpan(target, 30, 30, 0)

    assert refused.value.field is SpanField.TARGET_TIME


def test_a_target_time_on_any_whole_minute_is_accepted() -> None:
    # The control for both refusals: they must distinguish rather than refuse a time.
    for target in (time(0, 0), time(5, 7), time(23, 59)):
        assert RoutineSpan(target, 30, 30, 0).target_time == target


def test_a_datetime_is_not_a_date_to_resolve_against() -> None:
    # A datetime IS a date to the type system, so this rejection is the only thing standing
    # between combining one and silently dropping the time it already carried.
    with pytest.raises(ZoneError, match="datetime"):
        sleep().occurrence_on(datetime(2026, 2, 10, 9, 0, tzinfo=UTC), LONDON)


def test_every_rejection_the_frame_can_produce_is_a_domain_error() -> None:
    # A boundary accepting a routine from the wire catches one category. A rejection that
    # escapes it reaches the client as a 500 rather than as a stated refusal.
    with pytest.raises(DomainError):
        sleep(minimum=0)
    with pytest.raises(DomainError):
        sleep().occurrence_on(date(2026, 2, 10), "Europe/Lundon")


# --------------------------------------------------------------------------------
# The occurrence, at a daylight-saving boundary
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("week", DST_WEEKS, ids=[week.label for week in DST_WEEKS])
def test_the_sunday_night_frame_is_the_span_the_fixture_records(week: DstWeek) -> None:
    # Asserted against literals written for the interval and grid layers before this module
    # existed, so the frame and everything else that reads a transition week agree by
    # construction rather than by two authors reaching the same number.
    span = RoutineSpan(week.frame_target_time, week.frame_duration_minutes, 1, 0)

    assert span.occurrence_on(week.transition_date, week.zone) == week.sunday_night_frame


def test_a_night_containing_a_spring_forward_keeps_its_eight_hours() -> None:
    # 2026-03-28 23:00 local, over the morning the clocks go forward. The night reads as
    # nine hours of wall clock and is eight hours of sleep.
    night = sleep().occurrence_on(date(2026, 3, 28), LONDON)

    assert night.total_minutes() == SLEEP_MINUTES
    assert local(night.start, LONDON) == datetime(2026, 3, 28, 23, 0, tzinfo=resolve_zone(LONDON))
    assert local(night.end, LONDON).time() == time(8, 0)
    # Wall-clock arithmetic would end it at 07:00 local, having spent an hour of a floor
    # the solver is forbidden to spend silently.
    assert local(night.end, LONDON).time() != time(7, 0)


def test_a_night_containing_a_fall_back_keeps_its_eight_hours() -> None:
    # 2026-10-24 23:00 local, over the morning the clocks go back. Seven hours of wall
    # clock, eight hours of sleep.
    night = sleep().occurrence_on(date(2026, 10, 24), LONDON)

    assert night.total_minutes() == SLEEP_MINUTES
    assert local(night.end, LONDON).time() == time(6, 0)
    # And the wall-clock reading would hand the sleeper a ninth hour nobody slept.
    assert local(night.end, LONDON).time() != time(7, 0)


def test_the_duration_cap_does_not_keep_an_occurrence_clear_of_its_own_next_one() -> None:
    # The cap is a cap on the day a routine names, and nothing more. A spring-forward local day
    # is 23 hours, so the longest legal span overlaps the next date's occurrence, and no smaller
    # positive cap fixes it: a date the zone skips gives two dates one interval at any duration.
    # Frame overlap belongs to the layout stage rather than to a bound here, and these are the
    # figures it has to answer for.
    eve = date(2026, 3, 28)
    tomorrow = eve + timedelta(days=1)

    longest = RoutineSpan(SLEEP_TARGET, MAX_DURATION_MINUTES, 1, 0)
    assert longest.occurrence_on(eve, LONDON).overlaps(longest.occurrence_on(tomorrow, LONDON))
    assert longest.occurrence_on(eve, LONDON).end - longest.occurrence_on(
        tomorrow, LONDON
    ).start == timedelta(hours=1)

    # One minute over the local day is enough, and one minute under is not: 23 hours is the
    # boundary, not 24.
    over = RoutineSpan(SLEEP_TARGET, 23 * 60 + 1, 1, 0)
    abutting = RoutineSpan(SLEEP_TARGET, 23 * 60, 1, 0)
    assert over.occurrence_on(eve, LONDON).overlaps(over.occurrence_on(tomorrow, LONDON))
    assert not abutting.occurrence_on(eve, LONDON).overlaps(
        abutting.occurrence_on(tomorrow, LONDON)
    )

    # And on the date Samoa skipped, the two dates are one interval however short the routine is.
    minimal = RoutineSpan(time(5, 0), MIN_DURATION_MINUTES, 1, 0)
    assert minimal.occurrence_on(date(2011, 12, 30), APIA) == minimal.occurrence_on(
        date(2011, 12, 31), APIA
    )


def test_a_target_time_inside_a_spring_forward_gap_shifts_forward() -> None:
    # 01:30 does not exist on 2026-03-29: 01:00 GMT jumps straight to 02:00 BST. The
    # routine takes the instant 01:30 would have been, which reads as 02:30 local, so the
    # morning keeps its order instead of collapsing onto the transition boundary.
    span = RoutineSpan(time(1, 30), 60, 60, 0)

    inside_the_gap = span.occurrence_on(SPRING_FORWARD, LONDON)

    assert inside_the_gap.start == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    assert local(inside_the_gap.start, LONDON).time() == time(2, 30)


def test_two_target_times_straddling_a_gap_resolve_to_one_instant() -> None:
    # The consequence of shifting forward, stated rather than discovered: the mapping is not
    # one-to-one across a gap, so 01:30 and 02:30 start together on that one morning. A
    # caller needing frame entries distinct has to separate them itself.
    inside = RoutineSpan(time(1, 30), 60, 60, 0).occurrence_on(SPRING_FORWARD, LONDON)
    after = RoutineSpan(time(2, 30), 60, 60, 0).occurrence_on(SPRING_FORWARD, LONDON)

    assert inside.start == after.start


def test_a_gap_of_half_an_hour_collides_the_same_way_a_whole_hour_does() -> None:
    # The collision is a property of the gap, not of an hour. Lord Howe Island shifts by thirty
    # minutes, so 02:00 lands on 02:30 and meets the routine that targets 02:30, which is the
    # same one-instant collision an hour-long gap produces.
    inside = RoutineSpan(time(2, 0), 60, 60, 0).occurrence_on(LORD_HOWE_SPRING_FORWARD, LORD_HOWE)
    after = RoutineSpan(time(2, 30), 60, 60, 0).occurrence_on(LORD_HOWE_SPRING_FORWARD, LORD_HOWE)

    assert inside.start == after.start
    assert local(inside.start, LORD_HOWE).time() == time(2, 30)


def test_a_target_time_that_happens_twice_takes_the_first_occurrence() -> None:
    # 01:30 occurs twice on 2026-10-25. Taking the earlier offset keeps the frame's order
    # within the day and makes that day 25 hours long rather than silently 24.
    span = RoutineSpan(time(1, 30), 60, 60, 0)

    ambiguous = span.occurrence_on(FALL_BACK, LONDON)

    assert ambiguous.start == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    # The second occurrence is an hour later and is not what the frame takes.
    assert ambiguous.start != datetime(2026, 10, 25, 1, 30, tzinfo=UTC)


@pytest.mark.parametrize("on", [SPRING_FORWARD, FALL_BACK, date(2026, 2, 10)])
def test_a_midnight_target_starts_the_local_date_it_names(on: date) -> None:
    # Midnight is the one target time where being an hour out moves the occurrence onto
    # another date, which is the key an outcome is recorded against.
    span = RoutineSpan(time(0, 0), 30, 30, 0)

    midnight = span.occurrence_on(on, LONDON)

    assert local(midnight.start, LONDON).date() == on
    assert local(midnight.start, LONDON).time() == time(0, 0)


@pytest.mark.parametrize("on", [SPRING_FORWARD, FALL_BACK, date(2026, 2, 10)])
def test_a_span_crossing_midnight_belongs_to_the_date_it_starts_on(on: date) -> None:
    night = sleep().occurrence_on(on, LONDON)

    assert local(night.start, LONDON).date() == on
    assert local(night.end, LONDON).date() == on + timedelta(days=1)


def test_a_date_the_zone_skips_carries_its_occurrence_to_the_next_date() -> None:
    # Samoa crossed the date line and 2011-12-30 has no instants at all. The whole local
    # date is inside the gap, so shifting forward past it lands on 2011-12-31 at the same
    # wall time. No date this product plans is one of these; the input is real, so the
    # behavior is stated rather than left to be discovered.
    wake = RoutineSpan(time(5, 0), 30, 30, 0)

    skipped = wake.occurrence_on(date(2011, 12, 30), APIA)

    assert local(skipped.start, APIA) == datetime(2011, 12, 31, 5, 0, tzinfo=resolve_zone(APIA))
    assert skipped.total_minutes() == 30
