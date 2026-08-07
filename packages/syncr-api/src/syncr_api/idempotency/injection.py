"""The two dependencies a route with an unsafe method declares.

``IdempotencyGuardDep`` accepts a key and works without one: the header is offered on every
unsafe method rather than demanded, and a caller that wants the guarantee sends one.
``KeyedIdempotencyGuardDep`` refuses the request when the header is absent, for the routes
where a repeat would be unrecoverable: approving a proposal twice would append two revisions,
and there is no unapprove.

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
    ClientPrincipalDep,
    TransactionDep,
)
from syncr_api.core.clock import utc_now
from syncr_api.core.errors import MalformedRequest
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER, KEY_MAX_LENGTH
from syncr_api.idempotency.fingerprints import request_fingerprint
from syncr_api.idempotency.guard import IdempotencyGuard
from syncr_api.idempotency.repository import IdempotencyKeyRepository

MISSING_KEY_DETAIL = (
    f"This request needs an {IDEMPOTENCY_KEY_HEADER} header, so a retry cannot apply it "
    "twice. Nothing was changed. Resend it with a unique key."
)
OVERSIZE_KEY_DETAIL = (
    f"An {IDEMPOTENCY_KEY_HEADER} may be at most {KEY_MAX_LENGTH} characters. Nothing was "
    "changed. Resend the request with a shorter key, such as a UUID or a ULID."
)
BLANK_KEY_DETAIL = (
    f"The {IDEMPOTENCY_KEY_HEADER} header carries no value. Nothing was changed. Send a key "
    "that identifies this request, such as a UUID or a ULID, or omit the header entirely."
)


async def get_idempotency_guard(
    request: Request, transaction: TransactionDep, principal: ClientPrincipalDep
) -> IdempotencyGuard:
    """The guard for this request, scoped to the caller's tenant.

    Both ends of the key's bound are checked here, where the header is read, so the two
    dependencies below inherit them. A key wider than the primary key holds would fail in the
    driver on the way to storing it. An empty header is worse than that, because it succeeds:
    ``""`` is not absent, so it would become a real key that every request with the same bug
    shares, and the second such request would either be refused as a key the client does not
    believe it sent, or silently replay the first one's response. Both are a caller error, so
    both are a 400 naming the remedy.
    """
    key = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if key is not None:
        if not key.strip():
            raise MalformedRequest(BLANK_KEY_DETAIL)
        if len(key) > KEY_MAX_LENGTH:
            raise MalformedRequest(OVERSIZE_KEY_DETAIL)
    return IdempotencyGuard(
        IdempotencyKeyRepository(transaction, principal.tenant_id),
        key=key,
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
