"""Token issuance, refresh with rotation, revocation, and introspection.

None of these methods takes a principal, and that is not an omission. They are what PRODUCES
one: an authorization code and a refresh token are credentials being exchanged, and
introspection turns a presented access token into a principal. Keeping them out of
``service.py`` is what lets the authorization boundary assert its rule over every method in
that file with no exemption list, which is the same split accounts makes for the same reason.

**Rotation, and what a replay means.** Every refresh exchange consumes the presented token
and issues a new one, so a token is a one-time credential. A client that holds a valid
refresh token therefore never has cause to present a consumed one, and if a consumed one
arrives, two parties hold the chain: the legitimate client and whoever copied it. There is no
way to tell which one is presenting it, so neither is trusted and the whole family is
revoked. The user re-authorizes, which costs a browser round trip and reveals the theft.

**That revocation runs in a transaction of its own, and it has to.** The request it happens in
ends by raising, and one request is one unit of work that rolls back on a raise, so a
revocation written into the request's transaction would be undone by the very failure that
provoked it: the family would be logged as revoked and would still be issuing tokens. It is a
second unit of work rather than part of the first, so it gets a second transaction.

**What issuance costs, and why.** Every exchange reads the account's user id to put in the
token's subject, because no scoped table may carry a ``user_id`` and a tenant holds exactly
one user. That is one extra read per exchange and per refresh, neither of which is on a
request path.

**Where the tenant comes from.** A caller cannot name a tenant on this endpoint. The scope is
whatever the presented credential's own row carries, resolved by primary key from the digest
of the secret, and every write after that goes through a repository constructed with that
tenant. So there is no parameter here to authorize and nothing to get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syncr_api.core.scopes import format_scopes
from syncr_api.oauth.config import (
    GRANT_TYPE_AUTHORIZATION_CODE,
    GRANT_TYPE_REFRESH_TOKEN,
    REFRESH_TOKEN_LIFETIME,
    TOKEN_TYPE_BEARER,
)
from syncr_api.oauth.errors import (
    InvalidClient,
    InvalidGrant,
    InvalidRequest,
    InvalidToken,
    UnsupportedGrantType,
    bearer_challenge,
)
from syncr_api.oauth.pkce import verifies
from syncr_api.oauth.secrets import digest_of, mint_refresh_token
from syncr_common.logging import get_logger
from syncr_common.metrics import measured

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime
    from uuid import UUID

    from syncr_api.accounts.repository import UserRepository
    from syncr_api.core.clock import Clock
    from syncr_api.core.principal import Principal
    from syncr_api.core.scopes import Scope
    from syncr_api.oauth.access_tokens import AccessTokenCodec
    from syncr_api.oauth.records import GrantRecord, RefreshTokenRecord
    from syncr_api.oauth.repository import OAuthRepository, PresentedCredentialRepository
    from syncr_domain.identifiers import TenantId, UserId

# The scoped repository takes its tenant at construction, and this endpoint learns the tenant
# only after reading the presented credential, so what is injected is the factory rather than
# an instance. The rule is unchanged: no repository exists without a tenant, and this is what
# constructs one once the tenant is known. A PEP 695 alias is evaluated lazily, so the names in
# it stay type-only imports.
type ScopedRepositoryFactory = Callable[[TenantId], OAuthRepository]

# Revoking a compromised family, in a transaction that is not the request's. Returns how many
# refresh tokens it revoked. Injected rather than reached for, so the service holds no session
# factory and a test can see exactly what it is being asked to do.
type CompromisedFamilyRevoker = Callable[[TenantId, UUID, datetime], Awaitable[int]]

# One rejection for every way an exchange can fail. A caller learns "that credential does
# not work"; which rule caught it is in the log, because the distinction is an operator's
# question and an attacker's too.
EXCHANGE_REJECTION = (
    "That authorization could not be completed, so no token was issued. Nothing was "
    "changed. Start the authorization again."
)

_log = get_logger("syncr.oauth")


@dataclass(frozen=True, slots=True)
class TokenRequest:
    """A token endpoint request, exactly as presented."""

    grant_type: str
    client_id: str
    code: str | None = None
    code_verifier: str | None = None
    redirect_uri: str | None = None
    refresh_token: str | None = None


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """The pair a successful exchange hands back.

    The refresh token appears here and nowhere else: only its digest is stored, so this value
    is the one path from minting it to the response body.
    """

    access_token: str
    refresh_token: str
    expires_in: int
    scopes: frozenset[Scope]

    @property
    def token_type(self) -> str:
        return TOKEN_TYPE_BEARER


class TokenService:
    """The token endpoint's whole behavior, and the bearer credential's resolution."""

    def __init__(
        self,
        credentials: PresentedCredentialRepository,
        for_tenant: ScopedRepositoryFactory,
        revoke_compromised_family: CompromisedFamilyRevoker,
        users: UserRepository,
        codec: AccessTokenCodec,
        clock: Clock,
    ) -> None:
        self._credentials = credentials
        self._for_tenant = for_tenant
        self._revoke_compromised_family = revoke_compromised_family
        self._users = users
        self._codec = codec
        self._clock = clock

    @measured("oauth")
    async def exchange(self, request: TokenRequest) -> IssuedTokens:
        """Issue a token pair for a code, or rotate one for a refresh token.

        The client is resolved first, so a request naming a client this deployment never
        registered is told that rather than being told its credential is bad: the two are
        different problems, and a developer wiring a client hits the first one.
        """
        if await self._credentials.find_client(request.client_id) is None:
            _log.warning("oauth.token.unknown_client", client_id=request.client_id)
            raise InvalidClient(
                "No client is registered under that client_id, so no token was issued. "
                "Nothing was changed."
            )
        if request.grant_type == GRANT_TYPE_AUTHORIZATION_CODE:
            return await self._exchange_code(request)
        if request.grant_type == GRANT_TYPE_REFRESH_TOKEN:
            return await self._rotate(request)
        raise UnsupportedGrantType(
            f"grant_type must be {GRANT_TYPE_AUTHORIZATION_CODE} or "
            f"{GRANT_TYPE_REFRESH_TOKEN}. Nothing was changed."
        )

    @measured("oauth")
    async def revoke(self, presented: str, client_id: str) -> None:
        """Revoke a refresh token and its family, server-side.

        Answers the same way whether the token existed, belonged to this client, or was
        already revoked. RFC 7009 requires that, and the reason is that any other behavior
        turns this endpoint into an oracle for whether a token is live.
        """
        token = await self._credentials.find_refresh_token(digest_of(presented))
        if token is None:
            _log.info("oauth.revoke.unknown", client_id=client_id)
            return
        grant = await self._credentials.find_grant(token.grant_id)
        if grant is None or grant.client_id != client_id:
            _log.info("oauth.revoke.mismatched", client_id=client_id)
            return
        revoked = await self._for_tenant(token.tenant_id).revoke_family(
            token.grant_id, self._clock()
        )
        _log.info(
            "oauth.revoke.completed",
            tenant_id=str(token.tenant_id),
            client_id=client_id,
            revoked_count=revoked,
        )

    def introspect(self, presented: str) -> Principal:
        """The principal a presented access token authenticates. Raises 401 otherwise.

        No database read, deliberately. The token is a signed claim set naming its tenant,
        its subject, and its scopes, and verifying it is arithmetic; the cost of that is
        that revoking a grant does not reach an access token already issued, which is why
        the access lifetime is minutes rather than days.

        Not decorated with a metric. It runs on every bearer request, and a histogram
        observation per request would measure signature verification while adding the only
        latency worth measuring here.
        """
        principal = self._codec.verify(presented, at=self._clock())
        if principal is None:
            _log.warning("oauth.bearer.rejected")
            raise InvalidToken(
                "That access token is not valid for this API, so the request was not "
                "applied. Nothing was changed. Refresh it, or sign in again.",
                headers=bearer_challenge(),
            )
        return principal

    async def _exchange_code(self, request: TokenRequest) -> IssuedTokens:
        if not request.code or not request.code_verifier or not request.redirect_uri:
            raise InvalidRequest(
                "code, code_verifier, and redirect_uri are all required to exchange an "
                "authorization code. Nothing was changed."
            )
        code = await self._credentials.find_code(digest_of(request.code))
        now = self._clock()
        if code is None:
            raise self._rejected("unknown_code", client_id=request.client_id)
        if not code.is_redeemable_at(now):
            # A consumed code arriving again is a replay: either the client retried after a
            # response it did not see, or someone else holds it. Both are answered by
            # refusing, and the reason separates them in the log.
            raise self._rejected(
                "consumed_code" if code.consumed_at else "expired_code",
                client_id=request.client_id,
                tenant_id=code.tenant_id,
            )
        if code.client_id != request.client_id:
            raise self._rejected("client_mismatch", client_id=request.client_id)
        # RFC 6749 section 4.1.3 makes this REQUIRED whenever the authorize request carried
        # one, and no path through `GET /oauth/authorize` omits it. Compared rather than
        # optionally compared, so a caller cannot skip the check by dropping the parameter.
        if request.redirect_uri != code.redirect_uri:
            raise self._rejected("redirect_mismatch", client_id=request.client_id)
        if not verifies(request.code_verifier, code.code_challenge):
            raise self._rejected("pkce_failed", client_id=request.client_id)

        scoped = self._for_tenant(code.tenant_id)
        if not await scoped.consume_code(code.id, now):
            # Lost a race with a simultaneous exchange of the same code. The winner holds the
            # tokens; this caller gets the same answer a replay gets.
            raise self._rejected("consumed_code", client_id=request.client_id)

        grant = await scoped.find_grant_for_client(code.client_id)
        if grant is None or not grant.is_live:
            raise self._rejected("grant_revoked", client_id=request.client_id)
        issued = await self._issue(scoped, grant, code.scopes, now)
        _log.info(
            "oauth.token.issued",
            tenant_id=str(code.tenant_id),
            client_id=code.client_id,
            grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
            granted_scopes=format_scopes(code.scopes),
        )
        return issued

    async def _rotate(self, request: TokenRequest) -> IssuedTokens:
        if not request.refresh_token:
            raise InvalidRequest("refresh_token is required to refresh. Nothing was changed.")
        presented = await self._credentials.find_refresh_token(digest_of(request.refresh_token))
        now = self._clock()
        if presented is None:
            raise self._rejected("unknown_refresh_token", client_id=request.client_id)
        grant = await self._credentials.find_grant(presented.grant_id)
        if grant is None or grant.client_id != request.client_id:
            raise self._rejected(
                "client_mismatch", client_id=request.client_id, tenant_id=presented.tenant_id
            )
        scoped = self._for_tenant(presented.tenant_id)
        if presented.was_used:
            await self._revoke_replayed_family(presented, request.client_id, now)
            raise self._rejected(
                "refresh_replayed", client_id=request.client_id, tenant_id=presented.tenant_id
            )
        if not presented.is_exchangeable_at(now):
            raise self._rejected(
                "expired_or_revoked_refresh_token",
                client_id=request.client_id,
                tenant_id=presented.tenant_id,
            )
        if not grant.is_live:
            raise self._rejected(
                "grant_revoked", client_id=request.client_id, tenant_id=presented.tenant_id
            )
        if not await scoped.consume_refresh_token(presented.id, now):
            # Two refreshes with one token arrived together. Exactly one consumed it, and the
            # loser is indistinguishable from a replay, so it is treated as one.
            await self._revoke_replayed_family(presented, request.client_id, now)
            raise self._rejected(
                "refresh_replayed", client_id=request.client_id, tenant_id=presented.tenant_id
            )

        issued = await self._issue(scoped, grant, presented.scopes, now)
        _log.info(
            "oauth.token.refreshed",
            tenant_id=str(presented.tenant_id),
            client_id=grant.client_id,
            grant_type=GRANT_TYPE_REFRESH_TOKEN,
            granted_scopes=format_scopes(presented.scopes),
        )
        return issued

    async def _issue(
        self,
        scoped: OAuthRepository,
        grant: GrantRecord,
        scopes: frozenset[Scope],
        now: datetime,
    ) -> IssuedTokens:
        """Mint the pair: a signed access token, and a stored-by-digest refresh token."""
        access = self._codec.mint(
            tenant_id=grant.tenant_id,
            user_id=await self._account_user_id(grant),
            client_id=grant.client_id,
            scopes=scopes,
            issued_at=now,
        )
        refresh = mint_refresh_token()
        await scoped.create_refresh_token(
            token_id=digest_of(refresh),
            grant_id=grant.id,
            scopes=scopes,
            created_at=now,
            expires_at=now + REFRESH_TOKEN_LIFETIME,
        )
        return IssuedTokens(
            access_token=access.token,
            refresh_token=refresh,
            expires_in=access.expires_in,
            scopes=scopes,
        )

    async def _account_user_id(self, grant: GrantRecord) -> UserId:
        """The one user this tenant holds, for the access token's subject."""
        user = await self._users.find_by_tenant(grant.tenant_id)
        if user is None:
            # A grant exists for a tenant with no user. The foreign key makes that
            # unreachable while the tenant exists, so reaching it means the account was
            # removed mid-exchange, and minting a token for a subject that is gone would be
            # worse than refusing.
            raise self._rejected("no_account", client_id=grant.client_id, tenant_id=grant.tenant_id)
        return user.id

    async def _revoke_replayed_family(
        self, token: RefreshTokenRecord, client_id: str, now: datetime
    ) -> None:
        """End a family whose token was presented twice, outside this request's transaction."""
        revoked = await self._revoke_compromised_family(token.tenant_id, token.grant_id, now)
        _log.warning(
            "oauth.refresh.replay_detected",
            tenant_id=str(token.tenant_id),
            client_id=client_id,
            grant_id=str(token.grant_id),
            revoked_count=revoked,
        )

    @staticmethod
    def _rejected(
        reason: str, *, client_id: str, tenant_id: TenantId | None = None
    ) -> InvalidGrant:
        _log.warning(
            "oauth.token.rejected",
            reason=reason,
            client_id=client_id,
            tenant_id=str(tenant_id) if tenant_id else None,
        )
        return InvalidGrant(EXCHANGE_REJECTION)
