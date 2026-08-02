"""The dependencies a route declares, and what they compose.

This is where the perimeter is assembled. Three things are worth reading closely.

The origin check is a sub-dependency of principal resolution rather than a middleware
or a rule each router remembers. The credential this application accepts from a
browser is a cookie, which is ambient: the browser attaches it to a forged
cross-origin request as readily as to a real one. So the check belongs in the one
function that reads that cookie, where it cannot be omitted by a route that forgets
it. Sign-in has no cookie yet and still needs the check, so the auth router declares
it too, and FastAPI resolves it once per request either way.

Resolution binds the tenant onto the logging context, so every subsequent line of the
request carries it without a call site passing it.

Nothing here holds state between requests. The signing secret is read from
``app.state.settings`` per request, so a test can build an app with a different one
without reaching into a module global.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

# FastAPI resolves a dependency's annotations at RUNTIME to build the dependency
# graph, and a `type` alias is evaluated when it does. So every name reachable from an
# annotation below stays a runtime import: under `TYPE_CHECKING` it would resolve to a
# NameError while the app is being constructed.
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request  # noqa: TC002

from syncr_api.accounts.authentication import REJECTION_DETAIL, Authenticator
from syncr_api.accounts.cookies import read_session_token
from syncr_api.accounts.origin import is_origin_trusted
from syncr_api.accounts.repository import SessionRepository, UserRepository
from syncr_api.accounts.service import SessionService
from syncr_api.accounts.session_tokens import (
    SessionId,
    SessionToken,
    TokenDigest,
    make_token_digest,
)
from syncr_api.core.clock import utc_now
from syncr_api.core.db import get_transaction
from syncr_api.core.errors import OriginRejected, Unauthorized
from syncr_api.core.principal import Principal
from syncr_common.logging import bind_tenant_id

if TYPE_CHECKING:
    from syncr_api.core.settings import ServiceSettings

ORIGIN_REJECTED_DETAIL = (
    "This request states an origin this deployment does not serve, so it was not "
    "applied. Nothing was changed. Reading is unaffected."
)

type TransactionDep = Annotated[AsyncSession, Depends(get_transaction)]


def require_trusted_origin(request: Request) -> None:
    """Reject an unsafe request stating an origin this deployment does not serve."""
    settings: ServiceSettings = request.app.state.settings
    trusted = is_origin_trusted(
        request.method,
        origin=request.headers.get("origin"),
        referer=request.headers.get("referer"),
        allowed=settings.allowed_origins,
    )
    if not trusted:
        raise OriginRejected(ORIGIN_REJECTED_DETAIL)


type TrustedOriginDep = Annotated[None, Depends(require_trusted_origin)]


def require_session_token(request: Request) -> SessionToken:
    """The token the request presented, or 401."""
    token = read_session_token(request)
    if token is None:
        raise Unauthorized(REJECTION_DETAIL)
    return token


type SessionTokenDep = Annotated[SessionToken, Depends(require_session_token)]


def get_token_digest(request: Request) -> TokenDigest:
    """The token-to-row-id function for this deployment's signing secret.

    One owner of that derivation per request. Both the authenticator and the session-id
    dependency take it from here, so the secret is read and the function built once, and
    there is a single place the row id is derived from a token.
    """
    settings: ServiceSettings = request.app.state.settings
    return make_token_digest(settings.session_signing_secret.get_secret_value())


type TokenDigestDep = Annotated[TokenDigest, Depends(get_token_digest)]


def get_authenticator(transaction: TransactionDep, digest: TokenDigestDep) -> Authenticator:
    """The sign-in and cookie-resolution collaborator, wired for this request."""
    return Authenticator(
        users=UserRepository(transaction),
        sessions=SessionRepository(transaction),
        digest=digest,
        clock=utc_now,
    )


type AuthenticatorDep = Annotated[Authenticator, Depends(get_authenticator)]


async def require_principal(
    _trusted_origin: TrustedOriginDep,
    token: SessionTokenDep,
    authenticator: AuthenticatorDep,
) -> Principal:
    """Who this request is for, or 401. The only way a route obtains a principal."""
    principal = await authenticator.resolve(token)
    bind_tenant_id(str(principal.tenant_id))
    return principal


type PrincipalDep = Annotated[Principal, Depends(require_principal)]


def require_session_id(token: SessionTokenDep, digest: TokenDigestDep) -> SessionId:
    """The row id of the presented session, which is the token's keyed digest."""
    return digest(token)


type SessionIdDep = Annotated[SessionId, Depends(require_session_id)]


def get_session_service(transaction: TransactionDep) -> SessionService:
    """The session service, wired for this request."""
    return SessionService(
        sessions=SessionRepository(transaction),
        users=UserRepository(transaction),
        clock=utc_now,
    )


type SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
