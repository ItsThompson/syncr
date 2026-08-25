"""The five backlog routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a real
database can: that a two-value capture is stored with every default filled, that a refused
declaration is not stored, that the header's counts are computed in the database rather than from
the page, that an idempotency key replays a capture instead of creating a second row, and that
another tenant's identifier is a 404 rather than an edit.

Three tests are worth reading. ``test_a_field_that_would_carry_a_preferred_time_is_refused`` covers
the one field that must not exist: preferred times are a ``Preference``, so a task inherits its
Area's windows unless it overrides them. The chunk-bound test asserts the rejection comes from the
DOMAIN rather than from the schema, by validating the same body through the request schema and
finding it accepted there. ``test_the_week_input_version_is_bumped_by_every_mutating_route`` reads
the counter row itself.

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
from sqlalchemy import select, update

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX, PROJECTS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, Conflict, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.plans.models import WeekInputVersion
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_api.tasks.models import TaskRow
from syncr_api.tasks.schemas import TaskCreateRequest
from syncr_domain.tasks import (
    DEFAULT_ESTIMATE_MINUTES,
    DEFAULT_MIN_CHUNK_MINUTES,
    Priority,
    TaskStatus,
    is_eligible_for_solving,
    remaining_minutes,
)
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
AREAS = AREAS_PREFIX
PROJECTS = PROJECTS_PREFIX
TASKS = TASKS_PREFIX

A_DEADLINE = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
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
    """The headers a signed-in browser sends: the session cookie and its origin."""
    return _sign_in(http, owner.email)


@pytest.fixture
def area(http: TestClient, signed_in: dict[str, str]) -> str:
    """One declared Area, because a task cannot exist without one."""
    return declare_area(http, signed_in, "Career")


def _sign_in(http: TestClient, email: str) -> dict[str, str]:
    response = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    cookie = response.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def declare_area(http: TestClient, headers: dict[str, str], name: str) -> str:
    response = http.post(AREAS, json={"name": name}, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    area_id: str = response.json()["area"]["id"]
    return area_id


def declare_project(http: TestClient, headers: dict[str, str], area_id: str) -> str:
    response = http.post(
        PROJECTS, json={"areaId": area_id, "name": f"Push {uuid4().hex[:6]}"}, headers=headers
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    project_id: str = response.json()["id"]
    return project_id


def capture(http: TestClient, headers: dict[str, str], **body: object) -> dict[str, Any]:
    """The task body a successful capture answers with.

    Typed loosely on purpose: every assertion below reads the JSON a real client receives, rather
    than a shape reconstructed from the schema it was serialized by.
    """
    response = http.post(TASKS, json=body, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    payload: dict[str, Any] = response.json()
    return payload


def task_rows(database_url: str, tenant_id: TenantId) -> list[TaskRow]:
    """The tenant's task rows, read on a connection of this test's own."""

    async def read() -> list[TaskRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(TaskRow)
                    .where(TaskRow.tenant_id == tenant_id)
                    .order_by(TaskRow.created_at, TaskRow.id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def version_rows(database_url: str, tenant_id: TenantId) -> dict[str, int]:
    """Each tracked week's input version, keyed by its identifier."""

    async def read() -> dict[str, int]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(WeekInputVersion).where(WeekInputVersion.tenant_id == tenant_id)
                )
                return {row.iso_week: row.version for row in found}
        finally:
            await database.engine.dispose()

    return run(read())


def track_week(database_url: str, tenant_id: TenantId, iso_week: str) -> None:
    """Give one week a version row, so a bump has something to enumerate.

    A week with no row is not tracked and needs no bump: it has no plan and no running solve to
    invalidate. Every bump assertion below therefore seeds a row first, which is also what the
    horizon maintainer does when it first solves a week.
    """

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                session.add(
                    WeekInputVersion(
                        tenant_id=tenant_id,
                        iso_week=iso_week,
                        version=1,
                        updated_at=datetime.now(tz=UTC),
                    )
                )
        finally:
            await database.engine.dispose()

    run(seed())


def record_progress(database_url: str, tenant_id: TenantId, minutes: int) -> None:
    """Record time against every one of the tenant's tasks.

    Written with SQL rather than through a route because NO route in this module writes
    ``recorded_minutes``: it accumulates from confirmed outcomes, which the outcome routes own.
    Seeding it here is how the read path over a partially completed task is asserted end to end.
    """

    async def write() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await session.execute(
                    update(TaskRow)
                    .where(TaskRow.tenant_id == tenant_id)
                    .values(recorded_minutes=minutes)
                )
        finally:
            await database.engine.dispose()

    run(write())


