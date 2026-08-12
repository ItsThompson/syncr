"""The ``partial_progress`` fixture, re-derived from the wall times and the netting rule it states.

The fixture holds literals so that a probe property asserted against it is making a real claim.
That only works if the literals are right, so this suite is what earns them: every instant is
re-derived from ``to_instant`` in the zone the week runs in, and the netted demand is re-derived
from the three placements the fixture's own table describes.

The rule the figure comes from is the assembler's, and it is stated once there. It is applied here
against this one task so the fixture's stated 60 minutes is a consequence of something rather than
a number somebody typed.
"""

from __future__ import annotations

from datetime import date, time

from syncr_domain.feasibility import probe
from syncr_domain.fixtures import partial_progress
from syncr_domain.intervals import Instant, Interval, IntervalSet
from syncr_domain.outcomes import MISS_STATE, attributed_span
from syncr_domain.weeks import week_span
from syncr_domain.zones import ZoneProfile, to_instant

LONDON = "Europe/London"
PROFILE = ZoneProfile(LONDON)


def instant(on: date, at: time) -> Instant:
    return to_instant(at, on, LONDON)


def test_the_span_is_the_week_the_fixture_names() -> None:
    assert week_span(partial_progress.WEEK, PROFILE) == partial_progress.SPAN


def test_every_instant_is_the_wall_time_the_docstring_states() -> None:
    assert instant(date(2026, 2, 11), time(9, 0)) == partial_progress.NOW
    assert instant(date(2026, 2, 13), time(9, 0)) == partial_progress.DEADLINE
    assert (
        Interval(instant(date(2026, 2, 12), time(9, 0)), instant(date(2026, 2, 12), time(11, 0)))
        == partial_progress.PINNED_AHEAD
    )
    assert (
        Interval(instant(date(2026, 2, 10), time(14, 0)), instant(date(2026, 2, 10), time(15, 0)))
        == partial_progress.UNCONFIRMED_PAST
    )
    assert (
        Interval(instant(date(2026, 2, 14), time(10, 0)), instant(date(2026, 2, 14), time(11, 0)))
        == partial_progress.AFTER_THE_DEADLINE
    )


def test_each_placement_sits_where_the_table_says_relative_to_now_and_the_deadline() -> None:
    # The three cases the fixture exists for, asserted as the relations rather than as instants:
    # one pinned ahead but before the deadline, one behind `now` with no outcome recorded, and one
    # after the deadline entirely.
    assert partial_progress.PINNED_AHEAD.start > partial_progress.NOW
    assert partial_progress.PINNED_AHEAD.end <= partial_progress.DEADLINE
    assert partial_progress.UNCONFIRMED_PAST.end <= partial_progress.NOW
    assert partial_progress.AFTER_THE_DEADLINE.start >= partial_progress.DEADLINE


def test_the_demand_is_the_estimate_less_what_is_attributed_before_the_deadline() -> None:
    # The assembler's rule, applied to this one task: the greater of recorded minutes and the past
    # minutes placed before the deadline, plus the future minutes placed before it. Nothing
    # recorded, one past hour, two pinned hours, and the Saturday hour satisfying nothing.
    recorded = 0
    past_before_the_deadline = partial_progress.UNCONFIRMED_PAST.total_minutes()
    future_before_the_deadline = partial_progress.PINNED_AHEAD.total_minutes()
    attributed = max(recorded, past_before_the_deadline) + future_before_the_deadline

    assert partial_progress.ESTIMATE_MINUTES - attributed == partial_progress.REMAINING_MINUTES
    assert partial_progress.DEMAND.remaining_minutes == partial_progress.REMAINING_MINUTES


def test_the_committed_time_holds_all_three_placements_and_counts_each_once() -> None:
    assert (
        IntervalSet(
            [
                partial_progress.PINNED_AHEAD,
                partial_progress.UNCONFIRMED_PAST,
                partial_progress.AFTER_THE_DEADLINE,
            ]
        )
        == partial_progress.PLACED
    )
    assert partial_progress.PLACED.total_minutes() == 240


