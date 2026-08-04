"""The one budget route.

Thin, on purpose. It validates the request shape, resolves who is asking, calls one service
method, and maps the result. The period's own shape is validated in the service, by the domain
parser that owns the identifier, so no pattern is declared here that could drift from it.

**This route writes nothing.** No row, no input version bump, and no verdict. Reading a budget
is a read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.budgets.config import PERIOD_EXAMPLE, PERIOD_PARAMETER
from syncr_api.budgets.injection import BudgetServiceDep
from syncr_api.budgets.schemas import AreaBudgetReading, BudgetResponse, PeriodSpan

if TYPE_CHECKING:
    from syncr_api.budgets.service import BudgetView

router = APIRouter()

_PERIOD_DESCRIPTION = (
    f"The ISO week to report on, such as '{PERIOD_EXAMPLE}'. Every figure in the report is "
    "week-scoped, because discretionary time derives from one week's span."
)


@router.get("", summary="Discretionary time, per-Area target and actual, and the two residuals")
async def read_budget(
    principal: PrincipalDep,
    service: BudgetServiceDep,
    period: str = Query(alias=PERIOD_PARAMETER, description=_PERIOD_DESCRIPTION),
) -> BudgetResponse:
    """One period's budget report. Writes nothing."""
    return _as_response(await service.read(principal, period))


def _as_response(view: BudgetView) -> BudgetResponse:
    report = view.report
    return BudgetResponse(
        period=str(view.period),
        span=PeriodSpan(start=view.span.start, end=view.span.end),
        discretionary_minutes=report.discretionary_minutes,
        unallocated_minutes=report.unallocated_minutes,
        oversubscription_minutes=report.oversubscription_minutes,
        off_plan_minutes=view.off_plan.minutes,
        off_plan_statement=view.off_plan.statement,
        areas=[
            AreaBudgetReading(
                area_id=allocation.area_id,
                target_minutes=allocation.target_minutes,
                actual_minutes=allocation.actual_minutes,
                rolled_up_target_minutes=allocation.rolled_up_target_minutes,
                rolled_up_actual_minutes=allocation.rolled_up_actual_minutes,
            )
            for allocation in report.allocations
        ],
    )
