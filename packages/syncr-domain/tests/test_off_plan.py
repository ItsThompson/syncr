"""Off-plan periods: the grid rule, the non-overlap rule, and the boundaries of both.

Off-plan periods are intervals, so the boundaries ARE the subject matter. Two spans that
abut exactly, one nested inside another, one starting a quarter hour before the other ends,
a pair given in either order: each is asserted here rather than reasoned about, and the
half-open reading is asserted at both ends rather than at one.

``require_disjoint`` is also crossed against a brute-force comparison of every pair over
generated periods, because its adjacent-pairs-only walk is the one thing in the module that
could be right by luck: a wrong sort key or a missed pair would still pass every example
below while failing on the fourth period of a real tenant's year.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import combinations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.intervals import Interval, IntervalError
from syncr_domain.off_plan import (
    OffPlanError,
    OffPlanPeriod,
    OverlappingOffPlanError,
    require_disjoint,
)
from syncr_domain.snap import SNAP, is_on_snap_grid
from tests.instants import MONDAY, at, between

WEEK_MINUTES = 7 * 24 * 60
SNAPS_PER_WEEK = WEEK_MINUTES // 15


def period(interval: Interval, *, keep_frame: bool = False) -> OffPlanPeriod:
    return OffPlanPeriod(interval=interval, keep_frame=keep_frame)


@st.composite
def off_plan_periods(draw: st.DrawFn) -> OffPlanPeriod:
    """A period on the quarter-hour grid, somewhere inside one ordinary week."""
    start = draw(st.integers(min_value=0, max_value=SNAPS_PER_WEEK))
    length = draw(st.integers(min_value=1, max_value=96))
    return OffPlanPeriod(interval=Interval(MONDAY + start * SNAP, MONDAY + (start + length) * SNAP))


# --------------------------------------------------------------------------------
# OP1: the bounds run forward and land on the quarter hour
# --------------------------------------------------------------------------------


def test_a_span_on_the_grid_is_a_period() -> None:
    declared = OffPlanPeriod(interval=between(14, 17.25), keep_frame=True, label="Italy")

    assert declared.interval.total_minutes() == 195
    assert declared.keep_frame is True
    assert declared.label == "Italy"


def test_a_period_keeps_the_frame_only_when_asked_to() -> None:
    # False is the default because the common declaration is a holiday, where nothing at all
    # materializes. Keeping the frame is the quiet-week-at-home case and is said explicitly.
    assert OffPlanPeriod(interval=between(9, 10)).keep_frame is False
    assert OffPlanPeriod(interval=between(9, 10)).label is None


@pytest.mark.parametrize(
    "span",
    [
        Interval(at(14, 5), at(17, 0)),
        Interval(at(14, 0), at(17, 5)),
        Interval(at(14, 7), at(17, 8)),
    ],
    ids=["start_off_the_grid", "end_off_the_grid", "both_off_the_grid"],
)
def test_a_bound_off_the_grid_is_refused(span: Interval) -> None:
    with pytest.raises(OffPlanError, match="15-minute grid"):
        OffPlanPeriod(interval=span)


def test_the_rejection_names_every_bound_that_is_off_the_grid() -> None:
    with pytest.raises(OffPlanError) as refused:
        OffPlanPeriod(interval=Interval(at(14, 7), at(17, 8)))

    assert str(at(14, 7)) in str(refused.value)
    assert str(at(17, 8)) in str(refused.value)


def test_a_bound_carrying_seconds_is_off_the_grid() -> None:
    # 14:00:30 reads as 14:00 in every rendering the product has, so a check on the minute
    # alone would accept it and the stored instant would differ from the one displayed.
    with pytest.raises(OffPlanError):
        OffPlanPeriod(interval=Interval(at(14) + timedelta(seconds=30), at(17)))


@pytest.mark.parametrize("minutes", [0, 15, 30, 45])
def test_every_quarter_hour_is_on_the_grid(minutes: int) -> None:
    declared = OffPlanPeriod(interval=Interval(at(9, minutes), at(23, minutes)))

    assert is_on_snap_grid(declared.interval.start)
    assert is_on_snap_grid(declared.interval.end)


def test_a_span_that_runs_backwards_is_refused_by_the_interval_itself() -> None:
    # Stated here rather than restated in this module: `Interval` owns `start < end`, so a
    # period cannot exist with reversed bounds whatever it does with them afterwards.
    with pytest.raises(IntervalError, match="needs start < end"):
        OffPlanPeriod(interval=Interval(at(17), at(14)))


def test_a_zero_length_span_is_refused_by_the_interval_itself() -> None:
    # "Off from 09:00 to 09:00" covers no instant. Half-open bounds make it unconstructible
    # rather than a period every query has to skip.
    with pytest.raises(IntervalError, match="needs start < end"):
        OffPlanPeriod(interval=Interval(at(9), at(9)))


# --------------------------------------------------------------------------------
# OP2: two periods never cover a common instant
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "overlapping"),
    [
        (between(9, 10), between(10, 11), False),
        (between(10, 11), between(9, 10), False),
        (between(9, 10), between(9.75, 11), True),
        (between(9, 12), between(10, 11), True),
        (between(10, 11), between(9, 12), True),
        (between(9, 10), between(9, 10), True),
        (between(9, 10), between(11, 12), False),
        (between(9, 10), between(9, 9.25), True),
    ],
    ids=[
        "abutting_forwards",
        "abutting_backwards",
        "one_quarter_hour_of_overlap",
        "nested",
        "containing",
        "identical",
        "disjoint",
        "sharing_a_start",
    ],
)
def test_overlap_reads_the_bounds_as_half_open(
    first: Interval, second: Interval, overlapping: bool
) -> None:
    assert period(first).overlaps(period(second)) is overlapping
    # Symmetric, so the answer cannot depend on which period was declared first.
    assert period(second).overlaps(period(first)) is overlapping


@pytest.mark.parametrize(
    "periods",
    [
        [],
        [period(between(9, 10))],
        [period(between(9, 10)), period(between(10, 11))],
        [period(between(9, 10)), period(between(10, 11)), period(between(11, 12))],
        [period(between(9, 10)), period(between(11, 12))],
    ],
    ids=["none", "one", "abutting_pair", "abutting_chain", "gap"],
)
def test_periods_that_share_no_instant_are_accepted(periods: list[OffPlanPeriod]) -> None:
    require_disjoint(periods)


@pytest.mark.parametrize(
    "periods",
    [
        [period(between(9, 10)), period(between(9.75, 11))],
        [period(between(9.75, 11)), period(between(9, 10))],
        [period(between(9, 12)), period(between(10, 11))],
        [period(between(9, 10)), period(between(9, 10))],
        [period(between(9, 10)), period(between(20, 21)), period(between(9.75, 11))],
    ],
    ids=["overlap", "overlap_reversed", "nested", "identical", "third_wheel"],
)
def test_periods_sharing_an_instant_are_refused(periods: list[OffPlanPeriod]) -> None:
    with pytest.raises(OverlappingOffPlanError, match="cover a common instant"):
        require_disjoint(periods)


def test_the_rejection_names_both_offending_spans() -> None:
    with pytest.raises(OverlappingOffPlanError) as refused:
        require_disjoint([period(between(9, 12)), period(between(10, 11))])

    stated = str(refused.value)
    assert str(at(9)) in stated
    assert str(at(12)) in stated
    assert str(at(10)) in stated
    assert str(at(11)) in stated


def test_a_long_period_holding_several_short_ones_is_refused() -> None:
    # A containing period against three periods inside it. The walk compares adjacent pairs of the
    # SORTED sequence, so what this exercises is the sort: the container sorts first and is compared
    # against the earliest period inside it. A walk over declaration order, or one that compared
    # only literally neighbouring declarations, would answer differently on a shuffled input.
    holiday = period(Interval(at(0, day=0), at(0, day=5)))
    inside = [period(between(9, 10, day=day)) for day in (1, 2, 3)]

    with pytest.raises(OverlappingOffPlanError):
        require_disjoint([holiday, *inside])


def test_an_overlapping_pair_is_not_always_adjacent_and_is_still_refused() -> None:
    # The tempting justification for the adjacent-pairs walk is that an overlapping pair is always
    # adjacent once sorted. It is false, and this is the counterexample: sorted by start, the third
    # period overlaps the FIRST and not the second. The walk is complete for a different reason,
    # stated on `require_disjoint`, and the reason matters because a maintainer trusting the false
    # one could "optimize" the walk into something that misses this.
    containing = period(Interval(at(0), at(0, day=4)))
    early = period(between(1, 2))
    late = period(between(2, 3, day=2))

    assert late.overlaps(containing) is True
    assert late.overlaps(early) is False
    with pytest.raises(OverlappingOffPlanError):
        require_disjoint([containing, early, late])


@given(st.lists(off_plan_periods(), max_size=6))
def test_the_walk_agrees_with_comparing_every_pair(periods: list[OffPlanPeriod]) -> None:
    # The cross-check. `require_disjoint` walks adjacent pairs of the sorted sequence; this
    # compares all of them, which is the definition the walk is an optimization of.
    any_pair_overlaps = any(one.overlaps(other) for one, other in combinations(periods, 2))

    if any_pair_overlaps:
        with pytest.raises(OverlappingOffPlanError):
            require_disjoint(periods)
    else:
        require_disjoint(periods)


@given(st.lists(off_plan_periods(), max_size=6))
def test_the_answer_does_not_depend_on_the_order_the_periods_arrive_in(
    periods: list[OffPlanPeriod],
) -> None:
    def refused(ordered: list[OffPlanPeriod]) -> bool:
        try:
            require_disjoint(ordered)
        except OverlappingOffPlanError:
            return True
        return False

    assert refused(periods) == refused(list(reversed(periods)))
