"""The discretionary-time denominator: the worked union example, and the subtraction table.

The worked example is the one test to read. It carries the reference inputs from the spec's
own worked case, where summing the four subtrahends gives 84h 30m of discretionary time and
unioning them gives 93h 45m from exactly the same spans. Both figures are asserted, because
a test of the right answer alone would still pass on an implementation that had been fixed
by luck: what makes the union load-bearing is that the wrong arithmetic produces a plausible
figure, 9h 15m short, rather than a crash.

The interval algebra is real here and everywhere else. A faked ``IntervalSet`` would let this
suite pass while the arithmetic underneath it was wrong.
"""

from __future__ import annotations

import inspect

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.discretionary import (
    SUBTRAHEND_BY_KIND,
    OccupancyKind,
    Subtrahend,
    discretionary_intervals,
    discretionary_time,
    is_subtracted,
)
from syncr_domain.intervals import Interval, IntervalSet
from tests.instants import at
from tests.interval_strategies import interval_sets, intervals

# Monday 00:00 to the following Monday 00:00, in UTC, so the span is exactly 168 hours and
# the example's arithmetic is readable without a transition to reason about.
WEEK = Interval(at(0), at(0, day=7))
WEEK_MINUTES = 168 * 60

# The spec's worked case. Every span is placed so that three of the four subtrahends
# overlap something else, which is the ordinary shape of a real week rather than a
# contrived one: a frame Sleep span sits inside a long off-plan period, and an anchor's
# recovery window overlaps the anchor that cast it.
#
#   off-plan    Friday 00:00 to Monday 00:00                72h 00m
#   frame       Saturday 23:00 to Sunday 07:00               8h 00m   wholly inside off-plan
#   anchor      Thursday 16:07 to 18:07                      2h 00m   minute-precise, as
#                                                                     an imported fact is
#   recovery    Thursday 16:52 to 18:22                       1h 30m   75m inside the anchor
WORKED_OFF_PLAN = IntervalSet([Interval(at(0, day=4), at(0, day=7))])
WORKED_FRAME = IntervalSet([Interval(at(23, day=5), at(7, day=6))])
WORKED_ANCHORS = IntervalSet([Interval(at(16, 7, day=3), at(18, 7, day=3))])
WORKED_ABSOLUTE_FORBIDDEN = IntervalSet([Interval(at(16, 52, day=3), at(18, 22, day=3))])

SUMMED_DISCRETIONARY_MINUTES = 84 * 60 + 30
UNIONED_DISCRETIONARY_MINUTES = 93 * 60 + 45


def worked_example() -> int:
    return discretionary_time(
        WEEK,
        WORKED_FRAME,
        WORKED_ANCHORS,
        WORKED_ABSOLUTE_FORBIDDEN,
        WORKED_OFF_PLAN,
    )


def summed_subtraction() -> int:
    """The wrong arithmetic, stated so the right one is measured against something."""
    subtracted = sum(
        subtrahend.total_minutes()
        for subtrahend in (
            WORKED_FRAME,
            WORKED_ANCHORS,
            WORKED_ABSOLUTE_FORBIDDEN,
            WORKED_OFF_PLAN,
        )
    )
    return WEEK_MINUTES - subtracted


def test_the_span_the_worked_example_is_stated_over_is_an_ordinary_week() -> None:
    assert WEEK.total_minutes() == WEEK_MINUTES


def test_summing_the_subtrahends_overstates_the_subtraction() -> None:
    # The control for the test below. Without it, "unioning gives 93h 45m" is a number with
    # nothing to distinguish it from the number a wrong implementation produces.
    assert summed_subtraction() == SUMMED_DISCRETIONARY_MINUTES


def test_unioning_the_subtrahends_gives_the_correct_figure() -> None:
    assert worked_example() == UNIONED_DISCRETIONARY_MINUTES
    assert worked_example() > summed_subtraction()


