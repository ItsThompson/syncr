"""The two dependencies a route with an unsafe method declares.

``IdempotencyGuardDep`` accepts a key and works without one, which is what section 13 asks of
every unsafe method. ``KeyedIdempotencyGuardDep`` refuses the request when the header is
absent, for the routes where a repeat would be unrecoverable: approving a proposal twice would
append two revisions, and there is no unapprove.

The body is read here, once, before the framework parses it. Starlette caches it on the
request, so the handler's own parsed body costs nothing extra and the hash is taken over
exactly the bytes the client sent.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

# FastAPI resolves these annotations at RUNTIME to build the dependency graph, so the
# framework types and the dependency aliases stay runtime imports.
from starlette.requests import Request  # noqa: TC002

from syncr_api.accounts.injection import (  # noqa: TC001 - resolved at runtime by FastAPI
    PrincipalDep,
    TransactionDep,
)
from syncr_api.core.clock import utc_now
from syncr_api.core.errors import MalformedRequest
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.idempotency.fingerprints import request_fingerprint
from syncr_api.idempotency.guard import IdempotencyGuard
from syncr_api.idempotency.repository import IdempotencyKeyRepository

MISSING_KEY_DETAIL = (
    f"This request needs an {IDEMPOTENCY_KEY_HEADER} header, so a retry cannot apply it "
    "twice. Nothing was changed. Resend it with a unique key."
)


async def get_idempotency_guard(
    request: Request, transaction: TransactionDep, principal: PrincipalDep
) -> IdempotencyGuard:
    """The guard for this request, scoped to the caller's tenant."""
    return IdempotencyGuard(
        IdempotencyKeyRepository(transaction, principal.tenant_id),
        key=request.headers.get(IDEMPOTENCY_KEY_HEADER),
        request_hash=request_fingerprint(await request.body()),
        clock=utc_now,
    )


type IdempotencyGuardDep = Annotated[IdempotencyGuard, Depends(get_idempotency_guard)]


async def require_idempotency_key(request: Request, guard: IdempotencyGuardDep) -> IdempotencyGuard:
    """The guard, for a route where a request without a key must not be applied at all."""
    if request.headers.get(IDEMPOTENCY_KEY_HEADER) is None:
        raise MalformedRequest(MISSING_KEY_DETAIL)
    return guard


type KeyedIdempotencyGuardDep = Annotated[IdempotencyGuard, Depends(require_idempotency_key)]
