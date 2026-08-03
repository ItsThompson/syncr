"""The Authorization Server's services, against fakes and an injected clock.

The repositories are replaced and the clock is moved, so expiry is reached without waiting for
it. Everything else is real: the PKCE transform, the code and token minting, the digesting, the
signing, the scope arithmetic, and the redirect construction all run exactly as they do in
production, because those are the parts that would be wrong silently.

The tests worth reading are the four replay ones. A consumed code refused, a consumed refresh
token taking its whole family down, a lost race treated as a replay, and a scope a token does
not carry refused at the service boundary.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from syncr_api.accounts.records import UserRecord
from syncr_api.accounts.repository import UserRepository
from syncr_api.core.errors import Forbidden, NotFound
from syncr_api.core.principal import Principal, require_scope
from syncr_api.core.scopes import ALL_SCOPES, Scope, format_scopes, parse_scopes
from syncr_api.oauth.access_tokens import AccessTokenCodec
from syncr_api.oauth.authorization import (
    AuthorizeParams,
    ConsentScreen,
    RedirectedError,
    RedirectedRejection,
)
from syncr_api.oauth.config import (
    ACCESS_TOKEN_LIFETIME,
    AUTHORIZATION_CODE_LIFETIME,
    CLI_CLIENT_ID,
    CLI_CLIENT_NAME,
    CLI_CLIENT_SCOPES,
    CLI_REDIRECT_URIS,
    DEAD_GRANT_RETENTION,
    GRANT_TYPE_AUTHORIZATION_CODE,
    GRANT_TYPE_REFRESH_TOKEN,
    REFRESH_TOKEN_LIFETIME,
)
from syncr_api.oauth.errors import InvalidClient, InvalidGrant, InvalidRequest, UnsupportedGrantType
from syncr_api.oauth.keys import SigningKeySet, generate_signing_key
from syncr_api.oauth.pkce import CHALLENGE_LENGTH, derive_s256_challenge
from syncr_api.oauth.records import (
    AuthorizationCodeRecord,
    ClientRecord,
    GrantRecord,
    RefreshTokenRecord,
)
from syncr_api.oauth.repository import OAuthRepository, PresentedCredentialRepository
from syncr_api.oauth.secrets import digest_of
from syncr_api.oauth.service import AuthorizationService
from syncr_api.oauth.tokens import TokenRequest, TokenService

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from syncr_domain.identifiers import TenantId, UserId


class _Expirable(Protocol):
    """What the sweep's row removal needs of a row: a tenant to be scoped by."""

    @property
    def tenant_id(self) -> TenantId: ...


START = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
ISSUER = "https://syncr.example"
AUDIENCE = "https://syncr.example/api/v1"

# RFC 7636 appendix B's published verifier, so it is a specification value and not a secret.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # pragma: allowlist secret
CHALLENGE = derive_s256_challenge(VERIFIER)
LOOPBACK = "http://127.0.0.1:54321/callback"
EMAIL = "owner@syncr.test"
REQUESTED = frozenset({Scope.PLAN_READ, Scope.PLAN_WRITE})


class MovableClock:
    """A clock a test advances, so an expiry is reached without waiting for it."""

    def __init__(self, at: datetime) -> None:
        self.now = at

    def __call__(self) -> datetime:
        return self.now

    def advance(self, by: timedelta) -> None:
        self.now += by


class FakeCredentials(PresentedCredentialRepository):
    """The presented-credential reads, over dicts shared with the scoped fake."""

    def __init__(self, store: Store) -> None:
        self._store = store

    async def find_client(self, client_id: str) -> ClientRecord | None:
        return self._store.clients.get(client_id)

    async def find_code(self, code_id: str) -> AuthorizationCodeRecord | None:
        return self._store.codes.get(code_id)

    async def find_refresh_token(self, token_id: str) -> RefreshTokenRecord | None:
        return self._store.refresh_tokens.get(token_id)

    async def find_grant(self, grant_id: UUID) -> GrantRecord | None:
        return self._store.grants.get(grant_id)


