"""The two pie-review routes.

Thin, on purpose. Each validates the request shape, resolves who is asking, calls one service
method, and maps the result. The period's own shape is validated in the service, by the domain
parser that owns the identifier, so no pattern is declared here that could drift from it.

**The read writes nothing.** No row, no input version bump, and no verdict: reading a review is a
read. The apply is the one write, and it is what US-REV-03's "syncr never re-cuts the budget on its
own" means in code: nothing moves a share except a request the user made.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.budgets.schemas import PeriodSpan
from syncr_api.reviews.config import APPLY_PATH, BUDGET_PATH, PERIOD_EXAMPLE, PERIOD_PARAMETER
from syncr_api.reviews.declarations import shares_asked_for
from syncr_api.reviews.injection import BudgetReviewServiceDep
from syncr_api.reviews.schemas import (
    BudgetApplyRequest,
    BudgetApplyResponse,
    BudgetProposalResponse,
    BudgetReviewResponse,
    CategoryReadingResponse,
    ProposedShareResponse,
    ReviewDayCounts,
    TrendWeekResponse,
)
from syncr_api.reviews.statements import (
    basis_statement,
    confirmed_day_statement,
    denominator_statement,
    proposal_statement,
    quarter_statement,
)

if TYPE_CHECKING:
    from syncr_api.reviews.coverage import DayCounts
    from syncr_api.reviews.proposals import ProposalReading
    from syncr_api.reviews.readings import BudgetReviewReading, CategoryReading, TrendWeek
    from syncr_api.reviews.service import AppliedRevision

router = APIRouter()

_PERIOD_DESCRIPTION = (
    f"The ISO week the review is anchored at, such as '{PERIOD_EXAMPLE}'. Composition and "
    "deviation are that week's; the trend and the proposal are the quarter ending with it."
)


@router.get(BUDGET_PATH, summary="Composition, trend, deviation, and the proposed percentages")
async def read_budget_review(
    principal: PrincipalDep,
    service: BudgetReviewServiceDep,
    period: str = Query(alias=PERIOD_PARAMETER, description=_PERIOD_DESCRIPTION),
) -> BudgetReviewResponse:
    """One quarter's pie review, anchored at ``period``. Writes nothing."""
    return _as_review(await service.read(principal, period))


@router.post(APPLY_PATH, summary="Apply proposed percentages, wholly or adjusted")
async def apply_budget_review(
    principal: PrincipalDep, service: BudgetReviewServiceDep, body: BudgetApplyRequest
) -> BudgetApplyResponse:
    """Declare the shares the caller sent. The proposal's own figures, or its own edits of them."""
    asked = shares_asked_for([(row.area_id, row.budget_percent) for row in body.percentages])
    return _as_applied(await service.apply(principal, asked), asked_for=len(asked.by_area))


def _as_review(reading: BudgetReviewReading) -> BudgetReviewResponse:
    return BudgetReviewResponse(
        period=str(reading.period),
        span=PeriodSpan(start=reading.span.start, end=reading.span.end),
        discretionary_minutes=reading.discretionary_minutes,
        unallocated_minutes=reading.unallocated_minutes,
        oversubscription_minutes=reading.oversubscription_minutes,
        off_plan_minutes=reading.off_plan.minutes,
        off_plan_statement=reading.off_plan.statement,
        statement=denominator_statement(reading.discretionary_minutes),
        days=_as_days(reading.days, statement=confirmed_day_statement(reading.days.confirmed)),
        quarter_days=_as_days(
            reading.quarter_days, statement=quarter_statement(reading.quarter_days.confirmed)
        ),
        categories=[_as_category(one) for one in reading.categories],
        trend=[_as_trend_week(week) for week in reading.trend],
        proposal=_as_proposal(reading.proposal),
    )


def _as_days(counts: DayCounts, *, statement: str | None) -> ReviewDayCounts:
    return ReviewDayCounts(
        confirmed=counts.confirmed,
        unconfirmed=counts.unconfirmed,
        off_plan=counts.off_plan,
        statement=statement,
    )


def _as_category(reading: CategoryReading) -> CategoryReadingResponse:
    return CategoryReadingResponse(
        area_id=reading.area_id,
        target_minutes=reading.target_minutes,
        actual_minutes=reading.actual_minutes,
    )


def _as_trend_week(week: TrendWeek) -> TrendWeekResponse:
    return TrendWeekResponse(
        period=str(week.iso_week),
        slices=[_as_category(one) for one in week.slices],
        days=_as_days(week.days, statement=confirmed_day_statement(week.days.confirmed)),
    )


def _as_proposal(reading: ProposalReading) -> BudgetProposalResponse:
    return BudgetProposalResponse(
        confirmed_weeks=reading.confirmed_weeks,
        required_weeks=reading.required_weeks,
        shares=[
            ProposedShareResponse(
                area_id=share.area_id,
                declared_percent=share.declared_percent,
                observed_percent=share.observed_percent,
                proposed_percent=share.proposed_percent,
                basis=share.basis,
                statement=basis_statement(share.basis),
            )
            for share in reading.shares
        ],
        statement=proposal_statement(
            confirmed_weeks=reading.confirmed_weeks, required_weeks=reading.required_weeks
        ),
    )


def _as_applied(applied: AppliedRevision, *, asked_for: int) -> BudgetApplyResponse:
    changed = len(applied.declared)
    return BudgetApplyResponse(
        applied=changed,
        declared=list(applied.declared),
        changed_at=applied.at,
        statement=(
            f"{changed} of {asked_for} shares were declared."
            if changed
            else f"All {asked_for} shares already held the values sent, so nothing was changed."
        ),
    )
