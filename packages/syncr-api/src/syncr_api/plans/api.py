"""The five week routes.

Thin, on purpose. Each handler resolves who is asking, calls exactly one service method, and maps
the result onto a response shape through that shape's own ``of``, so this module holds no mapping of
its own: the wire shape of a value belongs beside the shape.

The week is a path segment and its shape is validated in the service, by the domain parser that owns
the identifier, so no pattern is declared here that could drift from it.

**Four of the five are reads and they write nothing at all**: no revision, no operation, no version
bump, and no ``VerdictEvent``. Three of the four compute a verdict, which is what a read may do;
recording one is what it may not. The fifth asks for a solve and answers with the operation to
follow rather than with a plan, because the plan does not exist yet: a request that answered with a
week would be answering with the week it is about to replace.
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Query

from syncr_api.accounts.injection import ClientPrincipalDep, PrincipalDep, TransactionDep
from syncr_api.plans.injection import WeekServiceDep
from syncr_api.plans.proposal_schemas import PendingProposalResponse
from syncr_api.plans.schemas import (
    WeekRevisionsResponse,
    WeekVerdictResponse,
    WeekViewResponse,
)
from syncr_api.plans.week_config import (
    IMMEDIATE_PARAMETER,
    PROPOSAL_PATH,
    REVISIONS_PATH,
    SOLVE_PATH,
    VERDICT_PATH,
    WEEK_PATH,
)
from syncr_api.solving.schemas import OperationResponse

router = APIRouter()

_IMMEDIATE_DESCRIPTION = (
    "Bypass the debounce window a solve would otherwise wait out, which is what the 'solve this "
    "week now' action on an empty week sends."
)


@router.get(WEEK_PATH, summary="The composed week view. Writes nothing")
async def read_week(
    iso_week: str, principal: ClientPrincipalDep, service: WeekServiceDep
) -> WeekViewResponse:
    """The Week screen's whole read: the plan, or the reason there is none."""
    return WeekViewResponse.of(await service.read(principal, iso_week))


@router.get(REVISIONS_PATH, summary="Revision history for the week. Read-only")
async def read_revisions(
    iso_week: str, principal: PrincipalDep, service: WeekServiceDep
) -> WeekRevisionsResponse:
    """Every revision this week's plan has had, newest first, and whether more exist."""
    return WeekRevisionsResponse.of(await service.revisions(principal, iso_week))


@router.get(VERDICT_PATH, summary="The verdict alone, for a cheap refresh. Writes nothing")
async def read_verdict(
    iso_week: str, principal: PrincipalDep, service: WeekServiceDep
) -> WeekVerdictResponse:
    """The week's verdict, null when the week holds no plan, and this read appends no event."""
    return WeekVerdictResponse.of(await service.verdict(principal, iso_week))


@router.get(PROPOSAL_PATH, summary="The pending proposal, or 404 when the slot is empty")
async def read_proposal(
    iso_week: str, principal: PrincipalDep, service: WeekServiceDep
) -> PendingProposalResponse:
    """What this week is asking assent for, and what the solve that proposed it proved."""
    return PendingProposalResponse.of(await service.proposal(principal, iso_week))


@router.post(
    SOLVE_PATH,
    status_code=HTTPStatus.ACCEPTED,
    summary="Request a solve of this week. Idempotent per week, and needs no key",
)
async def request_solve(
    iso_week: str,
    principal: ClientPrincipalDep,
    service: WeekServiceDep,
    transaction: TransactionDep,
    immediate: bool = Query(
        default=False, alias=IMMEDIATE_PARAMETER, description=_IMMEDIATE_DESCRIPTION
    ),
) -> OperationResponse:
    """Ask for a plan for this week, and answer with the operation to follow."""
    operation = await service.request_solve(principal, iso_week, immediate=immediate)
    # The answer names this operation, so the row must be readable the instant the client holds
    # its identifier. See `get_transaction` for why this commit is here rather than on teardown.
    await transaction.commit()
    return OperationResponse.of(operation)