class FakeScoped(OAuthRepository):
    """The scoped writes, over the same dicts, refusing to touch another tenant's rows.

    The refusal is the point: a fake that ignored the scope would let a scoping bug pass a
    service test and only fail in the integration tier.
    """

    def __init__(self, store: Store, tenant_id: TenantId) -> None:
        self._store = store
        self._tenant = tenant_id

    @property
    def tenant_id(self) -> TenantId:
        return self._tenant

    async def create_code(
        self,
        *,
        code_id: str,
        client_id: str,
        redirect_uri: str,
        scopes: frozenset[Scope],
        code_challenge: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._store.codes[code_id] = AuthorizationCodeRecord(
            id=code_id,
            tenant_id=self._tenant,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            code_challenge=code_challenge,
            created_at=created_at,
            expires_at=expires_at,
            consumed_at=None,
        )

    async def consume_code(self, code_id: str, at: datetime) -> bool:
        existing = self._store.codes.get(code_id)
        if existing is None or existing.tenant_id != self._tenant or existing.consumed_at:
            return False
        self._store.codes[code_id] = _replace(existing, consumed_at=at)
        return True

    async def upsert_grant(
        self, *, client_id: str, scopes: frozenset[Scope], at: datetime
    ) -> GrantRecord:
        existing = next(
            (
                grant
                for grant in self._store.grants.values()
                if grant.tenant_id == self._tenant and grant.client_id == client_id
            ),
            None,
        )
        grant = GrantRecord(
            id=existing.id if existing else uuid4(),
            tenant_id=self._tenant,
            client_id=client_id,
            scopes=scopes,
            authorized_at=at,
            revoked_at=None,
        )
        self._store.grants[grant.id] = grant
        return grant

    async def find_grant_for_client(self, client_id: str) -> GrantRecord | None:
        return next(
            (
                grant
                for grant in self._store.grants.values()
                if grant.tenant_id == self._tenant and grant.client_id == client_id
            ),
            None,
        )

    async def create_refresh_token(
        self,
        *,
        token_id: str,
        grant_id: UUID,
        scopes: frozenset[Scope],
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._store.refresh_tokens[token_id] = RefreshTokenRecord(
            id=token_id,
            tenant_id=self._tenant,
            grant_id=grant_id,
            scopes=scopes,
            created_at=created_at,
            expires_at=expires_at,
            consumed_at=None,
            revoked_at=None,
        )

    async def consume_refresh_token(self, token_id: str, at: datetime) -> bool:
        existing = self._store.refresh_tokens.get(token_id)
        if existing is None or existing.tenant_id != self._tenant:
            return False
        if existing.consumed_at or existing.revoked_at:
            return False
        self._store.refresh_tokens[token_id] = _replace(existing, consumed_at=at)
        return True

    async def revoke_family(self, grant_id: UUID, at: datetime) -> int:
        revoked = 0
        for token_id, token in list(self._store.refresh_tokens.items()):
            if token.grant_id != grant_id or token.tenant_id != self._tenant or token.revoked_at:
                continue
            self._store.refresh_tokens[token_id] = _replace(token, revoked_at=at)
            revoked += 1
        grant = self._store.grants.get(grant_id)
        if grant is not None and grant.tenant_id == self._tenant and grant.revoked_at is None:
            self._store.grants[grant_id] = _replace(grant, revoked_at=at)
        return revoked

    async def delete_expired_codes(self, before: datetime) -> int:
        return self._remove(self._store.codes, lambda row: row.expires_at < before)

    async def delete_expired_refresh_tokens(self, before: datetime) -> int:
        return self._remove(self._store.refresh_tokens, lambda row: row.expires_at < before)

    async def delete_grants_revoked_before(self, before: datetime) -> int:
        return self._remove(
            self._store.grants,
            lambda row: row.revoked_at is not None and row.revoked_at < before,
        )

    def _remove[RowT: _Expirable](
        self, rows: dict[Any, RowT], matches: Callable[[RowT], bool]
    ) -> int:
        doomed = [
            key for key, row in rows.items() if row.tenant_id == self._tenant and matches(row)
        ]
        for key in doomed:
            del rows[key]
        return len(doomed)


class FakeUsers(UserRepository):
    """The two user reads the OAuth flow needs, over a dict."""

    def __init__(self, users: list[UserRecord]) -> None:
        self._by_id = {user.id: user for user in users}
        self._by_tenant = {user.tenant_id: user for user in users}

    async def find(self, user_id: UserId) -> UserRecord | None:
        return self._by_id.get(user_id)

    async def find_by_tenant(self, tenant_id: TenantId) -> UserRecord | None:
        return self._by_tenant.get(tenant_id)


class Store:
    """The rows both fakes share, so a write by one is a read by the other."""

    def __init__(self, client: ClientRecord) -> None:
        self.clients: dict[str, ClientRecord] = {client.id: client}
        self.codes: dict[str, AuthorizationCodeRecord] = {}
        self.grants: dict[UUID, GrantRecord] = {}
        self.refresh_tokens: dict[str, RefreshTokenRecord] = {}


def _replace[RecordT](record: RecordT, **changes: object) -> RecordT:
    """One of the frozen records, with some fields replaced."""
    return replace(record, **changes)  # type: ignore[type-var]


@pytest.fixture
def cli_client() -> ClientRecord:
    return ClientRecord(
        id=CLI_CLIENT_ID,
        name=CLI_CLIENT_NAME,
        redirect_uris=CLI_REDIRECT_URIS,
        allowed_scopes=CLI_CLIENT_SCOPES,
        loopback_only=True,
    )


@pytest.fixture
def owner() -> UserRecord:
    return UserRecord(id=uuid4(), tenant_id=uuid4(), email=EMAIL, password_hash="not-verified-here")


@pytest.fixture
def principal(owner: UserRecord) -> Principal:
    return Principal(tenant_id=owner.tenant_id, user_id=owner.id, scopes=ALL_SCOPES)


@pytest.fixture
def store(cli_client: ClientRecord) -> Store:
    return Store(cli_client)


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock(START)


@pytest.fixture
def consent(store: Store, owner: UserRecord, clock: MovableClock) -> AuthorizationService:
    return AuthorizationService(
        clients=FakeCredentials(store),
        grants=FakeScoped(store, owner.tenant_id),
        users=FakeUsers([owner]),
        clock=clock,
    )


@pytest.fixture
def codec() -> AccessTokenCodec:
    return AccessTokenCodec(
        SigningKeySet(current=generate_signing_key("test")), issuer=ISSUER, audience=AUDIENCE
    )


@pytest.fixture
def tokens(
    store: Store, owner: UserRecord, codec: AccessTokenCodec, clock: MovableClock
) -> TokenService:
    async def revoke_independently(tenant_id: TenantId, grant_id: UUID, at: datetime) -> int:
        # Stands in for the second transaction. The fake store has no transaction to be rolled
        # back, so what this proves is that the service asks for the revocation; the integration
        # tier is where it is proven to SURVIVE the raise.
        return await FakeScoped(store, tenant_id).revoke_family(grant_id, at)

    return TokenService(
        credentials=FakeCredentials(store),
        for_tenant=lambda tenant_id: FakeScoped(store, tenant_id),
        revoke_compromised_family=revoke_independently,
        users=FakeUsers([owner]),
        codec=codec,
        clock=clock,
    )


def params(**overrides: str | None) -> AuthorizeParams:
    values: dict[str, str | None] = {
        "client_id": CLI_CLIENT_ID,
        "redirect_uri": LOOPBACK,
        "response_type": "code",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "scope": format_scopes(REQUESTED),
        "state": "opaque-client-state",
    }
    values.update(overrides)
    return AuthorizeParams(**values)  # type: ignore[arg-type]


def query_of(url: str) -> dict[str, str]:
    return {key: value[0] for key, value in parse_qs(urlsplit(url).query).items()}


async def granted_code(consent: AuthorizationService, principal: Principal) -> str:
    outcome = await consent.decide(principal, params(), approved=True)
    return query_of(outcome.url)["code"]


# --- Consent -------------------------------------------------------------------------


async def test_the_consent_screen_names_every_requested_scope(
    consent: AuthorizationService, principal: Principal
) -> None:
    # The rule the whole flow rests on: a user cannot consent to authority nobody stated.
    screen = await consent.describe_consent(principal, params())

    assert isinstance(screen, ConsentScreen)
    assert set(screen.scope_names) == {scope.value for scope in REQUESTED}
    assert screen.client_name == CLI_CLIENT_NAME
    assert screen.account_email == EMAIL
    for scope in screen.scopes:
        assert scope.description, f"{scope.name} is named but not explained"


async def test_the_consent_screen_names_a_single_requested_scope_and_no_others(
    consent: AuthorizationService, principal: Principal
) -> None:
    # The control for the assertion above: a screen that listed every scope the client MAY
    # hold, rather than the ones it asked for, would pass that test and fail this one.
    screen = await consent.describe_consent(principal, params(scope=Scope.PLAN_READ.value))

    assert isinstance(screen, ConsentScreen)
    assert screen.scope_names == (Scope.PLAN_READ.value,)


async def test_the_scopes_are_listed_least_authority_first(
    consent: AuthorizationService, principal: Principal
) -> None:
    screen = await consent.describe_consent(principal, params(scope="plan:write plan:read"))

    assert isinstance(screen, ConsentScreen)
    assert screen.scope_names == (Scope.PLAN_READ.value, Scope.PLAN_WRITE.value)


async def test_an_unknown_client_is_refused_and_not_redirected(
    consent: AuthorizationService, principal: Principal
) -> None:
    with pytest.raises(InvalidClient):
        await consent.describe_consent(principal, params(client_id="somebody-elses-cli"))


async def test_an_unregistered_redirect_is_refused_and_not_redirected(
    consent: AuthorizationService, principal: Principal
) -> None:
    # Bouncing the browser to an attacker-supplied URI to report the error would make the
    # error report the attack.
    with pytest.raises(InvalidRequest, match="not registered"):
        await consent.describe_consent(
            principal, params(redirect_uri="https://attacker.example/callback")
        )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"code_challenge_method": "plain"}, RedirectedError.INVALID_REQUEST),
        ({"code_challenge_method": ""}, RedirectedError.INVALID_REQUEST),
        ({"code_challenge": ""}, RedirectedError.INVALID_REQUEST),
        ({"code_challenge": "Á" * CHALLENGE_LENGTH}, RedirectedError.INVALID_REQUEST),
        ({"response_type": "token"}, RedirectedError.UNSUPPORTED_RESPONSE_TYPE),
        ({"scope": "admin"}, RedirectedError.INVALID_SCOPE),
        ({"scope": "plan:everything"}, RedirectedError.INVALID_SCOPE),
        ({"scope": ""}, RedirectedError.INVALID_SCOPE),
    ],
    ids=[
        "plain pkce",
        "absent pkce method",
        "absent challenge",
        "a right-length non-ascii challenge",
        "implicit flow",
        "a scope the cli may not hold",
        "a scope nobody serves",
        "no scope",
    ],
)
async def test_a_request_the_client_may_be_told_about_is_rejected_at_its_redirect(
    consent: AuthorizationService,
    principal: Principal,
    overrides: dict[str, str],
    expected: RedirectedError,
) -> None:
    rejected = await consent.describe_consent(principal, params(**overrides))

    assert isinstance(rejected, RedirectedRejection)
    assert rejected.error is expected
    assert query_of(rejected.url) == {
        "error": expected.value,
        "error_description": rejected.description,
        "state": "opaque-client-state",
    }