def this_week() -> str:
    """The ISO week the bump floors at.

    Computed from the UTC date, which agrees with the service only because a freshly provisioned
    tenant's home zone is ``UTC``: the service floors on today's LOCAL date in that home zone, and
    these tests never change it. If that default ever moves off UTC, resolve the zone here the way
    the service does rather than leaving these tests to fail inside a one-hour window.
    """
    today = datetime.now(tz=UTC).date()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


# --------------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------------


def test_the_tasks_route_needs_a_credential(http: TestClient) -> None:
    response = http.get(TASKS)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_capturing_with_two_values_fills_every_default_and_commits_it(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # Capture from any screen submits a title and an Area.
    created = capture(http, signed_in, areaId=area, title="Leetcode")

    assert created["title"] == "Leetcode"
    assert created["areaId"] == area
    assert created["projectId"] is None
    assert created["estimateMinutes"] == DEFAULT_ESTIMATE_MINUTES
    assert created["minChunkMinutes"] == DEFAULT_MIN_CHUNK_MINUTES
    assert created["priority"] == "normal"
    assert created["splittable"] is True
    assert created["deadline"] is None
    assert created["status"] == TaskStatus.OPEN.value
    assert created["recordedMinutes"] == 0
    assert created["remainingMinutes"] == DEFAULT_ESTIMATE_MINUTES
    assert created["completedAt"] is None
    # The rule the assembler will read: the captured row is eligible immediately.
    assert created["eligibleForSolving"] is True

    rows = task_rows(live_database_url, owner.tenant_id)
    assert [(row.title, row.status, row.recorded_minutes) for row in rows] == [
        ("Leetcode", TaskStatus.OPEN, 0)
    ]


def test_a_captured_row_satisfies_the_eligibility_predicate_the_assembler_will_use(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # Asked of the STORED row through the same two domain functions the week assembler will apply,
    # rather than of the response, so what is asserted is the row the assembler will read.
    capture(http, signed_in, areaId=area, title="Leetcode")

    [row] = task_rows(live_database_url, owner.tenant_id)

    assert (
        is_eligible_for_solving(
            status=row.status,
            remaining_minutes=remaining_minutes(
                estimate_minutes=row.estimate_minutes, recorded_minutes=row.recorded_minutes
            ),
        )
        is True
    )


def test_every_physics_value_can_be_stated_on_capture(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    created = capture(
        http,
        signed_in,
        areaId=area,
        title="Gym - Legs",
        estimateMinutes=90,
        minChunkMinutes=90,
        splittable=False,
        priority="high",
        deadline=A_DEADLINE.isoformat(),
    )

    assert created["estimateMinutes"] == 90
    assert created["minChunkMinutes"] == 90
    assert created["splittable"] is False
    assert created["priority"] == "high"
    assert created["deadline"] == A_DEADLINE.isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(
    "body",
    [
        {"title": "Leetcode", "preferredTimes": ["05:30", "13:15"]},
        {"title": "Leetcode", "preferredTime": "05:30"},
        {"title": "Leetcode", "windows": [{"start": "05:30", "end": "07:00"}]},
    ],
    ids=["preferredTimes", "preferredTime", "windows"],
)
def test_a_field_that_would_carry_a_preferred_time_is_refused(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
    body: dict[str, object],
) -> None:
    # A task inherits its Area's windows unless a Preference overrides them, so there is no field
    # here that could carry one and no column it could be stored in.
    response = http.post(TASKS, json={**body, "areaId": area}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    assert task_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize(
    "body",
    [
        {"status": "completed"},
        {"recordedMinutes": 30},
        {"completedAt": "2026-08-04T09:00:00Z"},
    ],
    ids=["a status", "recorded minutes", "a completion instant"],
)
def test_capture_refuses_the_fields_only_an_ending_or_an_outcome_may_set(
    http: TestClient, signed_in: dict[str, str], area: str, body: dict[str, object]
) -> None:
    response = http.post(
        TASKS, json={**body, "areaId": area, "title": "Leetcode"}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status, response.text


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"title": "x" * 121},
        {"title": "Leetcode", "estimateMinutes": 0},
        {"title": "Leetcode", "estimateMinutes": 10081},
        {"title": "Leetcode", "minChunkMinutes": 0},
        {"title": "Leetcode", "priority": "critical"},
        {"title": "Leetcode", "estimateMinutes": True},
        {"title": "Leetcode", "minChunkMinutes": True},
    ],
    ids=[
        "an empty title",
        "an over-long title",
        "an estimate of no minutes",
        "an estimate no week could hold",
        "a chunk of no minutes",
        "a priority outside the vocabulary",
        "a boolean where an estimate belongs",
        "a boolean where a chunk belongs",
    ],
)
def test_a_value_outside_its_declared_bounds_is_refused_rather_than_stored(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
    body: dict[str, object],
) -> None:
    response = http.post(TASKS, json={**body, "areaId": area}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    assert task_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize(
    "body",
    [
        {"estimateMinutes": 15, "minChunkMinutes": 15},
        {"estimateMinutes": 10080, "minChunkMinutes": 10080},
    ],
    ids=["a task of exactly one grid step", "a task the size of a nominal week"],
)
def test_a_value_at_its_bound_is_accepted(
    http: TestClient, signed_in: dict[str, str], area: str, body: dict[str, object]
) -> None:
    # The other half of the bound tests: a bound that refused its own edge would be off by one.
    created = capture(http, signed_in, areaId=area, title="Edge", **body)

    assert created["estimateMinutes"] == body["estimateMinutes"]


def test_a_minimum_chunk_above_the_estimate_is_a_422_from_the_domain(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # A chunk bound above the estimate. The second assertion is the load-bearing one: the SAME body
    # validates cleanly through the request schema, so the rejection is the domain's and the rule is
    # stated exactly once.
    body = {"areaId": area, "title": "Leetcode", "estimateMinutes": 60, "minChunkMinutes": 61}

    response = http.post(TASKS, json=body, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    problem = response.json()
    assert problem["type"] == ValidationFailed.type
    assert "does not fit" in problem["detail"]
    assert "Nothing was changed" in problem["detail"]
    assert [error["field"] for error in problem["errors"]] == [
        "minChunkMinutes",
        "estimateMinutes",
    ]
    assert task_rows(live_database_url, owner.tenant_id) == []

    accepted = TaskCreateRequest.model_validate(body)
    assert (accepted.estimate_minutes, accepted.min_chunk_minutes) == (60, 61)


def test_a_minimum_chunk_off_the_grid_is_a_422_naming_the_field(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # 25 clears the schema's floor of one grid step, so the refusal is the domain's: the same
    # rule a habit's minimum duration answers to, stated beside T1.
    body = {"areaId": area, "title": "Leetcode", "estimateMinutes": 90, "minChunkMinutes": 25}

    response = http.post(TASKS, json=body, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    problem = response.json()
    assert "does not land on the 15-minute grid" in problem["detail"]
    assert [error["field"] for error in problem["errors"]] == ["minChunkMinutes"]
    assert task_rows(live_database_url, owner.tenant_id) == []


def test_an_unknown_area_is_a_422_naming_the_field(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    response = http.post(
        TASKS, json={"areaId": str(uuid4()), "title": "Leetcode"}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status, response.text
    assert [error["field"] for error in response.json()["errors"]] == ["areaId"]
    assert task_rows(live_database_url, owner.tenant_id) == []


def test_a_project_in_another_area_is_a_422_naming_the_field(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    # A project in another Area, over HTTP: a comparison between two stored rows, so neither request
    # schema could make it.
    other = declare_area(http, signed_in, "Fitness")
    project = declare_project(http, signed_in, other)

    response = http.post(
        TASKS,
        json={"areaId": area, "title": "Leetcode", "projectId": project},
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status, response.text
    assert [error["field"] for error in response.json()["errors"]] == ["projectId"]


def test_a_project_in_the_same_area_is_accepted(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    project = declare_project(http, signed_in, area)

    created = capture(http, signed_in, areaId=area, title="Leetcode", projectId=project)

    assert created["projectId"] == project


# --------------------------------------------------------------------------------
# The list and its header
# --------------------------------------------------------------------------------


def test_the_header_states_the_open_count_and_a_zero_at_risk_count(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    # The at-risk count is the verdict's figure and the probe does not exist yet, so it is present
    # and zero rather than computed here: a second comparison would put a task at risk on one
    # screen and fine on another.
    capture(http, signed_in, areaId=area, title="one")
    capture(http, signed_in, areaId=area, title="two")

    header = http.get(TASKS, headers=signed_in).json()["header"]

    assert header == {"openCount": 2, "atRiskCount": 0}


def test_the_open_count_ignores_the_status_filter_and_honors_the_area_filter(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    other = declare_area(http, signed_in, "Fitness")
    capture(http, signed_in, areaId=area, title="career one")
    done = capture(http, signed_in, areaId=area, title="career two")
    capture(http, signed_in, areaId=other, title="fitness one")
    assert (
        http.post(f"{TASKS}/{done['id']}/complete", headers=signed_in).status_code == HTTPStatus.OK
    )

    filtered = http.get(f"{TASKS}?status=completed", headers=signed_in).json()
    by_area = http.get(f"{TASKS}?areaId={other}", headers=signed_in).json()

    assert [task["title"] for task in filtered["tasks"]] == ["career two"]
    assert filtered["header"]["openCount"] == 2
    assert [task["title"] for task in by_area["tasks"]] == ["fitness one"]
    assert by_area["header"]["openCount"] == 1


def test_a_status_outside_the_vocabulary_is_refused_rather_than_ignored(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    response = http.get(f"{TASKS}?status=paused", headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


def test_the_at_risk_filter_partitions_the_list_and_moves_neither_header_figure(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    """``atRisk`` is served rather than documented, so a client reads it instead of deriving it.

    This tenant has no plan, so the current week's verdict is ``None`` and nothing is marked. That
    makes the assertion here the shape of the filter rather than the determination behind it: the
    two values partition the list, and neither moves a header figure. **The filter over a week that
    really does mark a task is driven in ``test_at_risk_integration.py``**, against the week read's
    own shortfalls, because a suite with no verdict cannot tell a working filter from one that
    answers nothing.
    """
    capture(http, signed_in, areaId=area, title="one")
    capture(http, signed_in, areaId=area, title="two")

    marked = http.get(f"{TASKS}?atRisk=true", headers=signed_in).json()
    rest = http.get(f"{TASKS}?atRisk=false", headers=signed_in).json()

    assert [task["title"] for task in marked["tasks"]] == []
    assert [task["title"] for task in rest["tasks"]] == ["one", "two"]
    for answered in (marked, rest):
        assert answered["header"] == {"openCount": 2, "atRiskCount": 0}


def test_an_at_risk_value_that_is_not_a_boolean_is_refused_rather_than_ignored(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    """A misspelled filter must not read as the absent one, which would answer every row."""
    response = http.get(f"{TASKS}?atRisk=maybe", headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


def test_the_list_is_oldest_first(http: TestClient, signed_in: dict[str, str], area: str) -> None:
    for title in ("first", "second", "third"):
        capture(http, signed_in, areaId=area, title=title)

    listed = http.get(TASKS, headers=signed_in).json()["tasks"]

    assert [task["title"] for task in listed] == ["first", "second", "third"]


def test_another_tenant_s_task_is_a_404_rather_than_a_read(
    http: TestClient, live_database_url: str, owner: UserRecord, signed_in: dict[str, str]
) -> None:
    stranger = provision_owner(live_database_url)
    try:
        theirs = _sign_in(http, stranger.email)
        their_area = declare_area(http, theirs, "Theirs")
        their_task = capture(http, theirs, areaId=their_area, title="Theirs")

        read = http.get(f"{TASKS}/{their_task['id']}", headers=signed_in)
        patched = http.patch(
            f"{TASKS}/{their_task['id']}", json={"title": "mine now"}, headers=signed_in
        )

        assert read.status_code == NotFound.status
        assert patched.status_code == NotFound.status
        assert http.get(f"{TASKS}/{their_task['id']}", headers=theirs).json()["title"] == "Theirs"
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


# --------------------------------------------------------------------------------
# Change
# --------------------------------------------------------------------------------


def test_an_omitted_field_is_left_alone_and_an_explicit_null_clears_a_deadline(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    created = capture(
        http, signed_in, areaId=area, title="Leetcode", deadline=A_DEADLINE.isoformat()
    )

    renamed = http.patch(
        f"{TASKS}/{created['id']}", json={"title": "Leetcode, harder"}, headers=signed_in
    ).json()
    cleared = http.patch(
        f"{TASKS}/{created['id']}", json={"deadline": None}, headers=signed_in
    ).json()

    assert renamed["deadline"] == created["deadline"]
    assert renamed["title"] == "Leetcode, harder"
    assert cleared["deadline"] is None


@pytest.mark.parametrize(
    "field", ["title", "estimateMinutes", "priority", "minChunkMinutes", "splittable"]
)
def test_a_null_on_a_field_with_nothing_to_clear_is_refused(
    http: TestClient, signed_in: dict[str, str], area: str, field: str
) -> None:
    # Otherwise an explicit null and an omitted field would arrive as the same value and one of
    # the two intentions would be unreachable.
    created = capture(http, signed_in, areaId=area, title="Leetcode")

    response = http.patch(f"{TASKS}/{created['id']}", json={field: None}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


@pytest.mark.parametrize(
    "body",
    [{"areaId": str(uuid4())}, {"status": "completed"}, {"recordedMinutes": 30}],
    ids=["an Area", "a status", "recorded minutes"],
)
def test_a_patch_cannot_reach_the_area_the_status_or_the_recorded_time(
    http: TestClient, signed_in: dict[str, str], area: str, body: dict[str, object]
) -> None:
    created = capture(http, signed_in, areaId=area, title="Leetcode")

    response = http.patch(f"{TASKS}/{created['id']}", json=body, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


def test_lowering_an_estimate_under_the_stored_minimum_chunk_is_a_422(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # The body carries no minimum chunk, so the violation is only visible against the merged pair.
    created = capture(
        http, signed_in, areaId=area, title="Leetcode", estimateMinutes=90, minChunkMinutes=45
    )

    response = http.patch(
        f"{TASKS}/{created['id']}", json={"estimateMinutes": 30}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status, response.text
    [row] = task_rows(live_database_url, owner.tenant_id)
    assert (row.estimate_minutes, row.min_chunk_minutes) == (90, 45)


# --------------------------------------------------------------------------------
# The two endings
# --------------------------------------------------------------------------------


def test_completing_a_task_records_the_instant_and_keeps_the_recorded_time(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    created = capture(http, signed_in, areaId=area, title="Leetcode", estimateMinutes=90)
    record_progress(live_database_url, owner.tenant_id, 30)

    completed = http.post(f"{TASKS}/{created['id']}/complete", headers=signed_in)

    assert completed.status_code == HTTPStatus.OK, completed.text
    body = completed.json()
    assert body["status"] == TaskStatus.COMPLETED.value
    assert body["completedAt"] is not None
    assert body["recordedMinutes"] == 30
    assert body["eligibleForSolving"] is False
    [row] = task_rows(live_database_url, owner.tenant_id)
    assert row.recorded_minutes == 30
    assert row.completed_at is not None


def test_a_partially_completed_splittable_task_reports_its_reduced_remaining_estimate(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # No route writes recorded minutes: they come from confirmed outcomes, so they are seeded.
    created = capture(http, signed_in, areaId=area, title="Leetcode", estimateMinutes=90)
    record_progress(live_database_url, owner.tenant_id, 30)

    read = http.get(f"{TASKS}/{created['id']}", headers=signed_in).json()

    assert read["estimateMinutes"] == 90
    assert read["recordedMinutes"] == 30
    assert read["remainingMinutes"] == 60
    assert read["splittable"] is True
    assert read["eligibleForSolving"] is True


def test_recording_past_the_estimate_reports_no_remaining_work_rather_than_a_negative_one(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    created = capture(http, signed_in, areaId=area, title="Leetcode", estimateMinutes=60)
    record_progress(live_database_url, owner.tenant_id, 180)

    read = http.get(f"{TASKS}/{created['id']}", headers=signed_in).json()

    assert read["remainingMinutes"] == 0
    assert read["eligibleForSolving"] is False


def test_completing_a_task_twice_replays_it_without_moving_the_instant(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    created = capture(http, signed_in, areaId=area, title="Leetcode")

    first = http.post(f"{TASKS}/{created['id']}/complete", headers=signed_in).json()
    second = http.post(f"{TASKS}/{created['id']}/complete", headers=signed_in).json()

    assert first == second


def test_dropping_a_task_answers_with_it_rather_than_removing_the_row(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    created = capture(http, signed_in, areaId=area, title="Leetcode")

    dropped = http.delete(f"{TASKS}/{created['id']}", headers=signed_in)

    assert dropped.status_code == HTTPStatus.OK, dropped.text
    assert dropped.json()["status"] == TaskStatus.DROPPED.value
    assert dropped.json()["completedAt"] is None
    assert dropped.json()["eligibleForSolving"] is False
    [row] = task_rows(live_database_url, owner.tenant_id)
    assert row.status is TaskStatus.DROPPED


def test_completing_a_dropped_task_is_a_409_that_says_what_still_reads(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    created = capture(http, signed_in, areaId=area, title="Leetcode")
    assert http.delete(f"{TASKS}/{created['id']}", headers=signed_in).status_code == HTTPStatus.OK

    response = http.post(f"{TASKS}/{created['id']}/complete", headers=signed_in)

    assert response.status_code == Conflict.status, response.text
    problem = response.json()
    assert problem["type"] == Conflict.type
    assert "already dropped" in problem["detail"]
    assert "still reads as it did" in problem["detail"]


def test_dropping_a_completed_task_is_a_409(
    http: TestClient, signed_in: dict[str, str], area: str
) -> None:
    created = capture(http, signed_in, areaId=area, title="Leetcode")
    assert (
        http.post(f"{TASKS}/{created['id']}/complete", headers=signed_in).status_code
        == HTTPStatus.OK
    )

    response = http.delete(f"{TASKS}/{created['id']}", headers=signed_in)

    assert response.status_code == Conflict.status, response.text


# --------------------------------------------------------------------------------
# Idempotency and the input version
# --------------------------------------------------------------------------------


def test_a_repeated_capture_under_one_key_creates_one_task(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    body = {"areaId": area, "title": "Leetcode"}
    headers = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}

    first = http.post(TASKS, json=body, headers=headers)
    second = http.post(TASKS, json=body, headers=headers)

    assert first.status_code == HTTPStatus.CREATED, first.text
    assert second.status_code == HTTPStatus.CREATED, second.text
    assert first.json() == second.json()
    assert len(task_rows(live_database_url, owner.tenant_id)) == 1


def test_the_same_key_on_a_different_capture_is_refused(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    headers = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}
    assert (
        http.post(TASKS, json={"areaId": area, "title": "one"}, headers=headers).status_code
        == HTTPStatus.CREATED
    )

    reused = http.post(TASKS, json={"areaId": area, "title": "two"}, headers=headers)

    assert reused.status_code == ValidationFailed.status, reused.text
    assert len(task_rows(live_database_url, owner.tenant_id)) == 1


@pytest.mark.parametrize("method", ["post", "patch", "delete", "complete"])
def test_every_unsafe_method_accepts_an_idempotency_key(
    http: TestClient, signed_in: dict[str, str], area: str, method: str
) -> None:
    created = capture(http, signed_in, areaId=area, title="Leetcode")
    headers = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}
    requests = {
        "post": lambda: http.post(
            TASKS, json={"areaId": area, "title": "another"}, headers=headers
        ),
        "patch": lambda: http.patch(
            f"{TASKS}/{created['id']}", json={"title": "renamed"}, headers=headers
        ),
        "delete": lambda: http.delete(f"{TASKS}/{created['id']}", headers=headers),
        "complete": lambda: http.post(f"{TASKS}/{created['id']}/complete", headers=headers),
    }

    response = requests[method]()

    assert response.status_code in {HTTPStatus.OK, HTTPStatus.CREATED}, response.text
    # And the key replays rather than re-running: the second call answers identically.
    assert requests[method]().json() == response.json()


@pytest.mark.parametrize("method", ["delete", "complete", "patch"])
def test_one_key_across_two_tasks_does_not_silently_skip_the_second(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
    method: str,
) -> None:
    """One key, two tasks: the second request is refused rather than answered from the first's row.

    A claim is keyed by the tenant, the handler and the key, so the task the request named is
    carried by the request hash alone. Two tasks under one key are therefore one key used for two
    different requests, which is the 422 the guard already documents, and the second task is left
    exactly as it was for the caller to retry under a key of its own.

    ``DELETE`` and ``complete`` carry no body at all, so nothing but the path distinguishes them.
    ``PATCH`` is the conditional half: it collides whenever two requests carry the same body, which
    a batch of identical edits does.
    """
    first = capture(http, signed_in, areaId=area, title="first")
    second = capture(http, signed_in, areaId=area, title="second")
    headers = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}
    send = {
        "delete": lambda task: http.delete(f"{TASKS}/{task['id']}", headers=headers),
        "complete": lambda task: http.post(f"{TASKS}/{task['id']}/complete", headers=headers),
        "patch": lambda task: http.patch(
            f"{TASKS}/{task['id']}", json={"priority": "urgent"}, headers=headers
        ),
    }
    landed = {
        "delete": lambda row: row.status is TaskStatus.DROPPED,
        "complete": lambda row: row.status is TaskStatus.COMPLETED,
        "patch": lambda row: row.priority is Priority.URGENT,
    }

    send[method](first)
    answered = send[method](second)

    assert answered.status_code == ValidationFailed.status, answered.text
    stored = {row.title: row for row in task_rows(live_database_url, owner.tenant_id)}
    assert not landed[method](stored["second"])
    assert landed[method](stored["first"]), "the first request is the one that owns the key"


def test_the_week_input_version_is_bumped_by_every_mutating_route(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # A task is a solve input and belongs to no week, so a mutation bumps the current week and
    # every week after it. Only TRACKED weeks are bumped, which is why one is seeded first.
    week = this_week()
    track_week(live_database_url, owner.tenant_id, week)
    assert version_rows(live_database_url, owner.tenant_id)[week] == 1

    created = capture(http, signed_in, areaId=area, title="Leetcode")
    assert version_rows(live_database_url, owner.tenant_id)[week] == 2

    http.patch(f"{TASKS}/{created['id']}", json={"title": "renamed"}, headers=signed_in)
    assert version_rows(live_database_url, owner.tenant_id)[week] == 3

    http.post(f"{TASKS}/{created['id']}/complete", headers=signed_in)
    assert version_rows(live_database_url, owner.tenant_id)[week] == 4

    second = capture(http, signed_in, areaId=area, title="Second")
    http.delete(f"{TASKS}/{second['id']}", headers=signed_in)
    assert version_rows(live_database_url, owner.tenant_id)[week] == 6


def test_a_read_and_a_refused_mutation_bump_nothing(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    week = this_week()
    track_week(live_database_url, owner.tenant_id, week)

    http.get(TASKS, headers=signed_in)
    http.post(
        TASKS,
        json={"areaId": area, "title": "Leetcode", "estimateMinutes": 60, "minChunkMinutes": 61},
        headers=signed_in,
    )

    assert version_rows(live_database_url, owner.tenant_id)[week] == 1


def test_a_patch_that_states_nothing_bumps_nothing(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # An empty body changes no column, so it changes no solve input, and invalidating a running
    # solve would cost it its work for nothing.
    created = capture(http, signed_in, areaId=area, title="Leetcode")
    week = this_week()
    track_week(live_database_url, owner.tenant_id, week)

    answered = http.patch(f"{TASKS}/{created['id']}", json={}, headers=signed_in)

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert answered.json() == created
    assert version_rows(live_database_url, owner.tenant_id)[week] == 1


def test_changing_a_task_no_solve_can_see_bumps_nothing(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # An ended task is not collected by the assembler, so correcting what a report says about one
    # invalidates nothing. Editing it is still allowed and still answers with the changed task.
    created = capture(http, signed_in, areaId=area, title="Leetcode")
    assert (
        http.post(f"{TASKS}/{created['id']}/complete", headers=signed_in).status_code
        == HTTPStatus.OK
    )
    week = this_week()
    track_week(live_database_url, owner.tenant_id, week)

    corrected = http.patch(
        f"{TASKS}/{created['id']}", json={"estimateMinutes": 120}, headers=signed_in
    )

    assert corrected.status_code == HTTPStatus.OK, corrected.text
    assert corrected.json()["estimateMinutes"] == 120
    assert version_rows(live_database_url, owner.tenant_id)[week] == 1


def test_a_past_week_is_never_bumped(
    http: TestClient,
    signed_in: dict[str, str],
    area: str,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # An approved revision is immutable and keeps the inputs it was computed with, so re-deriving
    # a past week would change history rather than the plan.
    past = "2020-W01"
    track_week(live_database_url, owner.tenant_id, past)

    capture(http, signed_in, areaId=area, title="Leetcode")

    assert version_rows(live_database_url, owner.tenant_id)[past] == 1
