"""The dependencies the Authorization Server's routes declare.

Four things are worth reading closely.

**The consent routes resolve a BROWSER session**, through the accounts dependency that reads
the cookie, and they inherit that dependency's origin check with it. A bearer credential
deliberately cannot reach them: a client holding an access token must not be able to mint
itself a fresh grant, because it could then widen its own scopes or outlive its own
revocation.

**The consent service's repository is scoped by the session's tenant**, resolved before the
service exists. So the tenant it can reach is fixed by the credential rather than by anything
in the request, and the principal the service method takes is checked against that same
answer.

**The token and revocation endpoints resolve nothing.** They are what produces a credential,
so requiring one would make obtaining a token possible only while already holding one. The
allowlist in ``tests/test_authorization_boundary.py`` names them and says why.

**The signing key set is process-wide state on ``app.state.oauth``**, attached by the
entrypoint exactly as the database is. It is read once, at startup, so a malformed or
undecryptable key file fails the boot rather than the first request, and a rotation takes
effect on a restart rather than mid-process.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

# FastAPI resolves a dependency's annotations at RUNTIME to build the dependency graph, and a
# `type` alias is evaluated when it does, so every name reachable from an annotation below
# stays a runtime import: under TYPE_CHECKING it would resolve to a NameError while the app is
# being constructed.
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request  # noqa: TC002

# `PrincipalDep` stays a runtime import for the same reason: FastAPI evaluates the annotations
# of the dependency below to build its graph.
from syncr_api.accounts.injection import PrincipalDep  # noqa: TC001
from syncr_api.accounts.repository import UserRepository
from syncr_api.core.clock import utc_now
from syncr_api.core.db import Database, get_transaction
from syncr_api.core.principal import Principal
from syncr_api.oauth.access_tokens import AccessTokenCodec
from syncr_api.oauth.config import BEARER_SCHEME, OAuthConfig
from syncr_api.oauth.errors import InvalidToken, bearer_challenge
from syncr_api.oauth.repository import OAuthRepository, PresentedCredentialRepository
from syncr_api.oauth.service import AuthorizationService
from syncr_api.oauth.tokens import CompromisedFamilyRevoker, ScopedRepositoryFactory, TokenService

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from syncr_api.oauth.keys import SigningKeySet
    from syncr_domain.identifiers import TenantId

AUTHORIZATION_HEADER = "authorization"

MISSING_BEARER_DETAIL = (
    "This route needs an access token. Present one as `Authorization: Bearer <token>`. "
    "Nothing was changed."
)

# What a request to an OAuth route says when the entrypoint never attached the state. Named
# rather than generic, because the fix is one line in whichever process built the app.
_UNWIRED = (
    "app.state.oauth is not set, so this application has OAuth routes and no signing keys. "
    "Attach it with syncr_api.oauth.injection.build_oauth_state, the way the api entrypoint "
    "does."
)

type TransactionDep = Annotated[AsyncSession, Depends(get_transaction)]


@dataclass(frozen=True, slots=True)
class OAuthState:
    """The Authorization Server's process-wide state, carried on ``app.state.oauth``."""

    config: OAuthConfig
    keys: SigningKeySet
    codec: AccessTokenCodec


def build_oauth_state(config: OAuthConfig, keys: SigningKeySet) -> OAuthState:
    """Compose the process-wide OAuth state from its configuration and key set."""
    return OAuthState(
        config=config,
        keys=keys,
        codec=AccessTokenCodec(keys, issuer=config.issuer, audience=config.audience),
    )


def get_oauth_state(request: Request) -> OAuthState:
    """The Authorization Server state this application was built with."""
    state: OAuthState | None = getattr(request.app.state, "oauth", None)
    if state is None:
        raise RuntimeError(_UNWIRED)
    return state


type OAuthStateDep = Annotated[OAuthState, Depends(get_oauth_state)]


def get_authorization_service(
    transaction: TransactionDep, principal: PrincipalDep
) -> AuthorizationService:
    """The consent service, wired for this request and scoped to the signed-in tenant."""
    return AuthorizationService(
        clients=PresentedCredentialRepository(transaction),
        grants=OAuthRepository(transaction, principal.tenant_id),
        users=UserRepository(transaction),
        clock=utc_now,
    )


type AuthorizationServiceDep = Annotated[AuthorizationService, Depends(get_authorization_service)]


def get_token_service(
    request: Request, transaction: TransactionDep, state: OAuthStateDep
) -> TokenService:
    """The token service, wired for this request."""
    database: Database = request.app.state.db
    return TokenService(
        credentials=PresentedCredentialRepository(transaction),
        for_tenant=scoped_repository_factory(transaction),
        revoke_compromised_family=independent_family_revoker(database.sessionmaker),
        users=UserRepository(transaction),
        codec=state.codec,
        clock=utc_now,
    )


type TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]


def independent_family_revoker(
    sessions: async_sessionmaker[AsyncSession],
) -> CompromisedFamilyRevoker:
    """Revoke a compromised grant family in a transaction that is not the request's.

    The request that detects a replayed refresh token ends by raising, and one request is one
    unit of work that rolls back on a raise. A revocation written into that transaction would
    therefore be undone by the failure that provoked it, which is the difference between a
    replay defense and a log line claiming there was one.
    """

    async def revoke(tenant_id: TenantId, grant_id: UUID, at: datetime) -> int:
        async with sessions() as session, session.begin():
            return await OAuthRepository(session, tenant_id).revoke_family(grant_id, at)

    return revoke


def scoped_repository_factory(transaction: AsyncSession) -> ScopedRepositoryFactory:
    """Builds a tenant-scoped repository once the presented credential names its tenant.

    The token endpoint cannot be handed a scoped repository, because the tenant is not known
    until the presented code or refresh token has been read. The rule the base enforces is
    unchanged: this is the only way one is constructed, and it takes the tenant to do it.
    """

    def for_tenant(tenant_id: TenantId) -> OAuthRepository:
        return OAuthRepository(transaction, tenant_id)

    return for_tenant


def require_bearer_principal(request: Request, service: TokenServiceDep) -> Principal:
    """The principal a presented access token authenticates, or 401.

    What a route serving the CLI declares. It resolves the subject, the tenant, and the scopes
    the grant was issued for; the service method the route delegates to is where those scopes
    are then checked, which is why nothing is checked here.
    """
    presented = read_bearer_token(request)
    if presented is None:
        raise InvalidToken(MISSING_BEARER_DETAIL, headers=bearer_challenge())
    return service.introspect(presented)


type BearerPrincipalDep = Annotated[Principal, Depends(require_bearer_principal)]


def read_bearer_token(request: Request) -> str | None:
    """The token this request presented in its ``Authorization`` header, or ``None``.

    The scheme is compared case-insensitively, because RFC 7235 says it is and a client that
    sends ``bearer`` is not wrong.
    """
    header = request.headers.get(AUTHORIZATION_HEADER)
    if header is None:
        return None
    scheme, _, credential = header.partition(" ")
    if scheme.lower() != BEARER_SCHEME or not credential.strip():
        return None
    return credential.strip()
