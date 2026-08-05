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
