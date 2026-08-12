"""Off-plan time in the denominator: the fourth subtrahend, and the reading that explains it.

Two units meet here. ``OffPlanOccupancy`` turns stored periods into the set the budget
arithmetic subtracts, and ``off_plan_reading`` turns the same spans into the figure and the
sentence the report carries. Both are asserted against the real interval algebra, because a
faked ``IntervalSet`` would let this suite pass while the denominator was wrong.

The claim that matters is the one about summing. A frame occurrence inside an off-plan span must
leave the denominator ONCE, and the wrong figure is stated beside the right one in
``test_a_frame_span_inside_an_off_plan_span_is_subtracted_once``, because summing produces a
plausible-looking number rather than a crash.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syncr_api.offplan.occupancy import OffPlanOccupancy
from syncr_api.offplan.reading import WHOLE_WEEK_STATEMENT, off_plan_reading
from syncr_api.offplan.records import OffPlanPeriodRecord
from syncr_api.offplan.repository import OffPlanPeriodRepository
from syncr_domain.discretionary import discretionary_time
from syncr_domain.fixtures.off_plan_week import OFF_PLAN_WEEK
from syncr_domain.intervals import Interval, IntervalSet
from syncr_domain.weeks import week_span

if TYPE_CHECKING:
    from syncr_domain.identifiers import TenantId

EMPTY = IntervalSet()

WEEK = OFF_PLAN_WEEK.iso_week
WEEK_SPAN = OFF_PLAN_WEEK.week_span
FOLLOWING_SPAN = week_span(OFF_PLAN_WEEK.following_week, OFF_PLAN_WEEK.profile)


class StoredPeriods(OffPlanPeriodRepository):
    """The periods a week holds, with no database behind them."""

    def __init__(self, *intervals: Interval) -> None:
        self._tenant_id: TenantId = uuid4()
        self.rows = [
            OffPlanPeriodRecord(
                id=uuid4(),
                tenant_id=self._tenant_id,
                interval=interval,
                keep_frame=False,
                label=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for interval in intervals
        ]
        self.spans_read: list[Interval] = []

    async def for_span(self, span: Interval) -> tuple[OffPlanPeriodRecord, ...]:
        self.spans_read.append(span)
        return tuple(row for row in self.rows if row.interval.overlaps(span))


# --------------------------------------------------------------------------------
# The occupancy reader
# --------------------------------------------------------------------------------


async def test_a_week_with_no_declared_time_off_holds_nothing() -> None:
    occupancy = await OffPlanOccupancy(StoredPeriods()).read(WEEK, WEEK_SPAN)

    assert occupancy.off_plan == EMPTY
    assert occupancy.frame == EMPTY
    assert occupancy.anchors == EMPTY
    assert occupancy.absolute_forbidden == EMPTY
    assert occupancy.by_area == {}


async def test_the_reader_asks_for_the_span_it_was_given() -> None:
    periods = StoredPeriods(OFF_PLAN_WEEK.off_plan)

    await OffPlanOccupancy(periods).read(WEEK, WEEK_SPAN)

    assert periods.spans_read == [WEEK_SPAN]


async def test_a_span_reaching_past_the_week_is_contributed_unclipped() -> None:
    # Clipping here would be a second place the week's bounds were applied. The denominator
    # subtracts within the span, so the part outside removes nothing.
    occupancy = await OffPlanOccupancy(StoredPeriods(OFF_PLAN_WEEK.off_plan)).read(WEEK, WEEK_SPAN)

    assert occupancy.off_plan == IntervalSet([OFF_PLAN_WEEK.off_plan])
    assert occupancy.off_plan.total_minutes() == OFF_PLAN_WEEK.off_plan_minutes
    # And it is genuinely more than the week holds of it, so an unclipped contribution is a
    # claim this assertion can distinguish from a clipped one.
    assert occupancy.off_plan.clip(WEEK_SPAN).total_minutes() == (
        OFF_PLAN_WEEK.off_plan_minutes_inside_the_week
    )
    assert occupancy.off_plan.total_minutes() > occupancy.off_plan.clip(WEEK_SPAN).total_minutes()


async def test_a_span_outside_the_week_is_not_contributed_at_all() -> None:
    # Its end is the week's first instant, so it covers nothing inside the week.
    ending_where_the_week_begins = Interval(WEEK_SPAN.start - timedelta(days=1), WEEK_SPAN.start)
    periods = StoredPeriods(ending_where_the_week_begins)

    occupancy = await OffPlanOccupancy(periods).read(WEEK, WEEK_SPAN)

    assert occupancy.off_plan == EMPTY


async def test_two_periods_that_abut_reach_the_denominator_as_one_span() -> None:
    # `IntervalSet` merges adjacent members, so a holiday declared as two consecutive periods
    # subtracts exactly what one period over the pair would.
    first = Interval(WEEK_SPAN.start, WEEK_SPAN.start + timedelta(days=1))
    second = Interval(WEEK_SPAN.start + timedelta(days=1), WEEK_SPAN.start + timedelta(days=2))
    periods = StoredPeriods(first, second)

    occupancy = await OffPlanOccupancy(periods).read(WEEK, WEEK_SPAN)

    assert occupancy.off_plan == IntervalSet([Interval(first.start, second.end)])
    assert len(occupancy.off_plan) == 1


async def test_stored_periods_that_overlap_subtract_what_one_of_them_would() -> None:
    # The write path refuses such a pair, so this is not a state the product produces. The
    # property is what lets the read path union rather than re-check: a broken invariant cannot
    # make the denominator wrong, so a read must not fail over it.
    span = Interval(WEEK_SPAN.start, WEEK_SPAN.start + timedelta(days=2))
    inside = Interval(WEEK_SPAN.start + timedelta(days=1), WEEK_SPAN.start + timedelta(days=2))

    occupancy = await OffPlanOccupancy(StoredPeriods(span, inside)).read(WEEK, WEEK_SPAN)

    assert occupancy.off_plan == IntervalSet([span])


async def test_a_frame_span_inside_an_off_plan_span_is_subtracted_once() -> None:
    # An off-plan span reduces the total through the union of what it covers, read here through the
    # api's own reader: the frame occurrence is the eight hours the fixture puts inside the off-plan
    # span, and it must leave the denominator once rather than twice.
    occupancy = await OffPlanOccupancy(StoredPeriods(OFF_PLAN_WEEK.off_plan)).read(WEEK, WEEK_SPAN)
    frame = IntervalSet([OFF_PLAN_WEEK.frame_inside])

    unioned = discretionary_time(WEEK_SPAN, frame, EMPTY, EMPTY, occupancy.off_plan)

    inside_the_week = occupancy.off_plan.clip(WEEK_SPAN).total_minutes()
    assert inside_the_week == OFF_PLAN_WEEK.off_plan_minutes_inside_the_week
    assert unioned == WEEK_SPAN.total_minutes() - inside_the_week
    summed = WEEK_SPAN.total_minutes() - (inside_the_week + frame.total_minutes())
    assert summed == unioned - 8 * 60


# --------------------------------------------------------------------------------
# The reading
# --------------------------------------------------------------------------------


def test_a_week_with_no_time_off_reads_zero_and_says_nothing() -> None:
    reading = off_plan_reading(WEEK_SPAN, EMPTY)

    assert reading.minutes == 0
    assert reading.statement is None


def test_a_partly_off_plan_week_reads_the_clipped_minutes_and_says_nothing() -> None:
    # The Friday-to-Monday span, whose Monday part belongs to the following week. A statement
    # here would tell a user their week was off when four of its days were not.
    reading = off_plan_reading(WEEK_SPAN, IntervalSet([OFF_PLAN_WEEK.off_plan]))

    assert reading.minutes == OFF_PLAN_WEEK.off_plan_minutes_inside_the_week
    assert reading.statement is None


def test_the_following_week_reads_the_rest_of_the_same_span() -> None:
    reading = off_plan_reading(FOLLOWING_SPAN, IntervalSet([OFF_PLAN_WEEK.off_plan]))

    assert reading.minutes == OFF_PLAN_WEEK.off_plan_minutes_inside_the_following_week
    assert reading.statement is None


def test_a_week_covered_end_to_end_says_why_every_figure_is_zero() -> None:
    reading = off_plan_reading(WEEK_SPAN, IntervalSet([OFF_PLAN_WEEK.whole_week]))

    assert reading.minutes == OFF_PLAN_WEEK.week_span_minutes
    assert reading.statement == WHOLE_WEEK_STATEMENT


def test_a_week_covered_by_a_wider_span_says_the_same_thing() -> None:
    wider = Interval(WEEK_SPAN.start - timedelta(days=3), WEEK_SPAN.end + timedelta(days=3))

    reading = off_plan_reading(WEEK_SPAN, IntervalSet([wider]))

    # The figure is clipped to the week even though the span is not.
    assert reading.minutes == OFF_PLAN_WEEK.week_span_minutes
    assert reading.statement == WHOLE_WEEK_STATEMENT


def test_a_week_covered_by_two_abutting_spans_says_the_same_thing() -> None:
    midweek = WEEK_SPAN.start + timedelta(days=3)
    halves = IntervalSet([Interval(WEEK_SPAN.start, midweek), Interval(midweek, WEEK_SPAN.end)])

    reading = off_plan_reading(WEEK_SPAN, halves)

    assert reading.statement == WHOLE_WEEK_STATEMENT


@pytest.mark.parametrize("shortfall", [timedelta(minutes=15), timedelta(seconds=30)])
def test_a_week_all_but_covered_does_not_claim_to_be_off_plan(shortfall: timedelta) -> None:
    almost = Interval(WEEK_SPAN.start, WEEK_SPAN.end - shortfall)

    reading = off_plan_reading(WEEK_SPAN, IntervalSet([almost]))

    assert reading.statement is None


def test_a_span_whose_own_length_carries_seconds_is_not_read_as_covered() -> None:
    # Emptiness of the residual rather than a comparison of minute counts. Both counts truncate,
    # and here they truncate to the same number while thirty seconds of the span are still on
    # plan: `60` off-plan minutes inside a span that also reads as `60`. A week's span cannot
    # carry seconds in any zone this product serves, so this is what makes the choice provable
    # rather than an assertion about the arithmetic.
    span = Interval(WEEK_SPAN.start, WEEK_SPAN.start + timedelta(minutes=60, seconds=30))
    covered = IntervalSet([Interval(span.start, span.start + timedelta(minutes=60))])

    reading = off_plan_reading(span, covered)

    assert reading.minutes == span.total_minutes() == 60
    assert reading.statement is None
