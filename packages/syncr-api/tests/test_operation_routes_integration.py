"""The two operation routes end to end, against a real Postgres and a real request.

The lifecycle suite proves the machine with real rows. This proves what only a real request can:
that the wire shape is camelCase, that a superseded operation reads differently from a failed one on
the wire and not merely in a table, that another tenant's identifier is a 404 rather than a status,
that both filters are closed vocabularies, and that the page cursor walks the list without skipping
or repeating a row.

There is deliberately no route that creates or steps an operation, and that absence is asserted:
"we did not add a write route" is a claim that decays the moment someone needs one.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.solving.config import (
    CALENDAR_SYNC,
    FAILED,
    OPERATION_KINDS,
    OPERATION_STATUSES,
    OPERATIONS_PREFIX,
    PAGE_LIMIT_MAX,
    PENDING,
    SOLVE,
    SUPERSEDED,
)
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.outcomes import Failed, Superseded
from syncr_api.solving.reporting import statement
from syncr_api.solving.repository import OperationRepository
from syncr_domain.weeks import IsoWeek
from tests.boundaries import api_routes, route_identity
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.solving.outcomes import Outcome
    from syncr_api.solving.records import OperationRecord
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
WEEK = IsoWeek(2026, 7)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def other_owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    """A client against an app wired to the live database, as the process wires it."""
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    return _sign_in(http, owner.email)


def _sign_in(http: TestClient, email: str) -> dict[str, str]:
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def seed_operation(
    database_url: str,
    tenant_id: TenantId,
    *,
    kind: str = SOLVE,
    week: IsoWeek | None = WEEK,
    outcome: Outcome | None = None,
    at: datetime = NOW,
) -> OperationRecord:
    """One operation of this tenant's, stepped to ``outcome`` when one is given.

    Seeded through the lifecycle service rather than by inserting a row, so every operation these
    routes report has taken the steps the machine names.
    """

    async def write() -> OperationRecord:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                lifecycle = OperationLifecycle(OperationRepository(session, tenant_id), lambda: at)
                created = await lifecycle.enqueue(
                    kind=kind,  # type: ignore[arg-type]
                    iso_week=week,
                    source_id=None if week is not None else uuid4(),
                )
                if outcome is None:
                    return created
                if not isinstance(outcome, Superseded):
                    await lifecycle.claim(created.id)
                return await lifecycle.finish(created.id, outcome)
        finally:
            await database.engine.dispose()

    return run(write())


def read(http: TestClient, headers: dict[str, str], **query: Any) -> tuple[int, dict[str, Any]]:
    answered = http.get(OPERATIONS_PREFIX, params=query, headers=headers)
    return answered.status_code, answered.json()


# --------------------------------------------------------------------------------
# One operation by identifier
# --------------------------------------------------------------------------------


def test_an_operation_reports_its_status_by_identifier(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = seed_operation(live_database_url, owner.tenant_id)

    answered = http.get(f"{OPERATIONS_PREFIX}/{created.id}", headers=signed_in)

    assert answered.status_code == HTTPStatus.OK, answered.text
    body = answered.json()
    assert body["id"] == str(created.id)
    assert body["status"] == PENDING
    assert body["kind"] == SOLVE
    assert body["target"] == {"isoWeek": str(WEEK), "sourceId": None}
    assert body["attempt"] == 1
    assert body["inputVersion"] is None, "stamped when the worker loads inputs, not at creation"
    assert body["statement"] == statement(PENDING)


def test_a_superseded_operation_is_reported_distinctly_from_a_failed_one(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    """The word and the sentence differ on the wire, which is where the user meets them.

    A superseded solve is the expected outcome of editing quickly, so reporting it as a failure
    would make normal use look broken.
    """
    displaced = seed_operation(live_database_url, owner.tenant_id, outcome=Superseded())
    broken = seed_operation(
        live_database_url,
        owner.tenant_id,
        week=IsoWeek(2026, 8),
        outcome=Failed(code="solver_raised", message="the solver raised"),
    )

    one = http.get(f"{OPERATIONS_PREFIX}/{displaced.id}", headers=signed_in).json()
    other = http.get(f"{OPERATIONS_PREFIX}/{broken.id}", headers=signed_in).json()

    assert one["status"] == SUPERSEDED
    assert other["status"] == PENDING, "a first failure has an attempt left, so it is queued again"
    assert one["statement"] != other["statement"]
    assert one["error"] is None, "supersession is not an error and carries no code"


def test_a_terminal_failure_states_its_cause_and_what_still_works(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = seed_operation(live_database_url, owner.tenant_id)
    for _ in range(3):
        _step(
            live_database_url, owner.tenant_id, created, Failed(code="solver_raised", message="x")
        )

    body = http.get(f"{OPERATIONS_PREFIX}/{created.id}", headers=signed_in).json()

    assert body["status"] == FAILED
    assert body["attempt"] == 3
    assert body["error"] == {"code": "solver_raised", "message": "x"}
    assert "still projected" in body["statement"]


def test_another_tenants_operation_is_a_404(
    http: TestClient,
    signed_in: dict[str, str],
    other_owner: UserRecord,
    live_database_url: str,
) -> None:
    theirs = seed_operation(live_database_url, other_owner.tenant_id)

    answered = http.get(f"{OPERATIONS_PREFIX}/{theirs.id}", headers=signed_in)

    assert answered.status_code == HTTPStatus.NOT_FOUND


def test_an_identifier_nothing_matches_is_a_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    answered = http.get(f"{OPERATIONS_PREFIX}/{uuid4()}", headers=signed_in)

    assert answered.status_code == HTTPStatus.NOT_FOUND


def test_reading_an_operation_needs_a_credential(http: TestClient) -> None:
    answered = http.get(f"{OPERATIONS_PREFIX}/{uuid4()}", headers={"Origin": BROWSER_ORIGIN})

    assert answered.status_code == HTTPStatus.UNAUTHORIZED


# --------------------------------------------------------------------------------
# The list
# --------------------------------------------------------------------------------


def test_the_list_reports_this_tenants_operations_newest_first(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    earlier = seed_operation(live_database_url, owner.tenant_id, at=NOW)
    later = seed_operation(
        live_database_url, owner.tenant_id, week=IsoWeek(2026, 8), at=NOW.replace(hour=10)
    )

    status, body = read(http, signed_in)

    assert status == HTTPStatus.OK, body
    assert [one["id"] for one in body["operations"]] == [str(later.id), str(earlier.id)]
    assert body["nextCursor"] is None


def test_the_list_holds_no_other_tenants_operations(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    other_owner: UserRecord,
    live_database_url: str,
) -> None:
    mine = seed_operation(live_database_url, owner.tenant_id)
    seed_operation(live_database_url, other_owner.tenant_id)

    _status, body = read(http, signed_in)

    assert [one["id"] for one in body["operations"]] == [str(mine.id)]


def test_the_list_filters_by_status(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    queued = seed_operation(live_database_url, owner.tenant_id)
    seed_operation(live_database_url, owner.tenant_id, week=IsoWeek(2026, 8), outcome=Superseded())

    _status, body = read(http, signed_in, status=PENDING)

    assert [one["id"] for one in body["operations"]] == [str(queued.id)]


def test_the_list_filters_by_kind(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    sync = seed_operation(live_database_url, owner.tenant_id, kind=CALENDAR_SYNC, week=None)
    seed_operation(live_database_url, owner.tenant_id)

    _status, body = read(http, signed_in, kind=CALENDAR_SYNC)

    assert [one["id"] for one in body["operations"]] == [str(sync.id)]


def test_a_status_no_operation_can_hold_is_refused_rather_than_answered_empty(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    """An empty page would tell the user they have no operations, which is a different claim."""
    status, body = read(http, signed_in, status="done")

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert ", ".join(OPERATION_STATUSES) in body["detail"]


def test_a_kind_no_operation_can_hold_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    status, body = read(http, signed_in, kind="reticulate")

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert ", ".join(OPERATION_KINDS) in body["detail"]


def test_the_cursor_walks_the_list_without_skipping_or_repeating(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    seeded = [
        seed_operation(
            live_database_url,
            owner.tenant_id,
            week=IsoWeek(2026, week),
            at=NOW.replace(hour=8 + week),
        )
        for week in (7, 8, 9)
    ]
    newest_first = [str(one.id) for one in reversed(seeded)]

    walked: list[str] = []
    cursor: str | None = None
    for _ in range(len(seeded)):
        query: dict[str, Any] = {"limit": 1} | ({"cursor": cursor} if cursor else {})
        _status, body = read(http, signed_in, **query)
        walked += [one["id"] for one in body["operations"]]
        cursor = body["nextCursor"]

    assert walked == newest_first
    assert cursor is None, "the last page hands back no cursor"


def test_a_page_cursor_this_api_did_not_mint_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    status, body = read(http, signed_in, cursor="not-a-cursor")

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "page cursor" in body["detail"]


def test_a_page_larger_than_the_maximum_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    status, _body = read(http, signed_in, limit=PAGE_LIMIT_MAX + 1)

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY


def test_no_route_creates_or_steps_an_operation(settings: ServiceSettings) -> None:
    """An operation is created by the mutation whose work it tracks, and by nothing else.

    Asserted over the app's own route table rather than by reading ``api.py``, so a write route
    added through any wiring fails here.
    """
    answered = {
        pair
        for route in api_routes(create_app(settings))
        if route.path.startswith(OPERATIONS_PREFIX)
        for pair in route_identity(route)
    }

    assert answered, "the operation routes were not registered at all"
    assert {method for method, _path in answered} == {"GET"}, answered


def _step(
    database_url: str, tenant_id: TenantId, operation: OperationRecord, outcome: Outcome
) -> None:
    async def write() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                lifecycle = OperationLifecycle(OperationRepository(session, tenant_id), lambda: NOW)
                await lifecycle.claim(operation.id)
                await lifecycle.finish(operation.id, outcome)
        finally:
            await database.engine.dispose()

    run(write())
