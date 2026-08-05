"""Area budget arithmetic: floors, the remainder, and the two residuals kept apart.

Two tests here carry the defect an earlier draft of this arithmetic had.
``test_percentages_that_sum_to_exactly_one_hundred_leave_time_unallocated`` and
``test_unallocated_is_never_negative_however_the_budget_is_declared`` are what a
``discretionary - sum(area_target)`` definition of ``unallocated`` fails: it is exactly zero
whenever the percentages happen to sum to 100 while hours sat in no block, and negative
whenever the budget is oversubscribed, which is not a renderable pie wedge.

The interval algebra is real throughout. ``unallocated`` is interval coverage, not a
subtraction of two counts, and that is the whole reason it cannot go negative.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.budgets import (
    AreaShare,
    BudgetError,
    budget_report,
    floor_minutes,
    minutes_after_floors,
    oversubscription_minutes,
    target_minutes,
    unallocated_minutes,
)
from syncr_domain.discretionary import discretionary_intervals, discretionary_time
from syncr_domain.intervals import Interval, IntervalSet
from tests.instants import at
from tests.interval_strategies import interval_sets

WEEK = Interval(at(0), at(0, day=7))
WEEK_MINUTES = 168 * 60

FITNESS = UUID("00000000-0000-4000-8000-000000000001")
CAREER = UUID("00000000-0000-4000-8000-000000000002")
LEARNING = UUID("00000000-0000-4000-8000-000000000003")


def an_open_week() -> IntervalSet:
    """A week with nothing subtracted, so every minute is discretionary."""
    return discretionary_intervals(WEEK, IntervalSet(), IntervalSet(), IntervalSet(), IntervalSet())


def share(
    area_id: UUID,
    *,
    percent: str = "0",
    floor_hours: str | None = None,
    parent_id: UUID | None = None,
) -> AreaShare:
    return AreaShare(
        area_id=area_id,
        parent_id=parent_id,
        floor_minutes=floor_minutes(None if floor_hours is None else Decimal(floor_hours)),
        budget_percent=Decimal(percent),
    )


def blocks(*spans: Interval) -> IntervalSet:
    return IntervalSet(spans)


# --------------------------------------------------------------------------------
# Floors and the proportional remainder
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hours", "minutes"),
    [(None, 0), ("0", 0), ("0.25", 15), ("1", 60), ("4.50", 270), ("168", 10080)],
    ids=["undeclared", "zero", "quarter hour", "one hour", "four and a half", "a whole week"],
)
def test_a_weekly_floor_reads_as_whole_minutes(hours: str | None, minutes: int) -> None:
    assert floor_minutes(None if hours is None else Decimal(hours)) == minutes


def test_a_negative_floor_is_refused() -> None:
    with pytest.raises(BudgetError, match="not a duration"):
        floor_minutes(Decimal("-1"))


def test_the_remainder_is_what_the_floors_leave() -> None:
    shares = [share(FITNESS, floor_hours="4"), share(CAREER, floor_hours="6")]

    assert minutes_after_floors(WEEK_MINUTES, shares) == WEEK_MINUTES - 10 * 60


def test_the_remainder_is_clamped_at_zero_when_the_floors_alone_do_not_fit() -> None:
    # Asserted at the helper. What the clamp PREVENTS is asserted through the whole report in
    # `test_floors_that_cannot_fit_are_reported_as_oversubscription`, which is the test that
    # fails on the unclamped arithmetic.
    shares = [share(FITNESS, floor_hours="100"), share(CAREER, floor_hours="100")]

    assert minutes_after_floors(WEEK_MINUTES, shares) == 0


def test_a_target_is_its_floor_plus_its_share_of_the_remainder() -> None:
    declared = share(FITNESS, percent="25", floor_hours="4")

    assert target_minutes(declared, after_floors=1000) == 4 * 60 + 250


def test_an_area_with_no_declaration_has_a_zero_target() -> None:
    assert target_minutes(share(FITNESS), after_floors=WEEK_MINUTES) == 0


def test_a_share_is_truncated_rather_than_rounded_up() -> None:
    # 33% of 100 minutes is 33 minutes, not 34. Truncating is what keeps the summed targets
    # from exceeding the exact ones, so rounding cannot invent an oversubscription.
    assert target_minutes(share(FITNESS, percent="33"), after_floors=100) == 33


# --------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------


def test_the_denominator_is_discretionary_time_and_the_targets_divide_it() -> None:
    report = budget_report(
        discretionary=an_open_week(),
        shares=[share(FITNESS, percent="25"), share(CAREER, percent="75")],
        covered={},
    )

    assert report.discretionary_minutes == WEEK_MINUTES
    assert [allocation.target_minutes for allocation in report.allocations] == [
        WEEK_MINUTES // 4,
        WEEK_MINUTES * 3 // 4,
    ]
    assert report.oversubscription_minutes == 0


def test_percentages_summing_past_one_hundred_are_accepted_and_reported() -> None:
    report = budget_report(
        discretionary=an_open_week(),
        shares=[share(FITNESS, percent="80"), share(CAREER, percent="50")],
        covered={},
    )

    # Accepted, never rejected: the excess is a named quantity of its own.
    assert report.oversubscription_minutes == WEEK_MINUTES * 30 // 100
    # And it is NOT a negative unallocated. The two figures mean different things.
    assert report.unallocated_minutes == WEEK_MINUTES


def test_percentages_that_sum_to_exactly_one_hundred_leave_time_unallocated() -> None:
    # The defect the earlier `discretionary - sum(area_target)` definition had: at exactly
    # 100% that expression is zero every week, however much time sat in no block.
    report = budget_report(
        discretionary=an_open_week(),
        shares=[share(FITNESS, percent="40"), share(CAREER, percent="60")],
        covered={FITNESS: blocks(Interval(at(9), at(11)))},
    )

    assert sum(allocation.target_minutes for allocation in report.allocations) == WEEK_MINUTES
    assert report.oversubscription_minutes == 0
    assert report.unallocated_minutes == WEEK_MINUTES - 120


def test_unallocated_is_the_discretionary_time_no_block_covers() -> None:
    report = budget_report(
        discretionary=an_open_week(),
        shares=[share(FITNESS, percent="50"), share(CAREER, percent="50")],
        covered={
            FITNESS: blocks(Interval(at(6), at(7))),
            CAREER: blocks(Interval(at(9), at(12))),
        },
    )

    assert report.unallocated_minutes == WEEK_MINUTES - (60 + 180)
    assert [allocation.actual_minutes for allocation in report.allocations] == [60, 180]


def test_two_areas_covering_the_same_minutes_do_not_double_count_them() -> None:
    # Two blocks cannot really occupy one minute, but the figure must not depend on that:
    # unallocated is coverage, so an overlap removes the minute once.
    overlapping = blocks(Interval(at(9), at(11)))
    report = budget_report(
        discretionary=an_open_week(),
        shares=[share(FITNESS), share(CAREER)],
        covered={FITNESS: overlapping, CAREER: overlapping},
    )

    assert report.unallocated_minutes == WEEK_MINUTES - 120


def test_an_areas_actual_never_counts_time_that_left_the_denominator() -> None:
    # A block placed inside an off-plan period is time no Area may claim, so it cannot show
    # up as that Area's consumption either. Clipping is what keeps the wedges and the
    # residual adding up to the denominator.
    off_plan = IntervalSet([Interval(at(0, day=4), at(0, day=7))])
    discretionary = discretionary_intervals(
        WEEK, IntervalSet(), IntervalSet(), IntervalSet(), off_plan
    )
    report = budget_report(
        discretionary=discretionary,
        shares=[share(FITNESS)],
        covered={FITNESS: blocks(Interval(at(23, day=3), at(1, day=4)))},
    )

    assert report.discretionary_minutes == 96 * 60
    assert report.allocations[0].actual_minutes == 60
    assert report.unallocated_minutes == 96 * 60 - 60


def test_a_frame_only_week_reports_a_zero_target_for_every_area() -> None:
    # Routines define how much time exists, so they never appear in Area budget arithmetic:
    # a week that is entirely frame has no discretionary time and therefore nothing to
    # divide.
    frame_only = discretionary_intervals(
        WEEK, IntervalSet([WEEK]), IntervalSet(), IntervalSet(), IntervalSet()
    )
    report = budget_report(
        discretionary=frame_only,
        shares=[share(FITNESS, percent="40"), share(CAREER, percent="60")],
        covered={},
    )

    assert report.discretionary_minutes == 0
    assert [allocation.target_minutes for allocation in report.allocations] == [0, 0]
    assert report.unallocated_minutes == 0
    assert report.oversubscription_minutes == 0


def test_a_floor_a_frame_only_week_cannot_meet_is_reported_as_oversubscription() -> None:
    # A target is GROSS: netted against nothing and clamped to nothing, because it is a
    # reporting figure rather than a reservation. So a floor declared in a week with no
    # discretionary time stays visible, as the excess it is.
    #
    # This case passes with or without the clamp, because a zero share multiplies the remainder
    # away. The clamp's own case is the test below.
    frame_only = discretionary_intervals(
        WEEK, IntervalSet([WEEK]), IntervalSet(), IntervalSet(), IntervalSet()
    )
    report = budget_report(
        discretionary=frame_only, shares=[share(FITNESS, floor_hours="4")], covered={}
    )

    assert report.allocations[0].target_minutes == 240
    assert report.oversubscription_minutes == 240


def test_floors_that_cannot_fit_are_reported_as_oversubscription() -> None:
    # The clamp, asserted where the defect it prevents actually appears: through the report,
    # with floors that exceed discretionary time AND a share above zero. Both conditions are
    # needed, which is why the two tests above cannot stand in for this one.
    #
    # Two Areas, each declaring a 100-hour floor and half the remainder, over a 168-hour week:
    #
    #   discretionary     10080
    #   floors sum        12000
    #   CLAMPED   targets [6000, 6000]   oversubscription 1920   the floors' own excess
    #   UNCLAMPED targets [5040, 5040]   oversubscription    0   an impossible budget, feasible
    #
    # Unclamped, each 50% share multiplies the -1920 remainder and takes 960 off that Area's own
    # floor, so the summed targets collapse to exactly discretionary and a budget needing 200
    # hours in a 168-hour week reports as fitting perfectly.
    report = budget_report(
        discretionary=an_open_week(),
        shares=[
            share(FITNESS, percent="50", floor_hours="100"),
            share(CAREER, percent="50", floor_hours="100"),
        ],
        covered={},
    )

    assert [allocation.target_minutes for allocation in report.allocations] == [6000, 6000]
    assert report.oversubscription_minutes == 1920
    # The reported excess IS the floors' excess, which is what makes the figure actionable: the
    # user has to give back 32 hours of floor, not reword a percentage.
    assert report.oversubscription_minutes == 12000 - WEEK_MINUTES
    # And the residual is untouched by any of it. Nothing is planned, so every discretionary
    # minute is still in no block.
    assert report.unallocated_minutes == WEEK_MINUTES


def test_a_child_areas_time_rolls_up_into_its_parent() -> None:
    report = budget_report(
        discretionary=an_open_week(),
        shares=[
            share(CAREER, percent="50"),
            share(LEARNING, percent="10", parent_id=CAREER),
        ],
        covered={
            CAREER: blocks(Interval(at(9), at(10))),
            LEARNING: blocks(Interval(at(14), at(16))),
        },
    )
    career, learning = report.allocations

    assert career.actual_minutes == 60
    assert career.rolled_up_actual_minutes == 180
    assert career.rolled_up_target_minutes == career.target_minutes + learning.target_minutes
    # A leaf rolls up to itself, so a report can render one column for both.
    assert learning.rolled_up_actual_minutes == learning.actual_minutes


def test_an_area_declared_as_its_own_parent_is_refused() -> None:
    with pytest.raises(BudgetError, match="its own parent"):
        share(FITNESS, parent_id=FITNESS)


def test_a_cycle_in_the_hierarchy_is_refused_rather_than_walked_forever() -> None:
    # The API cannot produce one, because a parent is named at creation and never changed.
    # This function is public, so its termination must not rest on that.
    report = budget_report(
        discretionary=an_open_week(),
        shares=[
            AreaShare(
                area_id=FITNESS, parent_id=CAREER, floor_minutes=0, budget_percent=Decimal(0)
            ),
            AreaShare(
                area_id=CAREER, parent_id=FITNESS, floor_minutes=0, budget_percent=Decimal(0)
            ),
        ],
        covered={FITNESS: blocks(Interval(at(9), at(10)))},
    )

    assert [allocation.rolled_up_actual_minutes for allocation in report.allocations] == [60, 60]


@pytest.mark.parametrize(
    ("floor_minutes_value", "percent"),
    [(-1, "0"), (0, "-1")],
    ids=["a negative floor", "a negative share"],
)
def test_a_declaration_that_is_not_one_is_refused(floor_minutes_value: int, percent: str) -> None:
    with pytest.raises(BudgetError):
        AreaShare(
            area_id=FITNESS,
            parent_id=None,
            floor_minutes=floor_minutes_value,
            budget_percent=Decimal(percent),
        )


# --------------------------------------------------------------------------------
# Properties
# --------------------------------------------------------------------------------

percents = st.decimals(min_value=0, max_value=100, places=2, allow_nan=False, allow_infinity=False)
floors = st.integers(min_value=0, max_value=WEEK_MINUTES)


@st.composite
def declared_budgets(draw: st.DrawFn) -> tuple[list[AreaShare], dict[UUID, IntervalSet]]:
    count = draw(st.integers(min_value=0, max_value=4))
    shares = [
        AreaShare(
            area_id=uuid4(),
            parent_id=None,
            floor_minutes=draw(floors),
            budget_percent=draw(percents),
        )
        for _ in range(count)
    ]
    covered = {declared.area_id: draw(interval_sets(max_size=3)) for declared in shares}
    return shares, covered


@given(declared_budgets(), interval_sets())
def test_unallocated_is_never_negative_however_the_budget_is_declared(
    declared: tuple[list[AreaShare], dict[UUID, IntervalSet]], off_plan: IntervalSet
) -> None:
    shares, covered = declared
    discretionary = discretionary_intervals(
        WEEK, IntervalSet(), IntervalSet(), IntervalSet(), off_plan
    )

    report = budget_report(discretionary=discretionary, shares=shares, covered=covered)

    assert report.unallocated_minutes >= 0
    assert report.unallocated_minutes <= report.discretionary_minutes
    assert report.oversubscription_minutes >= 0


@given(declared_budgets())
def test_the_wedges_and_the_residual_add_up_to_the_denominator(
    declared: tuple[list[AreaShare], dict[UUID, IntervalSet]],
) -> None:
    # What makes the composition pie renderable: every actual is clipped to the denominator
    # and the residual is what nothing covered, so the figures tile it.
    shares, covered = declared
    discretionary = an_open_week()

    report = budget_report(discretionary=discretionary, shares=shares, covered=covered)

    claimed = IntervalSet()
    for declared_share in shares:
        claimed = claimed.union(covered[declared_share.area_id])
    covered_minutes = discretionary.intersect(claimed).total_minutes()
    assert covered_minutes + report.unallocated_minutes == report.discretionary_minutes


@given(declared_budgets())
def test_rounding_never_invents_an_oversubscription(
    declared: tuple[list[AreaShare], dict[UUID, IntervalSet]],
) -> None:
    shares, covered = declared
    discretionary = an_open_week()
    exact_floors = sum(declared_share.floor_minutes for declared_share in shares)
    exact_percent = sum(declared_share.budget_percent for declared_share in shares)

    report = budget_report(discretionary=discretionary, shares=shares, covered=covered)

    fits = exact_floors <= discretionary.total_minutes() and exact_percent <= 100
    assert not (fits and report.oversubscription_minutes > 0)


@given(interval_sets())
def test_a_budget_with_no_areas_leaves_the_whole_denominator_unallocated(
    off_plan: IntervalSet,
) -> None:
    discretionary = discretionary_intervals(
        WEEK, IntervalSet(), IntervalSet(), IntervalSet(), off_plan
    )

    report = budget_report(discretionary=discretionary, shares=[], covered={})

    assert report.allocations == ()
    assert report.unallocated_minutes == discretionary_time(
        WEEK, IntervalSet(), IntervalSet(), IntervalSet(), off_plan
    )


def test_unallocated_minutes_is_the_denominator_less_what_is_claimed_of_it() -> None:
    # The residual on its own, because a second caller reads it: a plan document carries the same
    # figure over its own blocks, and a second statement of the subtraction is how the report and
    # the document would come to disagree about one week.
    discretionary = IntervalSet([Interval(at(9), at(12))])
    claimed = IntervalSet([Interval(at(10), at(11))])

    assert unallocated_minutes(discretionary, claimed) == 120


def test_time_claimed_outside_the_denominator_claims_none_of_it() -> None:
    # A block covering time that left the denominator claims nothing, which the subtraction already
    # says, so no caller has to clip its covered set first.
    discretionary = IntervalSet([Interval(at(9), at(12))])
    elsewhere = IntervalSet([Interval(at(1), at(3))])

    assert unallocated_minutes(discretionary, elsewhere) == 180


def test_targets_are_oversubscribed_by_what_they_exceed_the_denominator_by() -> None:
    # Stated over the targets rather than over a report's rows, because two callers hold theirs in
    # different shapes and the figure needs nothing else.
    assert oversubscription_minutes([60, 120], 100) == 80
    assert oversubscription_minutes([60, 120], 180) == 0
    assert oversubscription_minutes([], 0) == 0