async def test_plain_pkce_is_refused_even_with_a_challenge_that_is_a_valid_verifier(
    consent: AuthorizationService, principal: Principal
) -> None:
    # A `plain` request whose challenge is well formed for `plain` (it IS the verifier). The
    # method is what refuses it, so the refusal cannot be evaded by shaping the challenge.
    rejected = await consent.describe_consent(
        principal, params(code_challenge=VERIFIER, code_challenge_method="plain")
    )

    assert isinstance(rejected, RedirectedRejection)
    assert "S256" in rejected.description
    assert "plain" in rejected.description


async def test_approving_delivers_a_code_and_the_clients_state(
    consent: AuthorizationService, principal: Principal, store: Store
) -> None:
    outcome = await consent.decide(principal, params(), approved=True)

    delivered = query_of(outcome.url)
    assert outcome.url.startswith(LOOPBACK)
    assert delivered["state"] == "opaque-client-state"
    assert delivered["code"].startswith("syncrc_")
    # Only the digest is stored, so the code in the redirect is the only copy.
    assert digest_of(delivered["code"]) in store.codes
    assert delivered["code"] not in store.codes


async def test_refusing_delivers_access_denied_and_mints_nothing(
    consent: AuthorizationService, principal: Principal, store: Store
) -> None:
    outcome = await consent.decide(principal, params(), approved=False)

    assert query_of(outcome.url)["error"] == RedirectedError.ACCESS_DENIED.value
    assert store.codes == {}
    assert store.grants == {}


