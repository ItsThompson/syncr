"""The universal properties of the interval algebra, over generated sets.

Three of these catch the failures that are otherwise quiet: union idempotence, which
is what keeps the budget denominator from double-counting; half-open adjacency, which
is what keeps a block abutting another from reading as a conflict; and subtraction
totality, which is what keeps a non-intersecting subtrahend from raising instead of
returning the set unchanged.

Generated instants are whole minutes inside one ordinary week, so `total_minutes` is
exact here and an arithmetic identity can be asserted as equality rather than as a
tolerance. The strategies that produce them are in `tests/interval_strategies.py`, because
the budget denominator's suite generates the same shapes.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.intervals import Interval, IntervalSet
from tests.interval_strategies import MAX_SET_SIZE, interval_sets, intervals


@st.composite
def a_set_and_a_permutation(draw: st.DrawFn) -> tuple[list[Interval], list[Interval]]:
    members = draw(st.lists(intervals(), max_size=MAX_SET_SIZE))
    return members, draw(st.permutations(members))


def _shifted_clear_of(subject: IntervalSet, other: IntervalSet) -> IntervalSet:
    """``other`` moved wholly after ``subject``, so the two cannot intersect."""
    if not subject or not other:
        return other
    offset = subject.members[-1].end - other.members[0].start + timedelta(minutes=1)
    return IntervalSet(Interval(m.start + offset, m.end + offset) for m in other)


@given(interval_sets())
def test_members_are_disjoint_sorted_and_merged(occupied: IntervalSet) -> None:
    for earlier, later in pairwise(occupied.members):
        assert earlier.end < later.start


@given(interval_sets())
def test_normalization_is_canonical(occupied: IntervalSet) -> None:
    assert IntervalSet(occupied.members) == occupied


@given(a_set_and_a_permutation())
def test_input_order_does_not_change_the_set(
    ordering: tuple[list[Interval], list[Interval]],
) -> None:
    members, shuffled = ordering

    assert IntervalSet(shuffled) == IntervalSet(members)


@given(interval_sets())
def test_union_is_idempotent(occupied: IntervalSet) -> None:
    assert occupied.union(occupied) == occupied
    assert occupied.union(occupied).total_minutes() == occupied.total_minutes()


@given(interval_sets(), interval_sets())
def test_union_is_commutative(left: IntervalSet, right: IntervalSet) -> None:
    assert left.union(right) == right.union(left)


@given(interval_sets(), interval_sets())
def test_union_never_over_counts(left: IntervalSet, right: IntervalSet) -> None:
    unioned = left.union(right).total_minutes()

    assert unioned <= left.total_minutes() + right.total_minutes()
    assert unioned >= max(left.total_minutes(), right.total_minutes())


@given(intervals())
def test_adjacency_is_not_overlap(interval: Interval) -> None:
    following = Interval(interval.end, interval.end + interval.duration)

    assert not interval.overlaps(following)
    assert not following.overlaps(interval)
    assert IntervalSet([interval, following]).total_minutes() == 2 * interval.total_minutes()


@given(interval_sets(), interval_sets())
def test_subtracting_a_non_intersecting_set_returns_an_equal_set(
    occupied: IntervalSet, other: IntervalSet
) -> None:
    clear = _shifted_clear_of(occupied, other)

    assert not occupied.intersect(clear)
    assert occupied.subtract(clear) == occupied


@given(interval_sets(), interval_sets())
def test_subtraction_removes_exactly_the_intersection(
    occupied: IntervalSet, other: IntervalSet
) -> None:
    remainder = occupied.subtract(other)

    assert not remainder.intersect(other)
    assert remainder.union(occupied.intersect(other)) == occupied
    assert (
        remainder.total_minutes()
        == occupied.total_minutes() - occupied.intersect(other).total_minutes()
    )


@given(interval_sets(), interval_sets())
def test_intersection_is_commutative_and_idempotent(left: IntervalSet, right: IntervalSet) -> None:
    assert left.intersect(right) == right.intersect(left)
    assert left.intersect(left) == left


@given(interval_sets(), intervals())
def test_clipping_keeps_only_what_the_bound_holds(occupied: IntervalSet, bound: Interval) -> None:
    clipped = occupied.clip(bound)

    assert all(bound.start <= member.start and member.end <= bound.end for member in clipped)
    assert clipped.clip(bound) == clipped
    assert clipped.total_minutes() <= min(occupied.total_minutes(), bound.total_minutes())


@given(interval_sets(), intervals())
def test_gaps_and_occupancy_tile_the_bound(occupied: IntervalSet, bound: Interval) -> None:
    gaps = occupied.gaps(bound)

    assert not gaps.intersect(occupied)
    assert occupied.clip(bound).union(gaps) == IntervalSet([bound])


@given(interval_sets(), intervals(), st.integers(min_value=0, max_value=600))
def test_gaps_never_returns_one_shorter_than_asked(
    occupied: IntervalSet, bound: Interval, min_minutes: int
) -> None:
    assert all(gap.total_minutes() >= min_minutes for gap in occupied.gaps(bound, min_minutes))


@given(interval_sets(), intervals())
def test_overlaps_agrees_with_the_intersection(occupied: IntervalSet, probe: Interval) -> None:
    assert occupied.overlaps(probe) == bool(occupied.intersect(IntervalSet([probe])))
