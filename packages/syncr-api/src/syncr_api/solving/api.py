"""The two operation routes: one status by identifier, and one cursor-paginated list.

Thin, on purpose. Each handler reads a query, resolves who is asking, calls exactly one service
method, and maps the result onto a response shape. No authorization decision and no persistence:
``tests/test_authorization_boundary.py`` asserts this file cannot reach either.

Both are reads and there is no route that creates or steps an operation, which is deliberate. An
operation is created by the mutation whose work it tracks, so a route that created one would offer
the client a way to schedule work with no mutation behind it. The CLI polls the first of these to a
terminal state and the browser is pushed the same resource over SSE.

The list route asks for one row more than the page holds, so whether a further page exists is read
off the query rather than guessed from a full page. That is the anchor list's own shape: two list
routes with two answers to "is there more" would be two things for a client to learn about one idea.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from syncr_api.accounts.injection import ClientPrincipalDep, PrincipalDep
from syncr_api.solving.config import (
    OPERATION_PATH,
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
)
from syncr_api.solving.injection import OperationServiceDep
from syncr_api.solving.queries import decode_cursor, encode_cursor, read_kind, read_status
from syncr_api.solving.schemas import OperationResponse, OperationsResponse

router = APIRouter()

_STATUS = Query(default=None, description="Only operations in this status.")
_KIND = Query(default=None, description="Only operations of this kind.")
_CURSOR = Query(default=None, description="The `nextCursor` a previous page handed back.")
_LIMIT = Query(
    default=PAGE_LIMIT_DEFAULT,
    ge=1,
    le=PAGE_LIMIT_MAX,
    description="How many operations one page holds.",
)


@router.get(
    "",
    response_model=OperationsResponse,
    summary="List tracked operations, most recently scheduled first",
)
async def list_operations(
    principal: PrincipalDep,
    operations: OperationServiceDep,
    status: str | None = _STATUS,
    kind: str | None = _KIND,
    cursor: str | None = _CURSOR,
    limit: int = _LIMIT,
) -> OperationsResponse:
    """One page of this tenant's operations."""
    page = await operations.page(
        principal,
        limit=limit + 1,
        status=read_status(status),
        kind=read_kind(kind),
        after=decode_cursor(cursor),
    )
    held, more = page[:limit], page[limit:]
    return OperationsResponse(
        operations=[OperationResponse.of(record) for record in held],
        next_cursor=encode_cursor((held[-1].scheduled_for, held[-1].id)) if more else None,
    )


@router.get(
    OPERATION_PATH,
    response_model=OperationResponse,
    summary="Read one operation's current status",
)
async def read_operation(
    operation_id: UUID, principal: ClientPrincipalDep, operations: OperationServiceDep
) -> OperationResponse:
    """The operation's current truth, so a client that missed a push is not left with a stuck UI."""
    return OperationResponse.of(await operations.report(principal, operation_id))