async def test_the_grant_is_recorded_for_the_sessions_tenant_and_not_the_requests(
    consent: AuthorizationService, principal: Principal, store: Store
) -> None:
    # There is no tenant parameter on the authorize request, and this is why: the grant's
    # scope comes from the credential that consented.
    await consent.decide(principal, params(), approved=True)

    (grant,) = store.grants.values()
    assert grant.tenant_id == principal.tenant_id
    assert grant.scopes == REQUESTED
    assert grant.is_live


async def test_re_consenting_refreshes_one_grant_rather_than_growing_a_second(
    consent: AuthorizationService, principal: Principal, store: Store, clock: MovableClock
) -> None:
    await consent.decide(principal, params(), approved=True)
    clock.advance(timedelta(days=1))
    await consent.decide(principal, params(scope=Scope.PLAN_READ.value), approved=True)

    (grant,) = store.grants.values()
    assert grant.scopes == {Scope.PLAN_READ}
    assert grant.authorized_at == clock.now


async def test_describing_consent_for_a_session_whose_account_is_gone_is_a_404(
    store: Store, principal: Principal, clock: MovableClock
) -> None:
    service = AuthorizationService(
        clients=FakeCredentials(store),
        grants=FakeScoped(store, principal.tenant_id),
        users=FakeUsers([]),
        clock=clock,
    )

    with pytest.raises(NotFound):
        await service.describe_consent(principal, params())


