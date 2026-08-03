"""The whole OAuth flow through HTTP, against a real Postgres.

The service suite proves the rules with fakes and a moved clock. This proves the things only a
real request and a real database can: that the guarded updates single use and rotation rest on
are the database's decision and not a read-then-write, that the redirect the browser follows
carries what the CLI's listener needs, that the consent screen is a page a browser can render,
that a replayed refresh token really takes its family down in committed rows, and that no
secret reaches a log line at any level.

Every test seeds its own tenant and removes it afterwards, so the suite depends on nothing in a
developer's database and leaves nothing there.

The session cookie is replayed by setting the header rather than through the client's jar. The
cookie is ``Secure``, and a client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import Forbidden, OriginRejected, Unauthorized
from syncr_api.core.scopes import Scope
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.core.tenancy import TenantScoped
from syncr_api.oauth.cleanup import ExpirySweep, SweptRows
from syncr_api.oauth.config import (
    AUTHORIZE_PATH,
    CLI_CLIENT_ID,
    CONSENT_DECISION_PATH,
    DEAD_GRANT_RETENTION,
    GRANT_TYPE_AUTHORIZATION_CODE,
    GRANT_TYPE_REFRESH_TOKEN,
    JWKS_PATH,
    OAUTH_PREFIX,
    REVOKE_PATH,
    TOKEN_PATH,
    WELL_KNOWN_PREFIX,
    build_oauth_config,
)
from syncr_api.oauth.consent import DECISION_APPROVE, DECISION_DENY, DECISION_FIELD
from syncr_api.oauth.errors import InvalidGrant, InvalidRequest, InvalidToken
from syncr_api.oauth.injection import build_oauth_state
from syncr_api.oauth.keys import SigningKeySet, generate_signing_key, rotate
from syncr_api.oauth.metadata import DISCOVERY_PATH
from syncr_api.oauth.models import OAuthAuthorizationCode, OAuthGrant, OAuthRefreshToken
from syncr_api.oauth.pkce import CHALLENGE_LENGTH, derive_s256_challenge
from syncr_api.oauth.repository import OAuthRepository
from syncr_api.oauth.secrets import digest_of
from syncr_common.logging import configure_logging
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run
from tests.scope_probe import (
    PROBE_ADMIN_PATH,
    PROBE_PLAN_WRITE_PATH,
    REACHED_FIELD,
    probe_router,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    import httpx
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.db import Database
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
ISSUER = "http://testserver"

# RFC 7636 appendix B's published verifier, so it is a specification value and not a secret.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # pragma: allowlist secret
CHALLENGE = derive_s256_challenge(VERIFIER)
LOOPBACK = "http://127.0.0.1:54321/callback"
STATE = "cli-supplied-state"
REQUESTED_SCOPE = "plan:read plan:write"
ONE_SECOND = timedelta(seconds=1)

LOGIN = f"{AUTH_PREFIX}/login"
AUTHORIZE = f"{OAUTH_PREFIX}{AUTHORIZE_PATH}"
DECISION = f"{OAUTH_PREFIX}{CONSENT_DECISION_PATH}"
TOKEN = f"{OAUTH_PREFIX}{TOKEN_PATH}"
REVOKE = f"{OAUTH_PREFIX}{REVOKE_PATH}"
JWKS = f"{WELL_KNOWN_PREFIX}{JWKS_PATH}"


def authorize_query(**overrides: str) -> dict[str, str]:
    query = {
        "client_id": CLI_CLIENT_ID,
        "redirect_uri": LOOPBACK,
        "response_type": "code",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "scope": REQUESTED_SCOPE,
        "state": STATE,
    }
    query.update(overrides)
    return query


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    """A tenant and its one user, created and then removed."""
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def keys() -> SigningKeySet:
    return SigningKeySet(current=generate_signing_key("integration"))


def build_app(database: Database, settings: ServiceSettings, keys: SigningKeySet) -> FastAPI:
    """An app wired to a live database and a key set, as the api entrypoint wires one."""
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    app.state.oauth = build_oauth_state(build_oauth_config(settings, is_dev=True), keys)
    return app


@pytest.fixture
def oauth_app(live_database_url: str, settings: ServiceSettings, keys: SigningKeySet) -> FastAPI:
    return build_app(create_database(live_database_url), settings, keys)


@pytest.fixture
def http(oauth_app: FastAPI) -> Iterator[TestClient]:
    """A client against an app wired to the live database, as the api process wires it."""
    with TestClient(oauth_app, raise_server_exceptions=False, base_url=ISSUER) as client:
        yield client


@pytest.fixture
def probe_http(oauth_app: FastAPI) -> Iterator[TestClient]:
    """The same client, with a scope-guarded route mounted for the bearer credential."""
    oauth_app.include_router(probe_router)
    with TestClient(oauth_app, raise_server_exceptions=False, base_url=ISSUER) as client:
        yield client


def signed_in(http: TestClient, email: str) -> dict[str, str]:
    """The cookie header a signed-in browser sends."""
    response = http.post(
        LOGIN, json={"email": email, "password": PASSWORD}, headers={"Origin": BROWSER_ORIGIN}
    )
    assert response.status_code == 200, response.text
    token = response.headers["set-cookie"].split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def consent(http: TestClient, session: dict[str, str], **overrides: str) -> dict[str, str]:
    """Drive the consent decision and return what the redirect delivered."""
    query = authorize_query(**overrides)
    response = http.post(
        DECISION,
        data={**query, DECISION_FIELD: DECISION_APPROVE},
        headers={**session, "Origin": BROWSER_ORIGIN},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return delivered(response.headers["location"])


def delivered(location: str) -> dict[str, str]:
    return {key: value[0] for key, value in parse_qs(urlsplit(location).query).items()}


def exchange(http: TestClient, code: str, **overrides: str) -> dict[str, object]:
    form = {
        "grant_type": GRANT_TYPE_AUTHORIZATION_CODE,
        "client_id": CLI_CLIENT_ID,
        "code": code,
        "code_verifier": VERIFIER,
        "redirect_uri": LOOPBACK,
    }
    form.update(overrides)
    response = http.post(TOKEN, data=form)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def refresh(http: TestClient, refresh_token: str) -> httpx.Response:
    # Annotated on the way out rather than cast: `TestClient` is typed loosely enough that the
    # response is `Any`, and every assertion in this module reads an attribute of it.
    response: httpx.Response = http.post(
        TOKEN,
        data={
            "grant_type": GRANT_TYPE_REFRESH_TOKEN,
            "client_id": CLI_CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )
    return response


def bearer(issued: dict[str, object]) -> dict[str, str]:
    """The header a client presents an access token in."""
    return {"Authorization": f"Bearer {issued['access_token']}"}


def in_a_transaction[ResultT](
    live_database_url: str, work: Callable[[AsyncSession], Awaitable[ResultT]]
) -> ResultT:
    """Run one unit of work against the live database, on a loop and an engine of its own.

    An asyncpg connection belongs to the loop that opened it, so a synchronous test cannot
    reach into the application's.
    """

    async def opened() -> ResultT:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                return await work(session)
        finally:
            await database.engine.dispose()

    return run(opened())


def rows_of[ModelT: TenantScoped](
    live_database_url: str, model: type[ModelT], tenant_id: TenantId
) -> list[ModelT]:
    """A tenant's rows of one kind, read on a connection of this test's own."""

    async def read() -> list[ModelT]:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(select(model).where(model.tenant_id == tenant_id))
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


# --- Discovery -------------------------------------------------------------------------


def test_the_discovery_document_is_served_at_the_path_the_rfc_fixes(http: TestClient) -> None:
    response = http.get(DISCOVERY_PATH)

    assert response.status_code == 200
    document = response.json()
    assert document["code_challenge_methods_supported"] == ["S256"]
    assert document["token_endpoint"].endswith(TOKEN)
    assert response.headers["cache-control"] == "no-store"


def test_the_jwks_publishes_the_current_and_previous_key(
    live_database_url: str, settings: ServiceSettings, keys: SigningKeySet
) -> None:
    # Rotated once, and the result held: `rotate` mints a random `kid` per call, so a second
    # call could not name the keys this app was wired with.
    rotated = rotate(keys)
    app = build_app(create_database(live_database_url), settings, rotated)

    with TestClient(app, base_url=ISSUER) as client:
        published = client.get(JWKS).json()

    assert [key["kid"] for key in published["keys"]] == [rotated.current.kid, keys.current.kid]
    assert all("d" not in key for key in published["keys"])


def test_discovery_and_jwks_need_no_credential(http: TestClient) -> None:
    # A client reads both before it has anything to present.
    assert http.get(DISCOVERY_PATH).status_code == 200
    assert http.get(JWKS).status_code == 200


# --- Consent ---------------------------------------------------------------------------


def test_the_authorize_endpoint_needs_a_browser_session(http: TestClient) -> None:
    response = http.get(AUTHORIZE, params=authorize_query())

    assert response.status_code == 401
    assert response.json()["type"] == Unauthorized.type


def test_the_consent_screen_is_a_page_that_names_the_scopes(
    http: TestClient, owner: UserRecord
) -> None:
    session = signed_in(http, owner.email)

    response = http.get(AUTHORIZE, params=authorize_query(), headers=session)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    for scope in (Scope.PLAN_READ.value, Scope.PLAN_WRITE.value):
        assert scope in response.text
    assert owner.email in response.text


def test_plain_pkce_is_rejected_at_the_clients_redirect(
    http: TestClient, owner: UserRecord
) -> None:
    session = signed_in(http, owner.email)

    response = http.get(
        AUTHORIZE,
        params=authorize_query(code_challenge_method="plain", code_challenge=VERIFIER),
        headers=session,
        follow_redirects=False,
    )

    assert response.status_code == 303
    answered = delivered(response.headers["location"])
    assert response.headers["location"].startswith(LOOPBACK)
    assert answered["error"] == "invalid_request"
    assert "S256" in answered["error_description"]
    assert answered["state"] == STATE


def test_a_challenge_outside_the_base64url_alphabet_is_rejected_at_the_redirect(
    http: TestClient, owner: UserRecord
) -> None:
    # A right-length non-ASCII challenge used to pass the shape rule and reach the digest
    # comparison at exchange time, which answered 500. The refusal belongs at the edge.
    session = signed_in(http, owner.email)

    response = http.get(
        AUTHORIZE,
        params=authorize_query(code_challenge="\u00c1" * CHALLENGE_LENGTH),
        headers=session,
        follow_redirects=False,
    )

    assert response.status_code == 303
    answered = delivered(response.headers["location"])
    assert answered["error"] == "invalid_request"
    assert "code_challenge" in answered["error_description"]


def test_an_unregistered_redirect_is_answered_here_and_never_followed(
    http: TestClient, owner: UserRecord
) -> None:
    session = signed_in(http, owner.email)

    response = http.get(
        AUTHORIZE,
        params=authorize_query(redirect_uri="https://attacker.example/callback"),
        headers=session,
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["type"] == InvalidRequest.type
    assert "location" not in response.headers


def test_approving_delivers_a_single_use_code_to_the_loopback_listener(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    session = signed_in(http, owner.email)

    answered = consent(http, session)

    assert answered["state"] == STATE
    assert answered["code"].startswith("syncrc_")
    (stored,) = rows_of(live_database_url, OAuthAuthorizationCode, owner.tenant_id)
    assert stored.id == digest_of(answered["code"])
    assert stored.consumed_at is None


def test_refusing_delivers_access_denied_and_records_nothing(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    session = signed_in(http, owner.email)

    response = http.post(
        DECISION,
        data={**authorize_query(), DECISION_FIELD: DECISION_DENY},
        headers={**session, "Origin": BROWSER_ORIGIN},
        follow_redirects=False,
    )

    assert delivered(response.headers["location"])["error"] == "access_denied"
    assert rows_of(live_database_url, OAuthAuthorizationCode, owner.tenant_id) == []
    assert rows_of(live_database_url, OAuthGrant, owner.tenant_id) == []


def test_the_consent_decision_is_refused_from_another_origin(
    http: TestClient, owner: UserRecord
) -> None:
    # The decision is a browser POST carrying an ambient cookie, so it needs the origin check
    # the token endpoint does not.
    session = signed_in(http, owner.email)

    response = http.post(
        DECISION,
        data={**authorize_query(), DECISION_FIELD: DECISION_APPROVE},
        headers={**session, "Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json()["type"] == OriginRejected.type


def test_a_bearer_token_cannot_consent_on_its_own_behalf(
    http: TestClient, owner: UserRecord
) -> None:
    # A client that could self-consent could widen its own scopes or outlive its revocation.
    session = signed_in(http, owner.email)
    issued = exchange(http, consent(http, session)["code"])

    response = http.get(AUTHORIZE, params=authorize_query(), headers=bearer(issued))

    assert response.status_code == 401


# --- The token endpoint ----------------------------------------------------------------


def test_a_code_exchanges_for_a_pair_the_rfc_shapes(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    session = signed_in(http, owner.email)

    issued = exchange(http, consent(http, session)["code"])

    assert issued["token_type"] == "Bearer"
    assert issued["scope"] == REQUESTED_SCOPE
    assert isinstance(issued["expires_in"], int)
    assert str(issued["refresh_token"]).startswith("syncrr_")
    (stored,) = rows_of(live_database_url, OAuthRefreshToken, owner.tenant_id)
    assert stored.id == digest_of(str(issued["refresh_token"]))


def test_the_token_response_is_never_cached(http: TestClient, owner: UserRecord) -> None:
    session = signed_in(http, owner.email)
    code = consent(http, session)["code"]

    response = http.post(
        TOKEN,
        data={
            "grant_type": GRANT_TYPE_AUTHORIZATION_CODE,
            "client_id": CLI_CLIENT_ID,
            "code": code,
            "code_verifier": VERIFIER,
            "redirect_uri": LOOPBACK,
        },
    )

    assert response.headers["cache-control"] == "no-store"


def test_the_token_endpoint_needs_no_origin_header(http: TestClient, owner: UserRecord) -> None:
    # The CLI is not a browser and sends none. The credential here is in the body rather than
    # ambient, so there is nothing for a cross-origin page to forge.
    session = signed_in(http, owner.email)

    issued = exchange(http, consent(http, session)["code"])

    assert issued["access_token"]


def test_replaying_a_consumed_code_fails_against_the_database(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    # The consumption is a guarded UPDATE whose row count decides, so this asserts the
    # database enforced single use rather than a read-then-write in the service.
    session = signed_in(http, owner.email)
    code = consent(http, session)["code"]
    exchange(http, code)

    replayed = http.post(
        TOKEN,
        data={
            "grant_type": GRANT_TYPE_AUTHORIZATION_CODE,
            "client_id": CLI_CLIENT_ID,
            "code": code,
            "code_verifier": VERIFIER,
            "redirect_uri": LOOPBACK,
        },
    )

    assert replayed.status_code == 400
    assert replayed.json()["type"] == InvalidGrant.type
    (stored,) = rows_of(live_database_url, OAuthAuthorizationCode, owner.tenant_id)
    assert stored.consumed_at is not None
    assert len(rows_of(live_database_url, OAuthRefreshToken, owner.tenant_id)) == 1


def test_the_access_token_is_bound_to_this_apis_audience(
    http: TestClient, owner: UserRecord, keys: SigningKeySet, settings: ServiceSettings
) -> None:
    from syncr_api.oauth.access_tokens import AccessTokenCodec

    session = signed_in(http, owner.email)
    issued = exchange(http, consent(http, session)["code"])
    config = build_oauth_config(settings, is_dev=True)

    ours = AccessTokenCodec(keys, issuer=config.issuer, audience=config.audience)
    elsewhere = AccessTokenCodec(keys, issuer=config.issuer, audience="https://mcp.syncr.example")
    presented = str(issued["access_token"])

    assert ours.verify(presented, at=datetime.now(UTC)) is not None
    assert elsewhere.verify(presented, at=datetime.now(UTC)) is None


def test_a_refresh_rotates_and_a_replay_takes_the_family_down(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    session = signed_in(http, owner.email)
    issued = exchange(http, consent(http, session)["code"])
    first = str(issued["refresh_token"])

    rotated = refresh(http, first)
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first

    replayed = refresh(http, first)

    assert replayed.status_code == 400
    tokens = rows_of(live_database_url, OAuthRefreshToken, owner.tenant_id)
    assert len(tokens) == 2
    assert all(token.revoked_at is not None for token in tokens)
    (grant,) = rows_of(live_database_url, OAuthGrant, owner.tenant_id)
    assert grant.revoked_at is not None
    # The successor the honest client holds is dead too: the two holders cannot be told apart.
    assert refresh(http, second).status_code == 400


def test_revoking_ends_the_family_server_side(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    session = signed_in(http, owner.email)
    issued = exchange(http, consent(http, session)["code"])
    presented = str(issued["refresh_token"])

    revoked = http.post(REVOKE, data={"token": presented, "client_id": CLI_CLIENT_ID})

    assert revoked.status_code == 200
    assert revoked.headers["cache-control"] == "no-store"
    assert refresh(http, presented).status_code == 400
    (grant,) = rows_of(live_database_url, OAuthGrant, owner.tenant_id)
    assert grant.revoked_at is not None


def test_revoking_an_unknown_token_answers_the_same_way(http: TestClient) -> None:
    response = http.post(
        REVOKE, data={"token": "syncrr_never-minted-here", "client_id": CLI_CLIENT_ID}
    )

    assert response.status_code == 200
    assert response.content == b""


def test_a_token_type_hint_is_accepted(http: TestClient, owner: UserRecord) -> None:
    session = signed_in(http, owner.email)
    issued = exchange(http, consent(http, session)["code"])

    response = http.post(
        REVOKE,
        data={
            "token": str(issued["refresh_token"]),
            "client_id": CLI_CLIENT_ID,
            "token_type_hint": "refresh_token",
        },
    )

    assert response.status_code == 200


# --- The bearer credential -------------------------------------------------------------


def test_a_plan_write_token_is_refused_where_admin_is_required(
    probe_http: TestClient, owner: UserRecord
) -> None:
    """The whole seam: an ``Authorization`` header, introspection, the scopes, then 403.

    The scope arithmetic is asserted on its own in the service suite. This is what proves the
    four links between a presented token and a refusal are joined: a broken bearer dependency,
    a dropped ``scope`` claim, or a principal built with no scopes would pass that test and
    fail this one.
    """
    session = signed_in(probe_http, owner.email)
    issued = exchange(probe_http, consent(probe_http, session)["code"])

    refused = probe_http.get(PROBE_ADMIN_PATH, headers=bearer(issued))

    assert refused.status_code == 403
    assert refused.json()["type"] == Forbidden.type
    # The counterpart, so the assertion discriminates: the same token reaches the route whose
    # scope its grant does carry.
    allowed = probe_http.get(PROBE_PLAN_WRITE_PATH, headers=bearer(issued))
    assert allowed.status_code == 200
    assert allowed.json() == {REACHED_FIELD: Scope.PLAN_WRITE.value}


def test_a_route_needing_a_token_says_how_to_present_one(probe_http: TestClient) -> None:
    # RFC 6750 section 3: a 401 from a bearer-protected resource names the scheme, so a client
    # learns what to present rather than guessing.
    response = probe_http.get(PROBE_PLAN_WRITE_PATH)

    assert response.status_code == 401
    assert response.json()["type"] == InvalidToken.type
    assert response.headers["www-authenticate"] == 'Bearer realm="syncr"'


@pytest.mark.parametrize(
    "presented",
    ["not-a-jwt", "eyJ.eyJ.signature", ""],
    ids=["nonsense", "jwt shaped", "empty"],
)
def test_a_token_this_server_never_signed_reaches_no_route(
    probe_http: TestClient, presented: str
) -> None:
    response = probe_http.get(
        PROBE_PLAN_WRITE_PATH, headers={"Authorization": f"Bearer {presented}"}
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer realm="syncr"'


def test_a_revoked_familys_access_token_still_reaches_a_route_until_it_expires(
    probe_http: TestClient, owner: UserRecord
) -> None:
    # The stated cost of a credential verified without a database read, asserted rather than
    # left as prose: revocation takes effect within the access token's fifteen minutes.
    session = signed_in(probe_http, owner.email)
    issued = exchange(probe_http, consent(probe_http, session)["code"])
    probe_http.post(
        REVOKE, data={"token": str(issued["refresh_token"]), "client_id": CLI_CLIENT_ID}
    )

    assert refresh(probe_http, str(issued["refresh_token"])).status_code == 400
    assert probe_http.get(PROBE_PLAN_WRITE_PATH, headers=bearer(issued)).status_code == 200


# --- Tenancy ---------------------------------------------------------------------------


def test_the_grant_is_written_under_the_signed_in_tenant(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    session = signed_in(http, owner.email)

    consent(http, session)

    (grant,) = rows_of(live_database_url, OAuthGrant, owner.tenant_id)
    assert grant.tenant_id == owner.tenant_id
    assert grant.client_id == CLI_CLIENT_ID


def test_two_tenants_hold_independent_grants(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    # One live grant per tenant and client is a unique INDEX on (tenant_id, client_id), so this
    # is what proves the uniqueness is scoped rather than global.
    second = provision_owner(live_database_url)
    try:
        consent(http, signed_in(http, owner.email))
        consent(http, signed_in(http, second.email))

        assert len(rows_of(live_database_url, OAuthGrant, owner.tenant_id)) == 1
        assert len(rows_of(live_database_url, OAuthGrant, second.tenant_id)) == 1
    finally:
        remove_tenant(live_database_url, second.tenant_id)


def test_removing_a_tenant_removes_its_grants_and_tokens(
    live_database_url: str, settings: ServiceSettings, keys: SigningKeySet
) -> None:
    account = provision_owner(live_database_url)
    app = build_app(create_database(live_database_url), settings, keys)
    with TestClient(app, raise_server_exceptions=False, base_url=ISSUER) as client:
        exchange(client, consent(client, signed_in(client, account.email))["code"])
    assert rows_of(live_database_url, OAuthRefreshToken, account.tenant_id)

    remove_tenant(live_database_url, account.tenant_id)

    assert rows_of(live_database_url, OAuthGrant, account.tenant_id) == []
    assert rows_of(live_database_url, OAuthRefreshToken, account.tenant_id) == []
    assert rows_of(live_database_url, OAuthAuthorizationCode, account.tenant_id) == []


# --- The sweep -------------------------------------------------------------------------


def swept_at(live_database_url: str, instant: datetime) -> SweptRows:
    """What one sweep removes when it believes the time is ``instant``."""
    return in_a_transaction(
        live_database_url, lambda opened: ExpirySweep(opened, lambda: instant).sweep()
    )


def test_the_sweep_removes_an_expired_code_and_leaves_a_live_refresh_token(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    session = signed_in(http, owner.email)
    exchange(http, consent(http, session)["code"])
    assert len(rows_of(live_database_url, OAuthAuthorizationCode, owner.tenant_id)) == 1

    # An hour on: the code's minute is long past, the refresh token's two months are not.
    # Passing the instant is what lets one sweep prove both.
    swept = swept_at(live_database_url, datetime.now(UTC) + timedelta(hours=1))

    assert swept.codes >= 1
    assert rows_of(live_database_url, OAuthAuthorizationCode, owner.tenant_id) == []
    assert len(rows_of(live_database_url, OAuthRefreshToken, owner.tenant_id)) == 1


def test_a_row_expiring_at_the_instant_swept_to_survives_and_one_before_it_does_not(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    """The expiry boundary is exclusive, and the database is what decides it.

    Asserted here rather than against the service fakes, which implement the same comparison
    themselves and so cannot tell a production ``<`` from a production ``<=``. Two rows of
    each kind are seeded a second apart around one instant, and the survivors are named.
    """
    session = signed_in(http, owner.email)
    issued = exchange(http, consent(http, session)["code"])
    instant = datetime.now(UTC) + timedelta(days=1)
    at_the_instant = "expires-at-the-instant"
    before_it = "expires-a-second-before"

    async def seed(opened: AsyncSession) -> None:
        scoped = OAuthRepository(opened, owner.tenant_id)
        grant = await scoped.find_grant_for_client(CLI_CLIENT_ID)
        assert grant is not None
        for name, expires_at in ((at_the_instant, instant), (before_it, instant - ONE_SECOND)):
            await scoped.create_code(
                code_id=digest_of(name),
                client_id=CLI_CLIENT_ID,
                redirect_uri=LOOPBACK,
                scopes=frozenset({Scope.PLAN_READ}),
                code_challenge=CHALLENGE,
                created_at=datetime.now(UTC),
                expires_at=expires_at,
            )
            await scoped.create_refresh_token(
                token_id=digest_of(name),
                grant_id=grant.id,
                scopes=frozenset({Scope.PLAN_READ}),
                created_at=datetime.now(UTC),
                expires_at=expires_at,
            )

    in_a_transaction(live_database_url, seed)

    swept = swept_at(live_database_url, instant)

    # The flow's own code expired an hour ago on this clock; its refresh token has not.
    assert (swept.codes, swept.refresh_tokens) == (2, 1)
    assert {
        code.id for code in rows_of(live_database_url, OAuthAuthorizationCode, owner.tenant_id)
    } == {digest_of(at_the_instant)}
    assert {
        token.id for token in rows_of(live_database_url, OAuthRefreshToken, owner.tenant_id)
    } == {digest_of(str(issued["refresh_token"])), digest_of(at_the_instant)}


def test_a_revoked_grant_is_kept_for_the_whole_retention_window_and_then_removed(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    # Not removed the moment it dies: an operator investigating a revocation needs something
    # to read. The window's own boundary is the database's, so it is asserted here, against the
    # instant the row actually carries rather than against one this test picked.
    session = signed_in(http, owner.email)
    issued = exchange(http, consent(http, session)["code"])
    http.post(REVOKE, data={"token": str(issued["refresh_token"]), "client_id": CLI_CLIENT_ID})
    (revoked,) = rows_of(live_database_url, OAuthGrant, owner.tenant_id)
    assert revoked.revoked_at is not None

    assert swept_at(live_database_url, revoked.revoked_at + DEAD_GRANT_RETENTION).grants == 0
    assert rows_of(live_database_url, OAuthGrant, owner.tenant_id) != []

    swept = swept_at(live_database_url, revoked.revoked_at + DEAD_GRANT_RETENTION + ONE_SECOND)

    assert swept.grants == 1
    assert rows_of(live_database_url, OAuthGrant, owner.tenant_id) == []
    # The grant's refresh tokens go with it through the foreign key's cascade.
    assert rows_of(live_database_url, OAuthRefreshToken, owner.tenant_id) == []


# --- Logging ---------------------------------------------------------------------------


def test_no_secret_reaches_a_log_line_at_any_level(
    live_database_url: str, settings: ServiceSettings, keys: SigningKeySet
) -> None:
    """Drive the whole flow at debug level and assert every secret is absent from the stream.

    Not a check of the redactor's key list: the secrets are the actual values this run minted,
    searched for verbatim in what was rendered. A log call that interpolated one into an event
    name, or bound it under a key nobody thought of, fails here.
    """
    stream = StringIO()
    configure_logging(environment="test", log_level="debug", stream=stream)
    account = provision_owner(live_database_url)
    app = build_app(create_database(live_database_url), settings, keys)
    try:
        with TestClient(app, raise_server_exceptions=False, base_url=ISSUER) as client:
            session = signed_in(client, account.email)
            session_token = session["Cookie"].split("=", 1)[1]
            code = consent(client, session)["code"]
            issued = exchange(client, code)
            rotated = refresh(client, str(issued["refresh_token"]))
            second = rotated.json()["refresh_token"]
            # A replay, a refusal, and a revocation, so the warning and error paths log too.
            refresh(client, str(issued["refresh_token"]))
            client.post(REVOKE, data={"token": second, "client_id": CLI_CLIENT_ID})
            client.post(
                DECISION,
                data={**authorize_query(), DECISION_FIELD: DECISION_DENY},
                headers={**session, "Origin": BROWSER_ORIGIN},
                follow_redirects=False,
            )
    finally:
        remove_tenant(live_database_url, account.tenant_id)
        configure_logging(environment="test", log_level="info")

    logged = stream.getvalue()
    assert logged, "nothing was logged, so this asserts nothing"
    secrets = {
        "the authorization code": code,
        "the access token": str(issued["access_token"]),
        "the first refresh token": str(issued["refresh_token"]),
        "the rotated refresh token": str(second),
        "the session token": session_token,
        "the pkce verifier": VERIFIER,
        "the account password": PASSWORD,
    }
    for name, secret in secrets.items():
        assert secret not in logged, f"{name} reached a log line"
    # Every line is JSON with a dotted event name, and the identifiers a diagnosis needs are
    # there: this is the control that the assertions above are not passing on an empty stream.
    events = [json.loads(line)["event"] for line in logged.splitlines() if line.startswith("{")]
    assert "oauth.consent.granted" in events
    assert "oauth.token.issued" in events
    assert "oauth.refresh.replay_detected" in events
    assert "oauth.revoke.completed" in events
    assert "oauth.consent.refused" in events
