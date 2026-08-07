"""The one approve route.

Thin, on purpose. It resolves who is asking, calls exactly one service method, and maps the result
onto its response shape through that shape's own ``of``, so this module holds no mapping of its own.

The week is a path segment and its shape is validated in the service, by the domain parser that owns
the identifier, so no pattern is declared here that could drift from it.

**This route DEMANDS an ``Idempotency-Key``**, which makes it the first in the api to do so. Every
other unsafe route offers the header; here a repeat is unrecoverable, because approval appends to a
table with no update and no delete path, and there is no unapprove. A retry without a key would
therefore append a second approved revision of one document. A request with no key is refused before
anything is read.

The key is not the whole of that protection and does not claim to be: two clicks carrying two
DIFFERENT keys are two requests, and what stops the second from appending a revision of its own is
the service's own claim on the slot.

The body is empty. Approving names no figures: what is approved is the proposal the week holds, and
a caller that could state anything about it could state something the user was not shown.
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter

from syncr_api.accounts.injection import ClientPrincipalDep
from syncr_api.approvals.config import APPROVE_PATH, APPROVE_ROUTE
from syncr_api.approvals.injection import ApprovalServiceDep
from syncr_api.approvals.schemas import WeekApprovedResponse
from syncr_api.idempotency.injection import KeyedIdempotencyGuardDep

router = APIRouter()


@router.post(
    APPROVE_PATH,
    status_code=HTTPStatus.CREATED,
    summary="Approve the pending proposal. Needs an Idempotency-Key",
)
async def approve_week(
    iso_week: str,
    principal: ClientPrincipalDep,
    guard: KeyedIdempotencyGuardDep,
    service: ApprovalServiceDep,
) -> WeekApprovedResponse:
    """Make what the week is proposing its plan of record, and answer with what that wrote."""

    async def assent() -> WeekApprovedResponse:
        return WeekApprovedResponse.of(await service.approve(principal, iso_week))

    return await guard.once(APPROVE_ROUTE, WeekApprovedResponse, assent)