async def test_a_foreign_principal_cannot_read_this_accounts_email(
    consent: AuthorizationService, principal: Principal
) -> None:
    # 404 rather than 403, so the status does not confirm the account exists.
    intruder = Principal(tenant_id=uuid4(), user_id=principal.user_id, scopes=ALL_SCOPES)

    with pytest.raises(NotFound):
        await consent.describe_consent(intruder, params())


# --- The code exchange ---------------------------------------------------------------


async def test_a_code_exchanges_for_an_audience_bound_pair(
    consent: AuthorizationService,
    tokens: TokenService,
    principal: Principal,
    codec: AccessTokenCodec,
    clock: MovableClock,
) -> None:
    code = await granted_code(consent, principal)

    issued = await tokens.exchange(
        TokenRequest(
            grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
            client_id=CLI_CLIENT_ID,
            code=code,
            code_verifier=VERIFIER,
            redirect_uri=LOOPBACK,
        )
    )

    assert issued.refresh_token.startswith("syncrr_")
    assert issued.expires_in == int(ACCESS_TOKEN_LIFETIME.total_seconds())
    assert issued.scopes == REQUESTED
    bearer = codec.verify(issued.access_token, at=clock.now)
    assert bearer is not None
    assert bearer.tenant_id == principal.tenant_id
    assert bearer.user_id == principal.user_id
    assert bearer.scopes == REQUESTED


async def test_replaying_a_consumed_code_fails(
    consent: AuthorizationService, tokens: TokenService, principal: Principal
) -> None:
    # Single use rests on consumption, not on expiry: the replay below happens inside the
    # code's lifetime and still fails.
    code = await granted_code(consent, principal)
    request = TokenRequest(
        grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
        client_id=CLI_CLIENT_ID,
        code=code,
        code_verifier=VERIFIER,
        redirect_uri=LOOPBACK,
    )
    await tokens.exchange(request)

    with pytest.raises(InvalidGrant):
        await tokens.exchange(request)