def test_the_career_reservation_is_the_floor_less_what_is_placed_in_it() -> None:
    # Three of the four hours placed are Career work, so 120 of the 300-minute floor are still to
    # find. Stated so a test that asserts a floor gap against this fixture is asserting something.
    assert partial_progress.CAREER_FLOOR_MINUTES - partial_progress.CAREER_RESERVED_MINUTES == 180
    assert partial_progress.RESERVATIONS[0].reserved_minutes == 120


def test_the_week_the_fixture_describes_is_one_the_probe_finds_no_gap_in() -> None:
    # The fixture is a HEALTHY week, deliberately: it is the state a defect in the netting turns
    # into a gap, so a test that measures a gap against it starts from nothing rather than from
    # noise.
    assert probe(partial_progress.PARTIAL_PROGRESS).shortfalls == ()


def test_a_confirmed_skip_on_the_past_hour_raises_the_demand_by_that_hour() -> None:
    # The attribution table's one contested row, re-derived THROUGH the table rather than by hand:
    # the skipped hour attributes nothing, so the whole 240 less the two pinned hours is outstanding
    # again. Worked by hand this would pass even if the table said `skipped` attributes its planned
    # span, which is the reading the table rejects.
    attributed_past = attributed_span(
        partial_progress.UNCONFIRMED_PAST, partial_progress.SKIPPED_PAST
    )
    recorded = 0
    past_before_the_deadline = 0 if attributed_past is None else attributed_past.total_minutes()
    future_before_the_deadline = partial_progress.PINNED_AHEAD.total_minutes()
    attributed = max(recorded, past_before_the_deadline) + future_before_the_deadline

    assert attributed_past is None
    assert (
        partial_progress.ESTIMATE_MINUTES - attributed
        == partial_progress.REMAINING_MINUTES_AFTER_A_SKIP
    )
    assert partial_progress.AFTER_A_SKIP.deadline_demands[0].remaining_minutes == (
        partial_progress.REMAINING_MINUTES_AFTER_A_SKIP
    )


def test_the_healthy_weeks_demand_is_re_derived_through_the_same_table() -> None:
    # The other side of the pair, so the two figures come from one mechanism: with no row at all the
    # past hour attributes its planned span, because an absent row is the ordinary case rather than
    # a gap, and that is what keeps the minutes from vanishing from both sides of the arithmetic.
    attributed_past = attributed_span(partial_progress.UNCONFIRMED_PAST, None)

    assert attributed_past == partial_progress.UNCONFIRMED_PAST
    assert (
        partial_progress.ESTIMATE_MINUTES
        - (attributed_past.total_minutes() + partial_progress.PINNED_AHEAD.total_minutes())
        == partial_progress.REMAINING_MINUTES
    )


def test_the_skip_is_recorded_against_the_task_the_placements_are_for() -> None:
    # The row exists so a consumer can drive the netting with it, so it has to name the same content
    # the demand is about: an outcome on another binding would change no figure at all.
    assert partial_progress.SKIPPED_PAST.binding.entity_id == partial_progress.TASK
    assert partial_progress.SKIPPED_PAST.state is MISS_STATE


def test_recording_the_skip_returns_no_span_to_capacity() -> None:
    # The column of the table that is uniform by construction. Capacity starts at `now`, so the
    # Tuesday hour was never in it: were it returned, pressing skip would make the week read as more
    # feasible, which is the inversion the split between attribution and capacity exists to prevent.
    assert partial_progress.AFTER_A_SKIP.placed == partial_progress.PARTIAL_PROGRESS.placed


def test_the_week_absorbs_the_denied_hour_without_a_gap_and_without_a_smaller_one() -> None:
    # What the fixture is FOR: a healthy week, so a figure measured against it starts from nothing.
    # The denied hour raises the demand from 60 to 120 and the week still has the Career capacity to
    # hold it before Friday, so no gap appears. What may never happen is a gap FALLING, and the
    # denominator may not move either: capacity is identical because a past span was never in it.
    healthy = probe(partial_progress.PARTIAL_PROGRESS)
    after = probe(partial_progress.AFTER_A_SKIP)

    assert healthy.shortfalls == ()
    assert after.shortfalls == ()
    assert after.discretionary_minutes == healthy.discretionary_minutes
