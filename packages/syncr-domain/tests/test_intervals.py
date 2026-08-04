"""The interval algebra by example. Its universal properties live in
``test_interval_properties.py``."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest

from syncr_domain.intervals import Interval, IntervalError, IntervalSet, as_instant
from syncr_domain.zones import to_instant
from tests.instants import at, between

LONDON = "Europe/London"


class TestAsInstant:
    def test_an_aware_datetime_reads_in_utc(self) -> None:
        tokyo_noon = datetime(2026, 3, 2, 12, 0, tzinfo=timezone(timedelta(hours=9)))

        assert as_instant(tokyo_noon) == datetime(2026, 3, 2, 3, 0, tzinfo=UTC)
        assert as_instant(tokyo_noon).tzinfo is UTC

    def test_a_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(IntervalError, match="carries no time zone"):
            as_instant(datetime(2026, 3, 2, 12, 0))  # noqa: DTZ001 - the rejection is the point


class TestInterval:
    def test_start_must_precede_end(self) -> None:
        with pytest.raises(IntervalError, match="start < end"):
            Interval(at(9), at(9))

        with pytest.raises(IntervalError, match="start < end"):
            Interval(at(10), at(9))

    def test_it_is_frozen(self) -> None:
        interval = between(9, 10)

        with pytest.raises(dataclasses.FrozenInstanceError):
            interval.start = at(8)  # type: ignore[misc]

    def test_it_orders_by_start_then_end(self) -> None:
        first, longer, later = between(9, 10), between(9, 11), between(10, 11)

        assert sorted([later, longer, first]) == [first, longer, later]

    def test_bounds_written_in_another_zone_equal_the_same_utc_interval(self) -> None:
        east = timezone(timedelta(hours=2))
        written_east = Interval(at(9).astimezone(east), at(10).astimezone(east))

        assert written_east == between(9, 10)
        assert hash(written_east) == hash(between(9, 10))

    def test_total_minutes_is_elapsed_minutes(self) -> None:
        assert between(9, 10).total_minutes() == 60
        assert Interval(at(9), at(9, 15)).total_minutes() == 15

    def test_a_sub_minute_remainder_truncates(self) -> None:
        ninety_seconds = Interval(at(9), at(9) + timedelta(seconds=90))

        assert ninety_seconds.total_minutes() == 1

    def test_adjacency_is_not_overlap(self) -> None:
        assert not between(9, 10).overlaps(between(10, 11))
        assert not between(10, 11).overlaps(between(9, 10))

    def test_a_shared_minute_is_overlap(self) -> None:
        assert between(9, 10).overlaps(Interval(at(9, 59), at(11)))
        assert between(9, 12).overlaps(between(10, 11))
        assert between(9, 10).overlaps(between(9, 10))

    def test_a_disjoint_interval_does_not_overlap(self) -> None:
        assert not between(9, 10).overlaps(between(14, 15))


class TestNormalization:
    def test_an_empty_set_has_no_members_and_no_minutes(self) -> None:
        empty = IntervalSet()

        assert len(empty) == 0
        assert not empty
        assert empty.total_minutes() == 0
        assert empty.members == ()

    def test_members_are_sorted(self) -> None:
        unsorted = IntervalSet([between(14, 15), between(9, 10), between(11, 12)])

        assert unsorted.members == (between(9, 10), between(11, 12), between(14, 15))

    def test_overlapping_members_merge(self) -> None:
        overlapping = IntervalSet([between(9, 11), between(10, 12)])

        assert overlapping.members == (between(9, 12),)

    def test_adjacent_members_merge(self) -> None:
        adjacent = IntervalSet([between(9, 10), between(10, 11)])

        assert adjacent.members == (between(9, 11),)
        assert adjacent.total_minutes() == 120

    def test_a_contained_member_is_absorbed(self) -> None:
        containing = IntervalSet([between(9, 17), between(10, 11), between(12, 13)])

        assert containing.members == (between(9, 17),)

    def test_input_order_does_not_change_the_set(self) -> None:
        members = [between(12, 13), between(9, 10), between(9, 11)]

        assert IntervalSet(members) == IntervalSet(reversed(members))

    def test_equal_sets_are_interchangeable_as_dict_keys(self) -> None:
        assert (
            len({IntervalSet([between(9, 11)]), IntervalSet([between(9, 10), between(10, 11)])})
            == 1
        )


class TestUnion:
    def test_it_is_idempotent(self) -> None:
        occupied = IntervalSet([between(9, 10), between(14, 15)])

        assert occupied.union(occupied) == occupied
        assert occupied.union(occupied).total_minutes() == 120

    def test_a_span_inside_another_is_counted_once(self) -> None:
        off_plan = IntervalSet([between(0, 72)])
        frame = IntervalSet([between(23, 31)])

        assert off_plan.union(frame).total_minutes() == off_plan.total_minutes()

    def test_it_merges_across_the_two_sets(self) -> None:
        assert IntervalSet([between(9, 11)]).union(IntervalSet([between(10, 12)])) == IntervalSet(
            [between(9, 12)]
        )


class TestSubtract:
    def test_subtracting_a_non_intersecting_set_returns_an_equal_set(self) -> None:
        occupied = IntervalSet([between(9, 10), between(14, 15)])

        assert occupied.subtract(IntervalSet([between(20, 21)])) == occupied

    def test_subtracting_an_adjacent_set_returns_an_equal_set(self) -> None:
        occupied = IntervalSet([between(9, 10)])

        assert occupied.subtract(IntervalSet([between(10, 11)])) == occupied

    def test_a_cut_through_the_middle_splits_a_member(self) -> None:
        assert IntervalSet([between(9, 12)]).subtract(
            IntervalSet([between(10, 11)])
        ) == IntervalSet([between(9, 10), between(11, 12)])

    def test_a_covering_set_leaves_nothing(self) -> None:
        assert not IntervalSet([between(9, 12)]).subtract(IntervalSet([between(8, 13)]))

    def test_subtracting_from_an_empty_set_stays_empty(self) -> None:
        assert not IntervalSet().subtract(IntervalSet([between(9, 10)]))


class TestIntersect:
    def test_it_keeps_only_the_shared_minutes(self) -> None:
        assert IntervalSet([between(9, 12)]).intersect(
            IntervalSet([between(10, 11), between(11, 13)])
        ) == IntervalSet([between(10, 12)])

    def test_disjoint_sets_share_nothing(self) -> None:
        assert not IntervalSet([between(9, 10)]).intersect(IntervalSet([between(14, 15)]))

    def test_adjacent_sets_share_nothing(self) -> None:
        assert not IntervalSet([between(9, 10)]).intersect(IntervalSet([between(10, 11)]))


# The eight ways one interval can sit against another, named as the reader of a failure sees
# them. Both abutting cases are here because the convention is half-open, and the two containment
# cases are here because a clip has to answer them in opposite directions.
OVERLAP_CASES = (
    ("wholly before", between(5, 7)),
    ("ends where the bound starts", between(7, 9)),
    ("straddles the start", between(8, 10)),
    ("contained", between(10, 11)),
    ("equal to the bound", between(9, 17)),
    ("covers the bound", between(6, 20)),
    ("straddles the end", between(16, 20)),
    ("starts where the bound ends", between(17, 19)),
)
BOUND = between(9, 17)


class TestClippingOneInterval:
    @pytest.mark.parametrize(
        ("label", "interval"), OVERLAP_CASES, ids=[case[0] for case in OVERLAP_CASES]
    )
    def test_the_clip_and_the_sets_clip_answer_the_same(
        self, label: str, interval: Interval
    ) -> None:
        # Two implementations of one convention: this one compares two pairs of bounds, and the
        # set's walks many members. Crossed over every way two intervals can sit against each
        # other, so neither can drift into a different reading of an abutting bound.
        clipped = interval.clipped_to(BOUND)
        expected = IntervalSet([interval]).clip(BOUND)

        assert IntervalSet([clipped] if clipped is not None else []) == expected, label

    @pytest.mark.parametrize(
        ("label", "interval"), OVERLAP_CASES, ids=[case[0] for case in OVERLAP_CASES]
    )
    def test_a_clip_holds_no_minute_outside_the_bound(self, label: str, interval: Interval) -> None:
        clipped = interval.clipped_to(BOUND)

        if clipped is not None:
            assert BOUND.start <= clipped.start < clipped.end <= BOUND.end, label

    def test_an_abutting_interval_clips_to_nothing_rather_than_to_an_empty_span(self) -> None:
        # Half-open bounds, so neither abutting case shares a minute with the bound. There is no
        # empty interval to return, because the algebra refuses one by construction.
        assert between(7, 9).clipped_to(BOUND) is None
        assert between(17, 19).clipped_to(BOUND) is None

    def test_an_interval_inside_the_bound_is_returned_whole(self) -> None:
        assert between(10, 11).clipped_to(BOUND) == between(10, 11)

    def test_an_interval_covering_the_bound_clips_to_the_bound(self) -> None:
        assert between(6, 20).clipped_to(BOUND) == BOUND


class TestClip:
    def test_it_trims_the_members_crossing_the_bound(self) -> None:
        occupied = IntervalSet([between(8, 10), between(11, 12), between(16, 20)])

        assert occupied.clip(between(9, 17)) == IntervalSet(
            [between(9, 10), between(11, 12), between(16, 17)]
        )

    def test_a_set_outside_the_bound_clips_to_nothing(self) -> None:
        assert not IntervalSet([between(20, 21)]).clip(between(9, 17))


class TestGaps:
    def test_an_empty_set_leaves_the_whole_bound_open(self) -> None:
        assert IntervalSet().gaps(between(9, 17)) == IntervalSet([between(9, 17)])

    def test_it_returns_the_uncovered_parts(self) -> None:
        occupied = IntervalSet([between(9, 10), between(12, 13)])

        assert occupied.gaps(between(9, 17)) == IntervalSet([between(10, 12), between(13, 17)])

    def test_a_covered_bound_has_no_gaps(self) -> None:
        assert not IntervalSet([between(8, 18)]).gaps(between(9, 17))

    def test_min_minutes_drops_the_gaps_too_short_to_use(self) -> None:
        occupied = IntervalSet([between(9, 10), between(10.5, 13), between(14, 17)])

        assert occupied.gaps(between(9, 17), min_minutes=30) == IntervalSet(
            [between(10, 10.5), between(13, 14)]
        )
        assert occupied.gaps(between(9, 17), min_minutes=31) == IntervalSet([between(13, 14)])
        assert not occupied.gaps(between(9, 17), min_minutes=61)


class TestOverlaps:
    def test_a_probe_sharing_a_minute_overlaps(self) -> None:
        occupied = IntervalSet([between(9, 10), between(14, 15)])

        assert occupied.overlaps(Interval(at(9, 30), at(9, 45)))
        assert occupied.overlaps(between(8, 20))

    def test_an_adjacent_probe_does_not_overlap(self) -> None:
        occupied = IntervalSet([between(9, 10)])

        assert not occupied.overlaps(between(10, 11))
        assert not occupied.overlaps(between(8, 9))

    def test_an_empty_set_overlaps_nothing(self) -> None:
        assert not IntervalSet().overlaps(between(9, 10))


class TestMinutesAcrossADstTransition:
    """`total_minutes` reads instants, so a transition inside a set is exact.

    Asserted against Europe/London and the real 2026 transition dates. The ordinary
    week's 24-hour day is the control: without it, a 23-hour answer could come from
    arithmetic that is wrong everywhere rather than from the transition.
    """

    def local_day(self, on: date) -> IntervalSet:
        midnight = time(0, 0)
        return IntervalSet(
            [
                Interval(
                    to_instant(midnight, on, LONDON),
                    to_instant(midnight, on + timedelta(days=1), LONDON),
                )
            ]
        )

    def test_an_ordinary_day_is_24_hours(self) -> None:
        assert self.local_day(date(2026, 3, 1)).total_minutes() == 24 * 60

    def test_the_spring_forward_day_is_23_hours(self) -> None:
        assert self.local_day(date(2026, 3, 29)).total_minutes() == 23 * 60

    def test_the_fall_back_day_is_25_hours(self) -> None:
        assert self.local_day(date(2026, 10, 25)).total_minutes() == 25 * 60

    def test_a_union_spanning_the_transition_counts_the_real_elapsed_minutes(self) -> None:
        saturday = self.local_day(date(2026, 3, 28))
        sunday = self.local_day(date(2026, 3, 29))

        assert saturday.union(sunday).total_minutes() == (24 + 23) * 60