async def test_an_expired_code_fails(
    consent: AuthorizationService,
    tokens: TokenService,
    principal: Principal,
    clock: MovableClock,
) -> None:
    code = await granted_code(consent, principal)
    clock.advance(AUTHORIZATION_CODE_LIFETIME)

    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
                client_id=CLI_CLIENT_ID,
                code=code,
                code_verifier=VERIFIER,
                redirect_uri=LOOPBACK,
            )
        )


async def test_a_code_inside_its_lifetime_still_works(
    consent: AuthorizationService,
    tokens: TokenService,
    principal: Principal,
    clock: MovableClock,
) -> None:
    # The control for the expiry assertion: the boundary is the expiry, not any exchange
    # after a delay.
    code = await granted_code(consent, principal)
    clock.advance(AUTHORIZATION_CODE_LIFETIME - timedelta(seconds=1))

    issued = await tokens.exchange(
        TokenRequest(
            grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
            client_id=CLI_CLIENT_ID,
            code=code,
            code_verifier=VERIFIER,
            redirect_uri=LOOPBACK,
        )
    )

    assert issued.access_token


async def test_the_wrong_verifier_fails(
    consent: AuthorizationService, tokens: TokenService, principal: Principal
) -> None:
    code = await granted_code(consent, principal)

    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
                client_id=CLI_CLIENT_ID,
                code=code,
                code_verifier="b" * len(VERIFIER),
                redirect_uri=LOOPBACK,
            )
        )


async def test_a_mismatched_redirect_uri_fails(
    consent: AuthorizationService, tokens: TokenService, principal: Principal
) -> None:
    code = await granted_code(consent, principal)

    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
                client_id=CLI_CLIENT_ID,
                code=code,
                code_verifier=VERIFIER,
                redirect_uri="http://127.0.0.1:9999/somewhere-else",
            )
        )


async def test_a_missing_verifier_is_a_malformed_request_rather_than_a_bad_grant(
    tokens: TokenService,
) -> None:
    with pytest.raises(InvalidRequest):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_AUTHORIZATION_CODE, client_id=CLI_CLIENT_ID, code="syncrc_x"
            )
        )


async def test_an_unknown_client_on_the_token_endpoint_is_told_so(tokens: TokenService) -> None:
    with pytest.raises(InvalidClient):
        await tokens.exchange(
            TokenRequest(grant_type=GRANT_TYPE_AUTHORIZATION_CODE, client_id="not-registered")
        )


async def test_an_unsupported_grant_type_is_named(tokens: TokenService) -> None:
    with pytest.raises(UnsupportedGrantType):
        await tokens.exchange(TokenRequest(grant_type="password", client_id=CLI_CLIENT_ID))


# --- Rotation and family revocation --------------------------------------------------


async def exchange_code(
    consent: AuthorizationService, tokens: TokenService, principal: Principal
) -> str:
    code = await granted_code(consent, principal)
    issued = await tokens.exchange(
        TokenRequest(
            grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
            client_id=CLI_CLIENT_ID,
            code=code,
            code_verifier=VERIFIER,
            redirect_uri=LOOPBACK,
        )
    )
    return issued.refresh_token


async def test_a_refresh_rotates_the_token(
    consent: AuthorizationService, tokens: TokenService, principal: Principal
) -> None:
    first = await exchange_code(consent, tokens, principal)

    refreshed = await tokens.exchange(
        TokenRequest(
            grant_type=GRANT_TYPE_REFRESH_TOKEN, client_id=CLI_CLIENT_ID, refresh_token=first
        )
    )

    assert refreshed.refresh_token != first
    assert refreshed.scopes == REQUESTED


async def test_reusing_a_consumed_refresh_token_revokes_the_whole_grant_family(
    consent: AuthorizationService, tokens: TokenService, principal: Principal, store: Store
) -> None:
    # The stolen-token defense. A client holding a live refresh token never presents a
    # consumed one, so a consumed one arriving means two parties hold the chain and neither
    # can be told from the other. Everything goes.
    first = await exchange_code(consent, tokens, principal)
    second = await tokens.exchange(
        TokenRequest(
            grant_type=GRANT_TYPE_REFRESH_TOKEN, client_id=CLI_CLIENT_ID, refresh_token=first
        )
    )

    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_REFRESH_TOKEN, client_id=CLI_CLIENT_ID, refresh_token=first
            )
        )

    assert all(token.revoked_at is not None for token in store.refresh_tokens.values())
    assert all(not grant.is_live for grant in store.grants.values())
    # The successor the legitimate client holds is dead too, which is the cost of not being
    # able to tell the two holders apart.
    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_REFRESH_TOKEN,
                client_id=CLI_CLIENT_ID,
                refresh_token=second.refresh_token,
            )
        )


