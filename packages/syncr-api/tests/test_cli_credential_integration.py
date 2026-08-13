"""A CLI credential against real product routes, over HTTP and a real Postgres.

The bearer seam was first proved through a probe router. This proves the thing only the
real routes can: that a request presenting an access token reaches the routes the CLI's
command catalog needs, that it reaches none of the others, and that the two rules a bearer request
changes behave in both directions.

Every token here is issued through the real flow rather than constructed, because a constructed
principal proves that a service authorizes a value and says nothing about whether a request carrying
a token ever reaches that service. That was exactly the gap: the bearer seam existed and no product
route declared a dependency that resolved it, so ``syncr week show`` exited 3 against a running API
while every unit test about scopes passed.

Four rules, each driven both ways:

**A read reaches the CLI's routes with a token and with a cookie.** Same route, same body, two
credentials, so the perimeter's choice is the request's rather than the route's.

**A token whose grant lacks ``plan:write`` is refused on a write and serves a read.** The refusal is
``syncr:forbidden`` from the service layer, which is where authorization lives; one direction alone
would pass on a route that refused everything.

**A bearer request needs no ``Origin`` and a cookie request still does.** The exemption is the
credential's property, so a CLI mutation works with no origin at all while the same mutation with a
cookie and a hostile origin is refused. A request presenting BOTH is refused too, which is the only
case that holds the exemption's second conjunct: without it the cookie-only case still passes.

**A route outside the catalog refuses a token and serves the cookie.** The default is closed, and
this is what says the twelve are the whole of the exception rather than the first twelve of many.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.areas.repository import AreaRepository
from syncr_api.core.app_factory import create_app
from syncr_api.core.credentials import AUTHORIZATION_HEADER
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import Forbidden, Unauthorized
from syncr_api.core.scopes import Scope
from syncr_api.core.settings import API_PREFIX
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.oauth.config import build_oauth_config
from syncr_api.oauth.injection import build_oauth_state
from syncr_api.oauth.keys import SigningKeySet, generate_signing_key
from syncr_api.routines.config import ROUTINES_PREFIX
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_api.templates.config import DAY_TYPES_PREFIX
from tests.cli_credentials import BROWSER_ORIGIN, cli_bearer_header
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run
from tests.test_authorization_boundary import CLI_ROUTES

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx
    from fastapi import FastAPI

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

ISSUER = "http://testserver"
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
ISO_WEEK = "2026-W07"

WEEK_ROUTE = f"{API_PREFIX}/weeks/{ISO_WEEK}"
AREAS_ROUTE = AREAS_PREFIX
TASKS_ROUTE = TASKS_PREFIX
# A route the CLI ships no command for, in a package it does reach, so the refusal is the route's
# own perimeter rather than a whole router being closed.
TASK_ROUTE = f"{TASKS_PREFIX}/{uuid4()}"

# A route outside the catalog that also takes the idempotency guard, which resolves the
# either-credential perimeter as a sub-dependency. Its own browser-only declaration is what has to
# survive that.
DAY_TYPES_ROUTE = DAY_TYPES_PREFIX
ROUTINES_ROUTE = ROUTINES_PREFIX

# One guarded, browser-only route per feature module that declares the guard on a collection POST.
# Two rather than one, because the redundancy that makes the route's own declaration survivable is a
# property of each module's `injection.py` and not of the api.
GUARDED_AND_BROWSER_ONLY = {
    "day_type": (DAY_TYPES_ROUTE, {"name": "Weekday"}),
    "routine": (ROUTINES_ROUTE, {"title": "Sleep", "targetTime": "23:00", "durationMinutes": 480}),
}

# A hostile page's origin: not in the deployment's allowed set, and the shape a forged cross-origin
# request states.
HOSTILE_ORIGIN = "https://not-syncr.example"


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    """A tenant with the one Area a capture needs, created and then removed."""
    account = provision_owner(live_database_url)
    _seed_an_area(live_database_url, account)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def app(live_database_url: str, settings: ServiceSettings) -> FastAPI:
    """The whole application, wired to the live database and a key set, as the entrypoint does."""
    database = create_database(live_database_url)
    built = create_app(settings, lifespan=create_db_lifespan(database.engine))
    built.state.db = database
    built.state.oauth = build_oauth_state(
        build_oauth_config(settings, is_dev=True),
        SigningKeySet(current=generate_signing_key("cli-credential")),
    )
    return built


@pytest.fixture
def http(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False, base_url=ISSUER) as client:
        yield client


def test_a_cli_token_reads_a_week_and_the_areas_that_name_its_rows(
    http: TestClient, owner: UserRecord
) -> None:
    # The two reads `week show` makes. Both were 401 before a product route accepted a token, which
    # is the whole of what blocked the CLI's fourteen commands.
    token = cli_bearer_header(http, owner.email)

    week = http.get(WEEK_ROUTE, headers=token)
    areas = http.get(AREAS_ROUTE, headers=token)

    assert week.status_code == 200, week.text
    assert week.json()["isoWeek"] == ISO_WEEK
    assert areas.status_code == 200, areas.text
    assert [area["name"] for area in areas.json()["areas"]] == ["Career"]


def test_the_same_read_answers_a_cookie_too(http: TestClient, owner: UserRecord) -> None:
    # The other half: widening a route to the CLI must not narrow it for the browser, and the
    # perimeter picks by what the request presents rather than by what the route declares.
    cookie = _signed_in(http, owner.email)

    answered = http.get(WEEK_ROUTE, headers=cookie)

    assert answered.status_code == 200, answered.text
    assert answered.json()["isoWeek"] == ISO_WEEK


def test_a_token_without_plan_write_is_refused_on_a_write_and_serves_a_read(
    http: TestClient, owner: UserRecord
) -> None:
    # Both directions, so the assertion discriminates: a route that refused everything would pass
    # the first half alone. The refusal comes from the service layer's own scope check.
    narrow = cli_bearer_header(http, owner.email, scopes=(Scope.PLAN_READ,))

    refused = http.post(
        TASKS_ROUTE,
        json=_a_task(http, narrow),
        headers={**narrow, IDEMPOTENCY_KEY_HEADER: "cli-scope-probe"},
    )
    read = http.get(TASKS_ROUTE, headers=narrow)

    assert refused.status_code == Forbidden.status, refused.text
    assert refused.json()["type"] == Forbidden.type
    assert Scope.PLAN_WRITE.value in refused.json()["detail"]
    assert read.status_code == 200, read.text


def test_a_token_carrying_plan_write_captures_a_task_with_no_origin_at_all(
    http: TestClient, owner: UserRecord
) -> None:
    # The origin decision, asserted where it matters: the CLI is not a browser and sends no `Origin`
    # header, so requiring one would refuse every CLI mutation.
    token = cli_bearer_header(http, owner.email)

    captured = http.post(
        TASKS_ROUTE,
        json=_a_task(http, token),
        headers={**token, IDEMPOTENCY_KEY_HEADER: "cli-capture-1"},
    )

    assert captured.status_code == 201, captured.text
    assert captured.json()["title"] == "Leetcode"


def test_the_same_write_with_a_cookie_and_a_hostile_origin_is_still_refused(
    http: TestClient, owner: UserRecord
) -> None:
    # The exemption belongs to the credential, not to the route. A cookie is ambient, so the same
    # mutation carrying one is checked, and this is what says the exemption opened no CSRF hole.
    cookie = _signed_in(http, owner.email)
    token = cli_bearer_header(http, owner.email)

    forged = http.post(
        TASKS_ROUTE,
        json=_a_task(http, token),
        headers={**cookie, "Origin": HOSTILE_ORIGIN},
    )

    assert forged.status_code == 403, forged.text
    assert forged.json()["type"] == "syncr:origin-rejected"


def test_a_write_presenting_both_credentials_and_a_hostile_origin_is_refused(
    http: TestClient, owner: UserRecord
) -> None:
    """The case that holds the exemption's second clause, and the only one that can.

    ``require_trusted_origin`` exempts a request only when it presents a bearer token **and no
    cookie**. The cookie-only test above passes with that second conjunct deleted, because such a
    request is not a bearer request at all; so does the whole api suite. What discriminates is a
    request carrying BOTH, which is the shape the conjunct exists for: the bearer half is what
    resolves it, and the cookie is still ambient, so the check has something left to protect.

    Not currently exploitable: a hostile page cannot attach ``Authorization`` cross-origin without a
    preflight this deployment refuses, there being no CORS middleware anywhere in the api. The rule
    was written deliberately, so it is asserted rather than reasoned about.
    """
    cookie = _signed_in(http, owner.email)
    token = cli_bearer_header(http, owner.email)

    forged = http.post(
        TASKS_ROUTE,
        json=_a_task(http, token),
        headers={**cookie, **token, "Origin": HOSTILE_ORIGIN},
    )

    assert forged.status_code == 403, forged.text
    assert forged.json()["type"] == "syncr:origin-rejected"


def test_a_write_presenting_both_credentials_and_a_trusted_origin_is_applied(
    http: TestClient, owner: UserRecord
) -> None:
    # The other direction, so the case above cannot pass by refusing every request that carries two
    # credentials: with an origin this deployment serves, the same request is applied.
    cookie = _signed_in(http, owner.email)
    token = cli_bearer_header(http, owner.email)

    applied = http.post(
        TASKS_ROUTE,
        json=_a_task(http, token),
        headers={
            **cookie,
            **token,
            "Origin": BROWSER_ORIGIN,
            IDEMPOTENCY_KEY_HEADER: "cli-both-credentials",
        },
    )

    assert applied.status_code == 201, applied.text


def test_a_route_outside_the_catalog_refuses_a_token_and_serves_the_cookie(
    http: TestClient, owner: UserRecord
) -> None:
    # The default is closed. `GET /tasks/{id}` sits in a package the CLI reaches and ships no
    # command, so a token is refused there while the browser reads it: the answer is the route's
    # perimeter rather than a router that turned the CLI away wholesale.
    token = cli_bearer_header(http, owner.email)
    cookie = _signed_in(http, owner.email)

    refused = http.get(TASK_ROUTE, headers=token)
    browser = http.get(TASK_ROUTE, headers=cookie)

    assert refused.status_code == Unauthorized.status, refused.text
    assert refused.json()["type"] == Unauthorized.type
    # 404 rather than 200: the identifier names no task of this tenant. What matters is that the
    # browser got past the perimeter the token did not.
    assert browser.status_code == 404, browser.text


@pytest.mark.parametrize(
    ("route", "declared"), GUARDED_AND_BROWSER_ONLY.values(), ids=GUARDED_AND_BROWSER_ONLY.keys()
)
def test_a_guarded_route_outside_the_catalog_refuses_a_token_and_serves_the_cookie(
    http: TestClient, owner: UserRecord, route: str, declared: dict[str, object]
) -> None:
    # The same default, on a route that takes the idempotency guard. The guard resolves the
    # either-credential perimeter for itself, so a guarded route declaring the browser-only one
    # resolves both, and this is what says the second did not widen the first. A token getting past
    # would answer 403 from the scope check rather than 401, so the assertion discriminates.
    token = cli_bearer_header(http, owner.email)
    cookie = _signed_in(http, owner.email)

    refused = http.post(
        route, json=declared, headers={**token, IDEMPOTENCY_KEY_HEADER: f"cli-{route}"}
    )
    browser = http.post(
        route,
        json=declared,
        headers={**cookie, "Origin": BROWSER_ORIGIN, IDEMPOTENCY_KEY_HEADER: f"browser-{route}"},
    )

    assert refused.status_code == Unauthorized.status, refused.text
    assert refused.json()["type"] == Unauthorized.type
    assert browser.status_code == 201, browser.text


def test_every_route_in_the_catalog_gets_past_the_perimeter_with_a_token(
    http: TestClient, owner: UserRecord
) -> None:
    """The inventory, driven rather than read off the dependency tree.

    ``test_authorization_boundary.py`` asserts which routes DECLARE the either-credential perimeter;
    this asserts that declaring it is enough to be served, over the same inventory. A route whose
    service or guard still resolved the browser-only perimeter would answer 401 here while the
    census read green, which is how a shared dependency silently closes a route that looks open.

    Only the perimeter is under test, so any answer other than 401 or 403 passes: a mutation with a
    made-up identifier legitimately answers 404 or 422, and driving each route's own semantics is
    what the twelve suites that own them already do.
    """
    token = cli_bearer_header(http, owner.email)
    assert CLI_ROUTES, "the catalog is empty, so this asserted nothing"

    refused = {
        f"{method} {path}": answered.status_code
        for method, path in sorted(CLI_ROUTES)
        if (answered := _drive(http, method, path, token)).status_code
        in {Unauthorized.status, Forbidden.status}
    }

    assert refused == {}


def _drive(http: TestClient, method: str, path: str, token: dict[str, str]) -> httpx.Response:
    """One request at ``path``, with every path parameter filled in with something plausible."""
    filled = (
        path.replace("{iso_week}", ISO_WEEK)
        .replace("{task_id}", str(uuid4()))
        .replace("{operation_id}", str(uuid4()))
        .replace("{block_id}", "a-block-that-does-not-exist")
        .replace("{date}", "2026-02-10")
    )
    # Annotated on the way out rather than cast: `TestClient` is typed loosely enough that the
    # response is `Any`, and the caller reads its status.
    answered: httpx.Response = http.request(
        method,
        filled,
        json={} if method in {"POST", "PUT", "PATCH"} else None,
        headers={**token, IDEMPOTENCY_KEY_HEADER: f"cli-perimeter-{method}-{filled}"},
    )
    return answered


def _a_task(http: TestClient, token: dict[str, str]) -> dict[str, object]:
    """A capture body naming the Area this tenant holds."""
    areas = http.get(AREAS_ROUTE, headers=token)
    assert areas.status_code == 200, areas.text
    return {"areaId": areas.json()["areas"][0]["id"], "title": "Leetcode"}


def _signed_in(http: TestClient, email: str) -> dict[str, str]:
    """The cookie header a signed-in browser sends."""
    response = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert response.status_code == 200, response.text
    token = response.headers["set-cookie"].split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


def _seed_an_area(database_url: str, account: UserRecord) -> None:
    """One Area, which is what a capture needs and what the ledger names a row by."""

    async def written() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await AreaRepository(session, account.tenant_id).create(
                    parent_id=None,
                    name="Career",
                    pigment_index=1,
                    budget_percent=Decimal(30),
                    floor_hours=Decimal(3),
                    created_at=NOW,
                )
        finally:
            await database.engine.dispose()

    run(written())


def test_the_bearer_header_this_module_sends_is_the_one_the_perimeter_reads() -> None:
    # The instrument's own precondition. Every assertion above rests on the header name, and a test
    # that sent `Authorisation` would report the perimeter refusing a token it never saw.
    assert AUTHORIZATION_HEADER == "authorization"
