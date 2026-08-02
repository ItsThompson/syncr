"""The three auth routes end to end, against a real Postgres.

The service suite proves the rules with fakes and an injected clock. This proves the
things only a real request and a real database can: what the ``Set-Cookie`` header
actually says, that the row is committed rather than merely written, that a second client
holding only the cookie is signed in, and that sign-out makes that same cookie useless.

Every test seeds its own tenant with a unique email and removes it afterwards, so the
suite does not depend on an empty database and does not leave rows in a developer's.

The cookie is replayed by setting the header rather than by using the client's cookie
jar. The cookie is ``Secure``, and an HTTP client that honors that attribute will not
send it back over ``http://testserver``: the browsers that matter treat localhost as a
secure origin, but the test client is not one of them.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from syncr_api.accounts.config import (
    AUTH_PREFIX,
    SESSION_ABSOLUTE_LIFETIME,
    SESSION_COOKIE_NAME,
    SESSION_IDLE_TIMEOUT,
)
from syncr_api.accounts.models import BrowserSession, Tenant
from syncr_api.accounts.provisioning import AccountProvisioner
from syncr_api.accounts.repository import UserRepository
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import OriginRejected, Unauthorized
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS

if TYPE_CHECKING:
    from collections.abc import Coroutine, Iterator

    from syncr_api.accounts.provisioning import ProvisionedAccount
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"  # pragma: allowlist secret
BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

LOGIN = f"{AUTH_PREFIX}/login"
SESSION = f"{AUTH_PREFIX}/session"
LOGOUT = f"{AUTH_PREFIX}/logout"


def run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    """Run one coroutine on a loop of its own, disposing everything it opened.

    The application under test runs in the test client's loop, and an asyncpg connection
    belongs to the loop that opened it, so a fixture that seeds or inspects the database
    keeps its own loop and its own engine rather than sharing either.
    """
    return asyncio.run(coroutine)


@pytest.fixture
def owner(live_database_url: str) -> Iterator[ProvisionedAccount]:
    """A tenant and its one user, created and then removed.

    Created through the same provisioner ``just bootstrap-user`` runs, so the password
    the tests sign in with was hashed by the code that will hash the real one.
    """
    email = f"owner-{uuid4().hex}@syncr.test"

    async def seed() -> ProvisionedAccount:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                provisioner = AccountProvisioner(users=UserRepository(session), clock=utc_now)
                return await provisioner.provision(email, PASSWORD)
        finally:
            await database.engine.dispose()

    account = run(seed())
    yield account

    async def remove() -> None:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await session.execute(delete(Tenant).where(Tenant.id == account.tenant_id))
        finally:
            await database.engine.dispose()

    run(remove())


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    """A client against an app wired to the live database, as the process wires it."""
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def sign_in(http: TestClient, email: str, password: str = PASSWORD) -> tuple[int, dict[str, str]]:
    """POST the credentials and hand back the status and the response headers."""
    response = http.post(
        LOGIN,
        json={"email": email, "password": password},
        headers={"Origin": BROWSER_ORIGIN},
    )
    return response.status_code, dict(response.headers)


def token_from(headers: dict[str, str]) -> str:
    """The session token the ``Set-Cookie`` header carries."""
    cookie = headers["set-cookie"]
    return cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]


def session_rows(live_database_url: str, tenant_id: TenantId) -> list[BrowserSession]:
    """The tenant's session rows, read on a connection of this fixture's own."""

    async def read() -> list[BrowserSession]:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(BrowserSession).where(BrowserSession.tenant_id == tenant_id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def test_signing_in_answers_the_principal_and_sets_the_session_cookie(
    http: TestClient, owner: ProvisionedAccount
) -> None:
    response = http.post(
        LOGIN,
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenantId"] == str(owner.tenant_id)
    assert body["userId"] == str(owner.user_id)
    assert body["email"] == owner.email
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]


def test_the_cookie_is_httponly_secure_lax_and_persistent(
    http: TestClient, owner: ProvisionedAccount
) -> None:
    _status, headers = sign_in(http, owner.email)

    cookie = headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    # Persistent rather than a session cookie, which is what makes the session survive
    # quitting the browser rather than being discarded with the window.
    assert "max-age=" in cookie


def test_the_cookie_expires_with_the_idle_window_not_the_absolute_cap(
    http: TestClient, owner: ProvisionedAccount
) -> None:
    _status, headers = sign_in(http, owner.email)

    max_age = int(headers["set-cookie"].split("Max-Age=", 1)[1].split(";", 1)[0])
    assert max_age == pytest.approx(SESSION_IDLE_TIMEOUT.total_seconds(), abs=5)
    assert max_age < SESSION_ABSOLUTE_LIFETIME.total_seconds()


def test_no_response_body_carries_the_token(http: TestClient, owner: ProvisionedAccount) -> None:
    response = http.post(
        LOGIN,
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    token = token_from(dict(response.headers))

    assert token not in response.text


def test_the_session_row_is_committed_and_holds_no_token(
    http: TestClient, owner: ProvisionedAccount, live_database_url: str
) -> None:
    # Read on a separate connection, so this asserts the request's transaction committed
    # rather than that the write reached a session that was about to roll back.
    _status, headers = sign_in(http, owner.email)
    token = token_from(headers)

    (row,) = session_rows(live_database_url, owner.tenant_id)
    assert row.tenant_id == owner.tenant_id
    assert row.user_id == owner.user_id
    assert row.revoked_at is None
    assert token not in row.id


def test_a_wrong_password_answers_401_problem_details(
    http: TestClient, owner: ProvisionedAccount
) -> None:
    response = http.post(
        LOGIN,
        json={"email": owner.email, "password": "not the password"},  # pragma: allowlist secret
        headers={"Origin": BROWSER_ORIGIN},
    )

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == Unauthorized.type


def test_an_unknown_email_answers_the_same_401(http: TestClient) -> None:
    response = http.post(
        LOGIN,
        json={"email": "nobody@syncr.test", "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in to continue."


def test_the_session_route_answers_401_without_a_cookie(http: TestClient) -> None:
    response = http.get(SESSION)

    assert response.status_code == 401
    assert response.json()["type"] == Unauthorized.type


def test_a_reload_finds_the_session_still_valid(
    http: TestClient, owner: ProvisionedAccount
) -> None:
    _status, headers = sign_in(http, owner.email)
    cookie = {"Cookie": f"{SESSION_COOKIE_NAME}={token_from(headers)}"}

    first = http.get(SESSION, headers=cookie)
    second = http.get(SESSION, headers=cookie)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_a_restarted_browser_carrying_only_the_cookie_is_signed_in(
    http: TestClient, owner: ProvisionedAccount, live_database_url: str, settings: ServiceSettings
) -> None:
    # A browser restart keeps the persistent cookie and nothing else: no in-memory state,
    # no connection, and a new client. So does this.
    _status, headers = sign_in(http, owner.email)
    token = token_from(headers)

    database = create_database(live_database_url)
    restarted = create_app(settings, lifespan=create_db_lifespan(database.engine))
    restarted.state.db = database
    with TestClient(restarted) as after_restart:
        response = after_restart.get(SESSION, headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})

    assert response.status_code == 200
    assert response.json()["email"] == owner.email


def test_signing_out_revokes_the_session_so_the_cookie_cannot_be_replayed(
    http: TestClient, owner: ProvisionedAccount, live_database_url: str
) -> None:
    _status, headers = sign_in(http, owner.email)
    cookie = {"Cookie": f"{SESSION_COOKIE_NAME}={token_from(headers)}"}

    signed_out = http.post(LOGOUT, headers={**cookie, "Origin": BROWSER_ORIGIN})
    replayed = http.get(SESSION, headers=cookie)

    assert signed_out.status_code == 204
    assert signed_out.content == b""
    assert replayed.status_code == 401
    (row,) = session_rows(live_database_url, owner.tenant_id)
    assert row.revoked_at is not None


def test_signing_out_clears_the_cookie_in_the_browser_too(
    http: TestClient, owner: ProvisionedAccount
) -> None:
    _status, headers = sign_in(http, owner.email)

    response = http.post(
        LOGOUT,
        headers={
            "Cookie": f"{SESSION_COOKIE_NAME}={token_from(headers)}",
            "Origin": BROWSER_ORIGIN,
        },
    )

    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_signing_out_without_a_session_answers_401(http: TestClient) -> None:
    response = http.post(LOGOUT, headers={"Origin": BROWSER_ORIGIN})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://evil.test"},
        {"Referer": "https://evil.test/attack"},
    ],
    ids=["no origin", "another origin", "another referer"],
)
def test_an_unsafe_request_from_an_untrusted_origin_is_rejected(
    http: TestClient, owner: ProvisionedAccount, headers: dict[str, str]
) -> None:
    response = http.post(LOGIN, json={"email": owner.email, "password": PASSWORD}, headers=headers)

    assert response.status_code == 403
    assert response.json()["type"] == OriginRejected.type


def test_a_read_needs_no_origin_header(http: TestClient, owner: ProvisionedAccount) -> None:
    # The origin check is about forged state changes. Rejecting reads would break the
    # healthcheck, the deploy gate, and the external probe, none of which sends one.
    _status, headers = sign_in(http, owner.email)

    response = http.get(SESSION, headers={"Cookie": f"{SESSION_COOKIE_NAME}={token_from(headers)}"})

    assert response.status_code == 200


def test_a_forged_token_is_rejected(http: TestClient, owner: ProvisionedAccount) -> None:
    # Signed in first, so a real session exists and this asserts the digest lookup rather
    # than an empty table.
    sign_in(http, owner.email)

    response = http.get(
        SESSION, headers={"Cookie": f"{SESSION_COOKIE_NAME}=syncrs_not-a-token-this-server-minted"}
    )

    assert response.status_code == 401


def test_a_malformed_sign_in_body_answers_422_problem_details(http: TestClient) -> None:
    response = http.post(LOGIN, json={"email": "x"}, headers={"Origin": BROWSER_ORIGIN})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["errors"]