async def test_a_revoked_family_cannot_be_re_established_by_an_unexpired_code(
    consent: AuthorizationService, tokens: TokenService, principal: Principal
) -> None:
    # Why the grant is revoked alongside its tokens. A code minted before the replay would
    # otherwise still exchange, and the family would be back.
    code = await granted_code(consent, principal)
    first = await exchange_code(consent, tokens, principal)
    await tokens.exchange(
        TokenRequest(
            grant_type=GRANT_TYPE_REFRESH_TOKEN, client_id=CLI_CLIENT_ID, refresh_token=first
        )
    )
    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_REFRESH_TOKEN, client_id=CLI_CLIENT_ID, refresh_token=first
            )
        )

    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
                client_id=CLI_CLIENT_ID,
                code=code,
                code_verifier=VERIFIER,
                redirect_uri=LOOPBACK,
            )
        )


async def test_an_expired_refresh_token_fails(
    consent: AuthorizationService,
    tokens: TokenService,
    principal: Principal,
    clock: MovableClock,
) -> None:
    first = await exchange_code(consent, tokens, principal)
    clock.advance(REFRESH_TOKEN_LIFETIME)

    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_REFRESH_TOKEN, client_id=CLI_CLIENT_ID, refresh_token=first
            )
        )


async def test_a_refresh_token_presented_by_another_client_fails(
    consent: AuthorizationService, tokens: TokenService, principal: Principal, store: Store
) -> None:
    store.clients["another-cli"] = ClientRecord(
        id="another-cli",
        name="Another client",
        redirect_uris=CLI_REDIRECT_URIS,
        allowed_scopes=CLI_CLIENT_SCOPES,
        loopback_only=True,
    )
    first = await exchange_code(consent, tokens, principal)

    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_REFRESH_TOKEN, client_id="another-cli", refresh_token=first
            )
        )


async def test_an_unknown_refresh_token_fails(tokens: TokenService) -> None:
    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_REFRESH_TOKEN,
                client_id=CLI_CLIENT_ID,
                refresh_token="syncrr_never-minted-by-this-server",
            )
        )


# --- Revocation ----------------------------------------------------------------------


async def test_revoking_ends_the_family_server_side(
    consent: AuthorizationService, tokens: TokenService, principal: Principal, store: Store
) -> None:
    first = await exchange_code(consent, tokens, principal)

    await tokens.revoke(first, CLI_CLIENT_ID)

    assert all(token.revoked_at is not None for token in store.refresh_tokens.values())
    with pytest.raises(InvalidGrant):
        await tokens.exchange(
            TokenRequest(
                grant_type=GRANT_TYPE_REFRESH_TOKEN, client_id=CLI_CLIENT_ID, refresh_token=first
            )
        )


async def test_revoking_an_unknown_token_says_nothing_about_it(tokens: TokenService) -> None:
    # RFC 7009: any other behavior makes this endpoint an oracle for whether a token is live.
    await tokens.revoke("syncrr_never-minted", CLI_CLIENT_ID)


async def test_another_clients_token_is_not_revoked_and_not_reported(
    consent: AuthorizationService, tokens: TokenService, principal: Principal, store: Store
) -> None:
    first = await exchange_code(consent, tokens, principal)

    await tokens.revoke(first, "another-cli")

    assert all(token.revoked_at is None for token in store.refresh_tokens.values())


# --- Introspection and the scope boundary --------------------------------------------


async def test_a_bearer_token_resolves_to_the_principal_its_grant_named(
    consent: AuthorizationService, tokens: TokenService, principal: Principal
) -> None:
    code = await granted_code(consent, principal)
    issued = await tokens.exchange(
        TokenRequest(
            grant_type=GRANT_TYPE_AUTHORIZATION_CODE,
            client_id=CLI_CLIENT_ID,
            code=code,
            code_verifier=VERIFIER,
            redirect_uri=LOOPBACK,
        )
    )

    resolved = tokens.introspect(issued.access_token)

    assert resolved.tenant_id == principal.tenant_id
    assert resolved.scopes == REQUESTED


