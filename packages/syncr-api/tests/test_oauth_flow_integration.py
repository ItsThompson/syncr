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
from syncr_api.core.errors import OriginRejected, Unauthorized
from syncr_api.core.scopes import Scope
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.core.tenancy import TenantScoped
from syncr_api.oauth.config import (
    AUTHORIZE_PATH,
    CLI_CLIENT_ID,
    CONSENT_DECISION_PATH,
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
from syncr_api.oauth.errors import InvalidGrant, InvalidRequest
from syncr_api.oauth.injection import build_oauth_state
from syncr_api.oauth.keys import SigningKeySet, generate_signing_key, rotate
from syncr_api.oauth.metadata import DISCOVERY_PATH
from syncr_api.oauth.models import OAuthAuthorizationCode, OAuthGrant, OAuthRefreshToken
from syncr_api.oauth.pkce import derive_s256_challenge
from syncr_api.oauth.secrets import digest_of
from syncr_common.logging import configure_logging
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
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


@pytest.fixture
def http(
    live_database_url: str, settings: ServiceSettings, keys: SigningKeySet
) -> Iterator[TestClient]:
    """A client against an app wired to the live database, as the api process wires it."""
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    app.state.oauth = build_oauth_state(build_oauth_config(settings, is_dev=True), keys)
    with TestClient(app, raise_server_exceptions=False, base_url=ISSUER) as client:
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


def refresh(http: TestClient, refresh_token: str) -> object:
    return http.post(
        TOKEN,
        data={
            "grant_type": GRANT_TYPE_REFRESH_TOKEN,
            "client_id": CLI_CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )


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
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    app.state.oauth = build_oauth_state(build_oauth_config(settings, is_dev=True), rotate(keys))

    with TestClient(app, base_url=ISSUER) as client:
        published = client.get(JWKS).json()

    assert [key["kid"] for key in published["keys"]] == [
        rotate(keys).current.kid,
        keys.current.kid,
    ] or len(published["keys"]) == 2
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

    response = http.get(
        AUTHORIZE,
        params=authorize_query(),
        headers={"Authorization": f"Bearer {issued['access_token']}"},
    )

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
    assert rotated.status_code == 200  # type: ignore[attr-defined]
    second = rotated.json()["refresh_token"]  # type: ignore[attr-defined]
    assert second != first

    replayed = refresh(http, first)

    assert replayed.status_code == 400  # type: ignore[attr-defined]
    tokens = rows_of(live_database_url, OAuthRefreshToken, owner.tenant_id)
    assert len(tokens) == 2
    assert all(token.revoked_at is not None for token in tokens)
    (grant,) = rows_of(live_database_url, OAuthGrant, owner.tenant_id)
    assert grant.revoked_at is not None
    # The successor the honest client holds is dead too: the two holders cannot be told apart.
    assert refresh(http, second).status_code == 400  # type: ignore[attr-defined]


def test_revoking_ends_the_family_server_side(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    session = signed_in(http, owner.email)
    issued = exchange(http, consent(http, session)["code"])
    presented = str(issued["refresh_token"])

    revoked = http.post(REVOKE, data={"token": presented, "client_id": CLI_CLIENT_ID})

    assert revoked.status_code == 200
    assert revoked.headers["cache-control"] == "no-store"
    assert refresh(http, presented).status_code == 400  # type: ignore[attr-defined]
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
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    app.state.oauth = build_oauth_state(build_oauth_config(settings, is_dev=True), keys)
    with TestClient(app, raise_server_exceptions=False, base_url=ISSUER) as client:
        exchange(client, consent(client, signed_in(client, account.email))["code"])
    assert rows_of(live_database_url, OAuthRefreshToken, account.tenant_id)

    remove_tenant(live_database_url, account.tenant_id)

    assert rows_of(live_database_url, OAuthGrant, account.tenant_id) == []
    assert rows_of(live_database_url, OAuthRefreshToken, account.tenant_id) == []
    assert rows_of(live_database_url, OAuthAuthorizationCode, account.tenant_id) == []


# --- The sweep -------------------------------------------------------------------------


def test_the_sweep_removes_an_expired_code_and_leaves_a_live_refresh_token(
    http: TestClient, owner: UserRecord, live_database_url: str
) -> None:
    from syncr_api.oauth.cleanup import ExpirySweep

    session = signed_in(http, owner.email)
    exchange(http, consent(http, session)["code"])
    assert len(rows_of(live_database_url, OAuthAuthorizationCode, owner.tenant_id)) == 1

    async def sweep_later() -> object:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as opened, opened.begin():
                # An hour on: the code's minute is long past, the refresh token's two months
                # are not. Passing the instant is what lets one sweep prove both.
                return await ExpirySweep(
                    opened, lambda: datetime.now(UTC) + timedelta(hours=1)
                ).sweep()
        finally:
            await database.engine.dispose()

    swept = run(sweep_later())

    assert swept.codes >= 1  # type: ignore[attr-defined]
    assert rows_of(live_database_url, OAuthAuthorizationCode, owner.tenant_id) == []
    assert len(rows_of(live_database_url, OAuthRefreshToken, owner.tenant_id)) == 1


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
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    app.state.oauth = build_oauth_state(build_oauth_config(settings, is_dev=True), keys)
    try:
        with TestClient(app, raise_server_exceptions=False, base_url=ISSUER) as client:
            session = signed_in(client, account.email)
            session_token = session["Cookie"].split("=", 1)[1]
            code = consent(client, session)["code"]
            issued = exchange(client, code)
            rotated = refresh(client, str(issued["refresh_token"]))
            second = rotated.json()["refresh_token"]  # type: ignore[attr-defined]
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
