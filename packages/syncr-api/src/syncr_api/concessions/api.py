"""The three concession routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one service
method, and maps the result onto a response shape. No authorization decision and no persistence:
``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

The week is a path segment and its shape is validated in the service, by the domain parser that owns
the identifier, so no pattern is declared here that could drift from it.

``POST`` returns the operation to follow rather than a concession, because it created none. That is
the request-and-approve split on the wire: the answer to "what did clicking this tradeoff do" is "a
solve is running against it", and the concession appears only if the proposal it produces is
approved.

The ``POST`` and the ``DELETE`` resolve services of their own, and the difference is the
weekly-session header: only the ``POST`` computes a verdict, but both schedule a solve whose
recorder reads what the request stated about the session, so both resolve the header. The ``GET``
resolves one that never looks at it, because it neither records nor schedules.

Two routers rather than one, and the split is the resource: a tradeoff is a request about the week,
an adjustment is a row the week holds. Requesting is also the only act here that can conflict with
the state of the week, so each router declares the statuses its own routes raise.
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import Response

from syncr_api.accounts.injection import PrincipalDep
from syncr_api.concessions.config import ADJUSTMENT_PATH, ADJUSTMENTS_PATH, TRADEOFFS_PATH
from syncr_api.concessions.declarations import RequestedConcession
from syncr_api.concessions.injection import (
    ConcessionServiceDep,
    RevocationServiceDep,
    TradeoffServiceDep,
)
from syncr_api.concessions.schemas import (
    AdjustmentResponse,
    AdjustmentsResponse,
    TradeoffRequest,
)
from syncr_api.solving.schemas import OperationResponse

tradeoff_router = APIRouter()
adjustment_router = APIRouter()


@tradeoff_router.post(
    TRADEOFFS_PATH,
    status_code=HTTPStatus.ACCEPTED,
    summary="Solve this week against one tradeoff. Persists nothing; returns an operation",
)
async def request_tradeoff(
    iso_week: str,
    body: TradeoffRequest,
    principal: PrincipalDep,
    service: TradeoffServiceDep,
) -> OperationResponse:
    """Ask for a proposal that honors one concession. Nothing is conceded until it is approved."""
    requested = RequestedConcession(kind=body.kind, target_id=body.target_id)
    return OperationResponse.of(await service.request(principal, iso_week, requested))


@adjustment_router.get(ADJUSTMENTS_PATH, summary="The concessions this week has absorbed")
async def list_adjustments(
    iso_week: str, principal: PrincipalDep, service: ConcessionServiceDep
) -> AdjustmentsResponse:
    """Every approved concession for the week. Writes nothing."""
    found = await service.approved(principal, iso_week)
    return AdjustmentsResponse(adjustments=[AdjustmentResponse.of(record) for record in found])


@adjustment_router.delete(
    ADJUSTMENT_PATH,
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    summary="Revoke one concession. Bumps the week's input version and re-solves",
)
async def revoke_adjustment(
    iso_week: str,
    adjustment_id: UUID,
    principal: PrincipalDep,
    service: RevocationServiceDep,
) -> Response:
    """Remove a concession, so the next plan is one the week was not conceded anything for."""
    await service.revoke(principal, iso_week, adjustment_id)
    # Built here rather than returning None, because a returned None is still serialized and a
    # 204 must carry no body at all.
    return Response(status_code=HTTPStatus.NO_CONTENT)
