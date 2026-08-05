"""The four week routes.

Thin, on purpose. Each handler resolves who is asking, calls exactly one service method, and maps
the result onto a response shape. No authorization decision and no persistence.

The week is a path segment and its shape is validated in the service, by the domain parser that owns
the identifier, so no pattern is declared here that could drift from it.

**Three of the four are reads and they write nothing at all**: no revision, no operation, no version
bump, and no ``VerdictEvent``. The fourth asks for a solve and answers with the operation to follow
rather than with a plan, because the plan does not exist yet: a request that answered with a week
would be answering with the week it is about to replace.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.core.schemas import WireSpan
from syncr_api.offplan.schemas import OffPlanPeriodResponse
from syncr_api.plans.document_schemas import PlanDocumentResponse
from syncr_api.plans.injection import WeekServiceDep
from syncr_api.plans.schemas import (
    EmptyWeekResponse,
    WeekReadingsResponse,
    WeekRevisionResponse,
    WeekRevisionsResponse,
    WeekVerdictResponse,
    WeekViewResponse,
)
from syncr_api.plans.week_config import (
    IMMEDIATE_PARAMETER,
    REVISIONS_PATH,
    SOLVE_PATH,
    VERDICT_PATH,
    WEEK_PATH,
)
from syncr_api.solving.schemas import OperationResponse

if TYPE_CHECKING:
    from syncr_api.plans.service import WeekView

router = APIRouter()

_IMMEDIATE_DESCRIPTION = (
    "Bypass the debounce window a solve would otherwise wait out, which is what the 'solve this "
    "week now' action on an empty week sends."
)


@router.get(WEEK_PATH, summary="The composed week view. Writes nothing")
async def read_week(
    iso_week: str, principal: PrincipalDep, service: WeekServiceDep
) -> WeekViewResponse:
    """The Week screen's whole read: the plan, or the reason there is none."""
    return _as_response(await service.read(principal, iso_week))


@router.get(REVISIONS_PATH, summary="Revision history for the week. Read-only")
async def read_revisions(
    iso_week: str, principal: PrincipalDep, service: WeekServiceDep
) -> WeekRevisionsResponse:
    """Every revision this week's plan has had, newest first."""
    found = await service.revisions(principal, iso_week)
    return WeekRevisionsResponse(revisions=[WeekRevisionResponse.of(record) for record in found])


@router.get(VERDICT_PATH, summary="The verdict alone, for a cheap refresh. Writes nothing")
async def read_verdict(
    iso_week: str, principal: PrincipalDep, service: WeekServiceDep
) -> WeekVerdictResponse:
    """The week's verdict. Always null in this deployment, and this read appends no event."""
    await service.verdict(principal, iso_week)
    return WeekVerdictResponse()


@router.post(
    SOLVE_PATH,
    status_code=HTTPStatus.ACCEPTED,
    summary="Request a solve of this week. Idempotent per week, and needs no key",
)
async def request_solve(
    iso_week: str,
    principal: PrincipalDep,
    service: WeekServiceDep,
    immediate: bool = Query(
        default=False, alias=IMMEDIATE_PARAMETER, description=_IMMEDIATE_DESCRIPTION
    ),
) -> OperationResponse:
    """Ask for a plan for this week, and answer with the operation to follow."""
    return OperationResponse.of(
        await service.request_solve(principal, iso_week, immediate=immediate)
    )


def _as_response(view: WeekView) -> WeekViewResponse:
    return WeekViewResponse(
        iso_week=str(view.iso_week),
        span=WireSpan.of(view.span),
        zone_by_date={day.isoformat(): zone for day, zone in sorted(view.zone_by_date.items())},
        live=None if view.live is None else PlanDocumentResponse.of(view.live),
        empty_reason=None if view.empty is None else view.empty.reason,
        empty_week=None if view.empty is None else EmptyWeekResponse.of(view.empty),
        off_plan=[OffPlanPeriodResponse.of(period) for period in view.off_plan],
        operation=None if view.operation is None else OperationResponse.of(view.operation),
        input_version=view.input_version,
        readings=None if view.readings is None else WeekReadingsResponse.of(view.readings),
    )
