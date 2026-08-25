"""The two conflict routes.

Thin, on purpose. Each handler validates a body, resolves who is asking, calls exactly one service
method, and maps the result onto a response shape through that shape's own ``of``. No authorization
decision and no persistence: ``tests/test_authorization_boundary.py`` asserts this file cannot reach
either.

``resolve`` takes the idempotency guard, because a retried answer must not be recorded twice. It is
guarded to a stated limit rather than fully: the resolution itself is idempotent by construction,
since the statement that records it matches only an unanswered conflict, so a repeat lands the same
row whether or not the guard replayed it. What the guard adds is the stored RESPONSE, so a retry
after a timeout reads the operation the first attempt created rather than one that has moved on.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from syncr_api.accounts.injection import PrincipalDep, TransactionDep
from syncr_api.conflicts.config import CONFLICTS_PATH, RESOLVE_PATH, RESOLVED_PARAMETER
from syncr_api.conflicts.declarations import ChosenResolution
from syncr_api.conflicts.injection import ConflictServiceDep
from syncr_api.conflicts.schemas import (
    ConflictsResponse,
    ResolveConflictRequest,
    ResolvedConflictResponse,
)
from syncr_api.core.patches import stated
from syncr_api.idempotency.injection import IdempotencyGuardDep

router = APIRouter()

RESOLVE_ROUTE = "conflicts.resolve_conflict"

_RESOLVED_DESCRIPTION = (
    "Narrow the list by state: `false` is what the banner reads, and `true` is the retained "
    "record a repeated collision is computed over. Omit it for both."
)


@router.get(CONFLICTS_PATH, summary="The conflicts this account holds. Writes nothing")
async def list_conflicts(
    principal: PrincipalDep,
    service: ConflictServiceDep,
    resolved: bool | None = Query(
        default=None, alias=RESOLVED_PARAMETER, description=_RESOLVED_DESCRIPTION
    ),
) -> ConflictsResponse:
    """Every conflict, or only the open ones, earliest overlap first."""
    return ConflictsResponse.of(await service.list_all(principal, resolved=resolved))


@router.post(RESOLVE_PATH, summary="Answer one conflict, and do what that answer names")
async def resolve_conflict(
    conflict_id: Annotated[UUID, Path(description="The conflict being answered.")],
    body: ResolveConflictRequest,
    principal: PrincipalDep,
    guard: IdempotencyGuardDep,
    service: ConflictServiceDep,
    transaction: TransactionDep,
) -> ResolvedConflictResponse:
    """Record the answer, free what it frees, and answer with the solve that will read it."""
    chosen = ChosenResolution(
        resolution=body.resolution,
        anchor_type=stated(body, "anchor_type_id", body.anchor_type_id),
    )

    async def resolve() -> ResolvedConflictResponse:
        return ResolvedConflictResponse.of(await service.resolve(principal, conflict_id, chosen))

    answered = await guard.once(RESOLVE_ROUTE, ResolvedConflictResponse, resolve)
    # The answer carries the solve the resolution asked for, so that row must be readable the
    # instant the client holds its identifier. See `get_transaction` for why this commit is here
    # rather than on teardown.
    await transaction.commit()
    return answered
