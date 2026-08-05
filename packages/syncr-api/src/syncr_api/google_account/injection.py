"""The dependencies the Google account routes declare, and the client they share.

The repositories are scoped to the principal's tenant HERE, before the service exists, so the
tenant a statement can reach is fixed by the credential rather than by anything in the request.

**The OAuth credentials come from settings, per request.** They are read off ``app.state.settings``
rather than held in a module global, so a test builds an app with its own client id and a
deployment that sets one needs no code change. An empty client id is a valid state: the service
refuses a connect and names what still works.

**The state secret is derived from the session signing secret**, inside
:mod:`syncr_api.google_account.state`. Rotating that secret therefore invalidates in-flight
connect flows as well as sessions, which is the documented cost of rotating it.

**The HTTP client is per request.** A connect is one call to Google's token endpoint, so pooling
would buy one connection's worth of setup while making the client's lifecycle something the
application has to own. The worker keeps one client per tick for the same reason the calendar
runner does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import httpx
from fastapi import Depends
from starlette.requests import Request  # noqa: TC002

# FastAPI resolves these annotations at RUNTIME to build the dependency graph, so every name
# reachable from one stays a runtime import.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.calendars.repository import CalendarSourceRepository
from syncr_api.core.clock import utc_now
from syncr_api.google_account.config import TOKEN_TIMEOUT_SECONDS
from syncr_api.google_account.crypto import TokenCipher, is_published_key
from syncr_api.google_account.oauth_client import GoogleOAuthClient
from syncr_api.google_account.repository import GoogleCredentialRepository
from syncr_api.google_account.service import GoogleConnectionService
from syncr_api.google_account.tokens import GoogleAccessTokens
from syncr_api.solving.repository import OperationRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

# The one environment where the published key may encrypt a token. Compared here rather than read
# off a settings predicate, because ``ServiceSettings`` deliberately carries the environment's NAME
# and no predicate: one definition of "is development", in the class that produced the value.
DEVELOPMENT = "development"


def may_store_tokens(settings: ServiceSettings) -> bool:
    """Whether this deployment may write a new Google authorization to its database.

    The judgment lives at composition because it reads two things the service should not: the key
    itself, and which environment this is. What the service receives is the answer.

    **It gates STORING and nothing else.** An earlier shape refused to build a cipher at all, which
    put the refusal on the dependency path of every calendar-source route and of the worker's whole
    poll: reading a feed, listing sources and polling every tenant's ICS calendars all answered 503,
    while the message said they still worked. Decrypting an authorization that is already stored is
    unaffected, so an account connected under a real key keeps reading if the key is later replaced
    by the published one, which is what the message now promises.
    """
    key = settings.google_token_encryption_key.get_secret_value()
    return not is_published_key(key) or settings.environment.lower() == DEVELOPMENT


def build_cipher(settings: ServiceSettings) -> TokenCipher:
    """The cipher this deployment reads and writes stored authorizations with.

    Whether a NEW one may be written is :func:`may_store_tokens`, checked by the service at the one
    point that writes: a cipher that refused to exist would take reading down with writing.
    """
    return TokenCipher(settings.google_token_encryption_key.get_secret_value())


def create_google_client() -> httpx.AsyncClient:
    """The client for Google's own endpoints. Redirects are not followed.

    A token endpoint that answered a redirect would be a misrouted request rather than a hop to
    follow, and following one would send a client secret to whatever it named.
    """
    return httpx.AsyncClient(timeout=TOKEN_TIMEOUT_SECONDS, follow_redirects=False)


async def get_google_client() -> AsyncIterator[httpx.AsyncClient]:
    """One HTTP client for the life of one request, closed when it ends."""
    async with create_google_client() as client:
        yield client


type GoogleClientDep = Annotated[httpx.AsyncClient, Depends(get_google_client)]


def build_oauth_client(settings: ServiceSettings, client: httpx.AsyncClient) -> GoogleOAuthClient:
    """The token-endpoint client for this deployment's registered OAuth client."""
    return GoogleOAuthClient(
        client=client,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret.get_secret_value(),
        redirect_uri=settings.google_oauth_redirect_uri,
    )


def build_access_tokens(
    settings: ServiceSettings,
    session: AsyncSession,
    tenant_id: TenantId,
    client: httpx.AsyncClient,
) -> GoogleAccessTokens:
    """One access-token source for one tenant, for the life of one request or one worker tick.

    Composed here rather than in the calendar package, because what turns a stored grant into a
    usable token is this package's concern and the calendar adapter should only be handed the
    result.
    """
    return GoogleAccessTokens(
        credentials=GoogleCredentialRepository(session, tenant_id),
        oauth=build_oauth_client(settings, client),
        cipher=build_cipher(settings),
        clock=utc_now,
    )


async def get_google_connection_service(
    request: Request,
    principal: PrincipalDep,
    transaction: TransactionDep,
    client: GoogleClientDep,
) -> GoogleConnectionService:
    """The Google account service, wired for this request and scoped to this tenant."""
    settings: ServiceSettings = request.app.state.settings
    return GoogleConnectionService(
        credentials=GoogleCredentialRepository(transaction, principal.tenant_id),
        sources=CalendarSourceRepository(transaction, principal.tenant_id),
        operations=OperationRepository(transaction, principal.tenant_id),
        oauth=build_oauth_client(settings, client),
        cipher=build_cipher(settings),
        may_store_tokens=may_store_tokens(settings),
        client_id=settings.google_oauth_client_id,
        redirect_uri=settings.google_oauth_redirect_uri,
        state_secret=settings.session_signing_secret.get_secret_value(),
        clock=utc_now,
    )


type GoogleConnectionServiceDep = Annotated[
    GoogleConnectionService, Depends(get_google_connection_service)
]