def test_the_two_figures_differ_by_exactly_the_double_counted_time() -> None:
    # 8h of frame inside the off-plan period, plus 75 minutes of recovery inside the anchor
    # that cast it.
    assert worked_example() - summed_subtraction() == 8 * 60 + 75


def test_the_count_agrees_with_the_set_it_is_derived_from() -> None:
    free = discretionary_intervals(
        WEEK, WORKED_FRAME, WORKED_ANCHORS, WORKED_ABSOLUTE_FORBIDDEN, WORKED_OFF_PLAN
    )

    assert free.total_minutes() == worked_example()
    # Nothing outside the week is in the denominator, whatever the subtrahends reached.
    assert free == free.clip(WEEK)


def test_a_frame_only_week_has_no_discretionary_time() -> None:
    whole_week = IntervalSet([WEEK])

    assert discretionary_time(WEEK, whole_week, IntervalSet(), IntervalSet(), IntervalSet()) == 0


def test_a_week_wholly_off_plan_has_no_discretionary_time() -> None:
    whole_week = IntervalSet([WEEK])

    assert discretionary_time(WEEK, IntervalSet(), IntervalSet(), IntervalSet(), whole_week) == 0


# --------------------------------------------------------------------------------
# The subtraction table
# --------------------------------------------------------------------------------

SUBTRACTED = (
    OccupancyKind.FRAME,
    OccupancyKind.ANCHOR,
    OccupancyKind.RECOVERY_ALL,
    OccupancyKind.UNATTRIBUTED_BUFFER,
    OccupancyKind.OFF_PLAN,
)

NOT_SUBTRACTED = (
    OccupancyKind.RECOVERY_AREAS,
    OccupancyKind.PREP_BLOCK,
    OccupancyKind.TRANSIT_BLOCK,
    OccupancyKind.TASK_BLOCK,
    OccupancyKind.HABIT_BLOCK,
    OccupancyKind.TEMPLATE_ENTRY_BLOCK,
    OccupancyKind.SLOT_BLOCK,
    OccupancyKind.EMPTY_SLOT,
)


@pytest.mark.parametrize("kind", SUBTRACTED, ids=[kind.value for kind in SUBTRACTED])
def test_time_no_area_can_claim_leaves_the_denominator(kind: OccupancyKind) -> None:
    assert is_subtracted(kind) is True
    assert kind in SUBTRAHEND_BY_KIND


@pytest.mark.parametrize("kind", NOT_SUBTRACTED, ids=[kind.value for kind in NOT_SUBTRACTED])
def test_time_an_area_can_claim_stays_in_the_denominator(kind: OccupancyKind) -> None:
    # Prep and transit BLOCKS are the pair the upstream definition subtracted. They carry an
    # Area, so subtracting them would remove the time from the denominator and charge it to
    # an Area at the same time. A materialized concrete template entry carries one for the same
    # reason, which is why it is named here rather than left out of the vocabulary.
    assert is_subtracted(kind) is False
    assert kind not in SUBTRAHEND_BY_KIND


def test_the_table_answers_for_every_kind_of_span_a_week_holds() -> None:
    # The control on the two lists above: a kind added to the vocabulary and left out of
    # both would otherwise be tested by neither.
    assert set(SUBTRACTED) | set(NOT_SUBTRACTED) == set(OccupancyKind)
    assert not set(SUBTRACTED) & set(NOT_SUBTRACTED)


def test_every_subtrahend_the_table_names_is_a_parameter_of_the_denominator() -> None:
    # The mechanical link between the table and the arithmetic. A fifth subtrahend added to
    # the signature, or a sixth kind routed to one that does not exist, fails here rather
    # than being carried by prose.
    parameters = set(inspect.signature(discretionary_intervals).parameters) - {"span"}

    assert {subtrahend.value for subtrahend in Subtrahend} == parameters
    assert set(SUBTRAHEND_BY_KIND.values()) == set(Subtrahend)


# --------------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------------


def occupied_weeks() -> st.SearchStrategy[tuple[IntervalSet, ...]]:
    """Four subtrahend sets, drawn independently so they overlap as real ones do."""
    return st.tuples(interval_sets(), interval_sets(), interval_sets(), interval_sets())


