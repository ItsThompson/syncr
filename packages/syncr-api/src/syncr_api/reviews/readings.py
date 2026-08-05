"""The pie review's figures, assembled from the reviewed quarter and the Areas' declarations.

Every figure here comes from ``syncr_domain``, through ``figures`` and ``proposals``. This module
decides which weeks answer which question and nothing else: the summary strip, the deviation bars,
the probe and the solver's capacity check all consume the same computation, and a second one here
would be the one that quietly disagreed.

**Two windows, and they answer different questions.** Composition and deviation are the NAMED
week's, because "composition now" is a statement about now. The trend and the proposal are the
quarter ending with that week, because a bad week and a bad quarter are the two things US-AREA-05
exists to tell apart.

**The share compared against is the one in effect now, not the one each week was solved under.**
The review exists to decide whether to change the current budget, so the current budget is what
behaviour is compared with. A past week's approved revision keeps its own inputs, and nothing here
rewrites them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.offplan.reading import off_plan_reading
from syncr_api.reviews.coverage import NO_DAYS
from syncr_api.reviews.figures import (
    actual_minutes,
    oversubscription,
    targets,
    vacancy_minutes,
    vacancy_target,
)
from syncr_api.reviews.proposals import proposal_over

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syncr_api.offplan.reading import OffPlanReading
    from syncr_api.reviews.coverage import DayCounts
    from syncr_api.reviews.history import ReviewedWeek
    from syncr_api.reviews.proposals import ProposalReading
    from syncr_domain.budgets import AreaShare
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Interval
    from syncr_domain.weeks import IsoWeek


@dataclass(frozen=True, slots=True, kw_only=True)
class CategoryReading:
    """One Area's row of the review, or the vacancy's.

    ``area_id`` is ``None`` for the vacancy. ``target_minutes`` is ``None`` when the week holds no
    plan of record, because a target divides a denominator that week does not have.
    """

    area_id: AreaId | None
    target_minutes: int | None
    actual_minutes: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TrendWeek:
    """One week's bar of the trend: what each category held, and how settled the week is."""

    iso_week: IsoWeek
    slices: tuple[CategoryReading, ...]
    days: DayCounts


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetReviewReading:
    """One period's review: the figures, the categories, the trend, and the proposal.

    ``discretionary_minutes`` and the two residuals are ``None`` together, for one reason: the named
    week holds no plan of record, so there is no denominator and nothing derived from one.
    """

    period: IsoWeek
    span: Interval
    discretionary_minutes: int | None
    unallocated_minutes: int | None
    oversubscription_minutes: int | None
    off_plan: OffPlanReading
    days: DayCounts
    quarter_days: DayCounts
    categories: tuple[CategoryReading, ...]
    trend: tuple[TrendWeek, ...]
    proposal: ProposalReading


def budget_review_reading(
    quarter: Sequence[ReviewedWeek], *, shares: Sequence[AreaShare]
) -> BudgetReviewReading:
    """The whole review, over the quarter's weeks oldest first and the Areas declared now.

    The named week is the LAST of the quarter: the window ends at the week the caller asked for,
    which is what makes "composition now" and "the trend up to now" one read.
    """
    named = quarter[-1]
    return BudgetReviewReading(
        period=named.iso_week,
        span=named.span,
        discretionary_minutes=named.discretionary_minutes,
        unallocated_minutes=vacancy_minutes(named),
        oversubscription_minutes=oversubscription(named, shares),
        off_plan=off_plan_reading(named.span, named.off_plan),
        days=named.counts,
        quarter_days=summed(week.counts for week in quarter),
        categories=categories_of(named, shares=shares),
        trend=tuple(
            TrendWeek(
                iso_week=week.iso_week,
                slices=categories_of(week, shares=shares),
                days=week.counts,
            )
            for week in quarter
        ),
        proposal=proposal_over(quarter, shares=shares),
    )


def categories_of(
    week: ReviewedWeek, *, shares: Sequence[AreaShare]
) -> tuple[CategoryReading, ...]:
    """One row per declared Area, then the vacancy, which is the order the wedges are drawn in.

    The vacancy is last so it closes the circle rather than splitting the Areas, and it is present
    whatever it holds: discretionary time no block covers is shown rather than hidden, which is the
    whole reason US-AREA-03 exists.
    """
    declared = targets(week, shares)
    return (
        *(
            CategoryReading(
                area_id=share.area_id,
                target_minutes=declared.get(share.area_id),
                actual_minutes=actual_minutes(week, share.area_id),
            )
            for share in shares
        ),
        CategoryReading(
            area_id=None,
            target_minutes=vacancy_target(week, declared),
            actual_minutes=vacancy_minutes(week) or 0,
        ),
    )


def summed(counts: Iterable[DayCounts]) -> DayCounts:
    """Every week's day counts added, which is the quarter's own."""
    total = NO_DAYS
    for one in counts:
        total += one
    return total
