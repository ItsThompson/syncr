"""The dependencies a route declares, and what they compose.

This is where the perimeter is assembled. Four things are worth reading closely.

**One dependency accepts either credential, and the request chooses which.**
:func:`require_client_principal` resolves a bearer token when the request presents one and the
session cookie otherwise, so a route serving both the browser and the CLI has the same shape as
every other route and no flag decides its behavior. :func:`require_principal` is that same
resolution with a bearer credential then refused, which is what a route the CLI must not reach
declares: the default is closed, and widening it is an edit to one route's signature that
``tests/test_authorization_boundary.py`` enumerates.

The origin check is a sub-dependency of principal resolution rather than a middleware
or a rule each router remembers. The credential this application accepts from a
browser is a cookie, which is ambient: the browser attaches it to a forged
cross-origin request as readily as to a real one. So the check belongs in the one
function that reads that cookie, where it cannot be omitted by a route that forgets
it. Sign-in has no cookie yet and still needs the check, so the auth router declares
it too, and FastAPI resolves it once per request either way.

Resolution binds the tenant onto the logging context, so every subsequent line of the
request carries it without a call site passing it. Both credential kinds pass through the one
function that binds it, so a CLI request's log lines carry what a browser request's do.

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
from syncr_api.core.credentials import CredentialKind, presented_credential
from syncr_api.core.db import get_transaction
from syncr_api.core.errors import OriginRejected, Unauthorized
from syncr_api.core.principal import Principal

# Runtime imports, because FastAPI evaluates this module's dependency annotations while the app is
# being built. ``oauth.injection`` reaches nothing in this module, which is what lets the perimeter
# here reach the bearer resolution there: the consent service, the one thing in that module that
# needed a browser session, lives in ``oauth/consent_injection.py``.
from syncr_api.oauth.injection import resolve_bearer_principal
from syncr_common.logging import bind_tenant_id

if TYPE_CHECKING:
    from syncr_api.core.settings import ServiceSettings

ORIGIN_REJECTED_DETAIL = (
    "This request states an origin this deployment does not serve, so it was not "
    "applied. Nothing was changed. Reading is unaffected."
)

SESSION_REQUIRED_DETAIL = (
    "This route is served to a signed-in browser only, so the access token presented with it "
    "was not accepted and nothing was changed. Everything the CLI ships a command for is "
    "reachable with the token it holds."
)

type TransactionDep = Annotated[AsyncSession, Depends(get_transaction)]


def require_trusted_origin(request: Request) -> None:
    """Reject an unsafe request stating an origin this deployment does not serve.

    **A request presenting a bearer token and no cookie is exempt, and the exemption belongs to the
    credential rather than to a route.** The check is the half of CSRF protection that
    ``SameSite=Lax`` does not cover, and CSRF exists because a cookie is ambient. A bearer token is
    not: a hostile page cannot put a header on a form post at all, and adding one through ``fetch``
    makes the request non-simple, so the browser preflights it and this deployment answers no CORS
    headers. Requiring an origin of a bearer request would instead refuse every CLI mutation, since
    the CLI is not a browser and sends no ``Origin`` header at all. Ticket 6 exempted
    ``/oauth/token`` by route for exactly this reason; stating it once, here, is what keeps a later
    CLI route from needing its own exemption.

    A request carrying a cookie is checked whatever else it carries, so nothing ambient is ever
    unprotected, and a request carrying neither is checked too: sign-in has no cookie yet.
    """
    if (
        presented_credential(request) is CredentialKind.BEARER
        and read_session_token(request) is None
    ):
        return
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


async def require_client_principal(
    request: Request,
    _trusted_origin: TrustedOriginDep,
    transaction: TransactionDep,
    authenticator: AuthenticatorDep,
) -> Principal:
    """Who this request is for, whichever credential it presents, or 401.

    What a route the CLI reaches declares. One dependency rather than two, because a browser
    presents an ambient cookie and the CLI presents a header, and a route that declared both would
    have a shape that depends on its caller. The credential is chosen by what the request presents,
    never by a flag or a query parameter.

    A session carries every scope, because the user is acting directly; a bearer token carries only
    what its grant was issued for. Both answers arrive on the principal, and the service method the
    route delegates to is the one place either is checked.
    """
    if presented_credential(request) is CredentialKind.BEARER:
        return _bind(resolve_bearer_principal(request, transaction))
    return _bind(await authenticator.resolve(require_session_token(request)))


type ClientPrincipalDep = Annotated[Principal, Depends(require_client_principal)]


async def require_principal(principal: ClientPrincipalDep, request: Request) -> Principal:
    """Who this request is for, from a browser session. The only way a browser-only route gets one.

    The same resolution as :func:`require_client_principal` with a bearer credential then refused,
    so the CLI's reach is the set of routes that deliberately declare the other dependency and the
    default for a route added later is closed. Sharing the resolution rather than repeating it is
    also what keeps a browser request to exactly one session read: FastAPI caches a dependency per
    request, and both perimeters are the same one.
    """
    if presented_credential(request) is CredentialKind.BEARER:
        raise Unauthorized(SESSION_REQUIRED_DETAIL)
    return principal


type PrincipalDep = Annotated[Principal, Depends(require_principal)]


def _bind(principal: Principal) -> Principal:
    """Put the resolved tenant on the logging context, for every line the request writes after."""
    bind_tenant_id(str(principal.tenant_id))
    return principal


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