@given(occupied_weeks(), intervals())
def test_adding_a_span_already_covered_changes_nothing(
    occupied: tuple[IntervalSet, ...], span: Interval
) -> None:
    # Union idempotence, stated over the denominator rather than over the algebra: this is
    # what keeps a frame span that sits inside an off-plan period from being subtracted
    # twice.
    frame, anchors, forbidden, off_plan = occupied
    before = discretionary_time(WEEK, frame, anchors, forbidden, off_plan)
    already_covered = frame.union(anchors).union(forbidden).union(off_plan)

    assert (
        discretionary_time(WEEK, frame.union(already_covered), anchors, forbidden, off_plan)
        == before
    )
    assert (
        discretionary_time(WEEK, frame, anchors, forbidden, off_plan.union(already_covered))
        == before
    )
    # And a span drawn at random is idempotent once it is in: adding it a second time to a
    # different subtrahend cannot move the figure again.
    once = discretionary_time(WEEK, frame, anchors, forbidden.union(IntervalSet([span])), off_plan)
    twice = discretionary_time(
        WEEK,
        frame.union(IntervalSet([span])),
        anchors,
        forbidden.union(IntervalSet([span])),
        off_plan,
    )
    assert once == twice


@given(occupied_weeks(), intervals())
def test_rescoping_a_recovery_window_to_all_never_increases_discretionary_time(
    occupied: tuple[IntervalSet, ...], window: Interval
) -> None:
    # A window scoped to named Areas stays in the denominator; the same window scoped to all
    # comes out of it. Widening the scope can only remove time, never add it, which is what
    # makes the two scopes safe to have.
    frame, anchors, forbidden, off_plan = occupied
    scoped_to_areas = discretionary_time(WEEK, frame, anchors, forbidden, off_plan)
    scoped_to_all = discretionary_time(
        WEEK, frame, anchors, forbidden.union(IntervalSet([window])), off_plan
    )

    assert scoped_to_all <= scoped_to_areas


@given(occupied_weeks())
def test_the_denominator_is_never_negative_and_never_exceeds_the_span(
    occupied: tuple[IntervalSet, ...],
) -> None:
    frame, anchors, forbidden, off_plan = occupied

    assert 0 <= discretionary_time(WEEK, frame, anchors, forbidden, off_plan) <= WEEK_MINUTES


@given(occupied_weeks())
def test_the_order_the_subtrahends_are_passed_in_does_not_change_the_figure(
    occupied: tuple[IntervalSet, ...],
) -> None:
    # The union is commutative, so a caller cannot change the denominator by deciding which
    # set to build first.
    frame, anchors, forbidden, off_plan = occupied

    assert discretionary_time(WEEK, frame, anchors, forbidden, off_plan) == discretionary_time(
        WEEK, off_plan, forbidden, anchors, frame
    )


@given(intervals())
def test_a_span_outside_the_week_subtracts_nothing_from_it(span: Interval) -> None:
    # Subtraction is total, so the assembler may hand over a span that reaches past the
    # week's own bounds without the denominator needing a clip of its own.
    outside = IntervalSet([Interval(WEEK.end, WEEK.end + span.duration)])

    assert (
        discretionary_time(WEEK, outside, IntervalSet(), IntervalSet(), IntervalSet())
        == WEEK_MINUTES
    )


def test_the_example_spans_overlap_in_the_way_the_worked_case_describes() -> None:
    # The worked figures only mean something if the spans really do overlap. Asserted rather
    # than assumed, so an edit to one instant cannot quietly turn the example into four
    # disjoint sets that sum and union to the same number.
    assert WORKED_OFF_PLAN.intersect(WORKED_FRAME) == WORKED_FRAME
    assert WORKED_ANCHORS.intersect(WORKED_ABSOLUTE_FORBIDDEN).total_minutes() == 75
    assert not WORKED_OFF_PLAN.intersect(WORKED_ANCHORS)