def test_a_plan_write_token_is_rejected_where_admin_is_required() -> None:
    # The scope check, at the service boundary. The CLI never receives `admin`, so this is
    # what stops a stolen CLI token from reaching calendar sources or the write target.
    cli = Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=CLI_CLIENT_SCOPES)

    require_scope(cli, Scope.PLAN_WRITE)

    with pytest.raises(Forbidden) as refused:
        require_scope(cli, Scope.ADMIN)
    assert refused.value.status == 403
    assert "admin" in refused.value.detail


def test_a_scope_a_credential_holds_is_allowed_and_one_it_does_not_is_not() -> None:
    read_only = Principal(tenant_id=uuid4(), user_id=uuid4(), scopes=frozenset({Scope.PLAN_READ}))

    require_scope(read_only, Scope.PLAN_READ)
    with pytest.raises(Forbidden):
        require_scope(read_only, Scope.PLAN_WRITE)


def test_the_cli_client_is_never_registered_for_admin() -> None:
    assert Scope.ADMIN not in CLI_CLIENT_SCOPES
    assert parse_scopes(format_scopes(CLI_CLIENT_SCOPES)) == CLI_CLIENT_SCOPES


# --- Expiry, as the sweep sees it ----------------------------------------------------


async def test_expiry_removes_a_consumed_code_and_a_live_one_alike(
    consent: AuthorizationService,
    tokens: TokenService,
    principal: Principal,
    store: Store,
    clock: MovableClock,
) -> None:
    # What the sweep deletes, asserted over both kinds of row rather than "some time later".
    # Two codes: one abandoned in a browser, one exchanged. Both are dead weight once expired.
    # The boundary instant itself belongs to the database and is asserted against real Postgres
    # in test_oauth_flow_integration.py, because a fake that implements the same comparison
    # cannot tell a production `<` from a `<=`.
    await granted_code(consent, principal)
    await exchange_code(consent, tokens, principal)
    scoped = FakeScoped(store, principal.tenant_id)
    assert len(store.codes) == 2

    clock.advance(AUTHORIZATION_CODE_LIFETIME * 2)

    assert await scoped.delete_expired_codes(clock.now) == 2
    assert store.codes == {}


async def test_a_refresh_token_outlives_the_code_that_produced_it(
    consent: AuthorizationService,
    tokens: TokenService,
    principal: Principal,
    store: Store,
    clock: MovableClock,
) -> None:
    await exchange_code(consent, tokens, principal)
    scoped = FakeScoped(store, principal.tenant_id)

    clock.advance(AUTHORIZATION_CODE_LIFETIME + timedelta(seconds=1))
    await scoped.delete_expired_codes(clock.now)

    assert len(store.refresh_tokens) == 1
    clock.advance(REFRESH_TOKEN_LIFETIME)
    assert await scoped.delete_expired_refresh_tokens(clock.now) == 1


async def test_a_revoked_grant_is_kept_for_the_retention_window_and_then_removed(
    consent: AuthorizationService,
    tokens: TokenService,
    principal: Principal,
    store: Store,
    clock: MovableClock,
) -> None:
    # Not removed the moment it dies: an operator investigating a revocation needs something
    # to read. Well inside the window here; the window's exact edge is the database's, and is
    # asserted against real Postgres in test_oauth_flow_integration.py.
    await exchange_code(consent, tokens, principal)
    scoped = FakeScoped(store, principal.tenant_id)
    await scoped.revoke_family(next(iter(store.grants)), clock.now)

    clock.advance(DEAD_GRANT_RETENTION / 2)
    assert await scoped.delete_grants_revoked_before(clock.now - DEAD_GRANT_RETENTION) == 0

    clock.advance(DEAD_GRANT_RETENTION)
    assert await scoped.delete_grants_revoked_before(clock.now - DEAD_GRANT_RETENTION) == 1
    assert store.grants == {}
