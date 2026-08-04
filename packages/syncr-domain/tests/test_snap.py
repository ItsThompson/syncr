"""The fifteen-minute snap, its two exemptions, and the two readings a declaration needs."""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.intervals import Instant, Interval
from syncr_domain.snap import (
    SNAP,
    SNAP_MINUTES,
    is_a_snap_multiple,
    is_on_snap_grid,
    is_wall_time_on_snap_grid,
    snap_to_grid,
)
from tests.instants import MONDAY, at

# Every producer that owes the grid a quarter hour, with an off-grid instant each
# would have to place. The solver's own H14 check reads the same predicate.
SNAPPING_PRODUCERS: list[tuple[str, Instant]] = [
    ("solver output", at(9, 7)),
    ("drag", at(13, 22)),
    ("keyboard move", at(13, 8)),
    ("off-plan bound", at(17, 53)),
]

# An imported anchor at 16:07 and the 30-minute transit computed from it. Both keep
# their real times, so both sit off the grid and neither is an error.
ANCHOR = Interval(at(16, 7), at(17, 7))
TRANSIT_BEFORE_ANCHOR = Interval(at(15, 37), at(16, 7))


def test_the_snap_is_fifteen_minutes() -> None:
    assert SNAP_MINUTES == 15
    assert SNAP.total_seconds() == SNAP_MINUTES * 60


@pytest.mark.parametrize(("producer", "chosen"), SNAPPING_PRODUCERS)
def test_a_snapping_producer_lands_on_a_quarter_hour(producer: str, chosen: Instant) -> None:
    assert not is_on_snap_grid(chosen)

    placed = snap_to_grid(chosen)

    assert is_on_snap_grid(placed), f"{producer} placed {placed}, which is off the snap grid"
    assert abs(placed - chosen) <= SNAP / 2


def test_both_bounds_of_a_snapped_interval_land_on_a_quarter_hour() -> None:
    dragged = Interval(snap_to_grid(at(9, 7)), snap_to_grid(at(10, 53)))

    assert is_on_snap_grid(dragged.start)
    assert is_on_snap_grid(dragged.end)
    assert dragged == Interval(at(9), at(11))


@pytest.mark.parametrize(
    ("exempt", "real_time"),
    [("an anchor", ANCHOR), ("an anchor-derived transit", TRANSIT_BEFORE_ANCHOR)],
)
def test_an_exempt_interval_keeps_its_real_time(exempt: str, real_time: Interval) -> None:
    assert not is_on_snap_grid(real_time.start), exempt
    assert not is_on_snap_grid(real_time.end), exempt


def test_a_transit_computed_from_an_anchor_inherits_the_anchor_minute() -> None:
    lead = timedelta(minutes=30)

    assert Interval(ANCHOR.start - lead, ANCHOR.start) == TRANSIT_BEFORE_ANCHOR
    assert not is_on_snap_grid(TRANSIT_BEFORE_ANCHOR.start)


def test_the_algebra_never_snaps_on_its_own() -> None:
    assert Interval(at(16, 7), at(17, 7)).start == at(16, 7)


@pytest.mark.parametrize("minute", [0, 15, 30, 45])
def test_a_quarter_hour_is_on_the_grid_and_snaps_to_itself(minute: int) -> None:
    on_grid = at(9, minute)

    assert is_on_snap_grid(on_grid)
    assert snap_to_grid(on_grid) == on_grid


@pytest.mark.parametrize(
    ("second", "microsecond"),
    [(1, 0), (0, 1)],
)
def test_a_sub_minute_instant_is_off_the_grid(second: int, microsecond: int) -> None:
    assert not is_on_snap_grid(at(9).replace(second=second, microsecond=microsecond))


def test_an_exact_half_step_rounds_up() -> None:
    assert snap_to_grid(at(9, 7) + timedelta(seconds=30)) == at(9, 15)


@given(st.integers(min_value=0, max_value=7 * 24 * 60 * 60))
def test_snapping_always_reaches_the_grid_and_is_idempotent(offset_seconds: int) -> None:
    moment = MONDAY + timedelta(seconds=offset_seconds)

    placed = snap_to_grid(moment)

    assert is_on_snap_grid(placed)
    assert snap_to_grid(placed) == placed
    assert abs(placed - moment) <= SNAP / 2


# --------------------------------------------------------------------------------
# A declaration carries a wall time and a duration in minutes, and no instant at all,
# so neither can be read by the instant predicate above.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("minute", [0, 15, 30, 45])
def test_a_declared_wall_time_on_a_quarter_hour_is_on_the_grid(minute: int) -> None:
    assert is_wall_time_on_snap_grid(time(5, minute))


@pytest.mark.parametrize(
    "at_time",
    [time(5, 5), time(5, 50), time(5, 0, 1), time(5, 0, 0, 1)],
    ids=["five past", "ten to", "a second past", "a microsecond past"],
)
def test_a_declared_wall_time_off_the_quarter_hour_is_not(at_time: time) -> None:
    assert not is_wall_time_on_snap_grid(at_time)


@pytest.mark.parametrize("minutes", [0, 15, 45, 1440])
def test_a_duration_that_is_a_multiple_of_the_step_keeps_an_end_on_the_grid(
    minutes: int,
) -> None:
    assert is_a_snap_multiple(minutes)
    assert is_on_snap_grid(at(5) + timedelta(minutes=minutes))


@pytest.mark.parametrize("minutes", [1, 20, 50])
def test_a_duration_that_is_not_would_move_an_end_off_it(minutes: int) -> None:
    # The half that matters: a start on the grid plus one of these ends between two quarter
    # hours, which is the block a materialized entry would produce.
    assert not is_a_snap_multiple(minutes)
    assert not is_on_snap_grid(at(5) + timedelta(minutes=minutes))
