"""The eight Area and Project routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a real
database can: that the pigment deal survives twelve committed rows, that a refused declaration
is not stored, that a wire ``Decimal`` reaches the client as a number rather than a string, and
that another tenant's identifier is a 404 rather than an edit.

Two tests are worth reading. ``test_a_thirteenth_area_is_refused_and_the_body_states_the_cap``
is the ramp's bound through HTTP, twelve committed rows and a refusal, and
``test_a_share_that_does_not_fit_is_accepted_rather_than_refused`` is the rule this endpoint
exists to hold: a percentage total past 100 is a legitimate declaration, and what answers for
it is the budget report's ``oversubscription``.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX, PROJECTS_PREFIX
from syncr_api.areas.models import AreaRow, ProjectRow
from syncr_api.areas.rules import FULL_RAMP_REFUSAL
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, Conflict, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_domain.pigments import PIGMENT_COUNT, PIGMENT_DEAL_ORDER
from syncr_domain.projects import ProjectStatus
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


def area_rows(database_url: str, tenant_id: TenantId) -> list[AreaRow]:
    """The tenant's Area rows, read on a connection of this test's own."""

    async def read() -> list[AreaRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(AreaRow)
                    .where(AreaRow.tenant_id == tenant_id)
                    .order_by(AreaRow.created_at, AreaRow.id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def project_rows(database_url: str, tenant_id: TenantId) -> list[ProjectRow]:
    async def read() -> list[ProjectRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(ProjectRow).where(ProjectRow.tenant_id == tenant_id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def declare_area(http: TestClient, headers: dict[str, str], **body: object) -> dict[str, Any]:
    """The `{area, ramp}` body a successful declaration answers with.

    Typed loosely on purpose: every assertion below reads the JSON a real client receives,
    rather than a shape reconstructed from the schema it was serialized by.
    """
    response = http.post(AREAS, json=body, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    payload: dict[str, Any] = response.json()
    return payload


# --------------------------------------------------------------------------------
# Areas
# --------------------------------------------------------------------------------


def test_the_areas_route_needs_a_credential(http: TestClient) -> None:
    response = http.get(AREAS)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_declaring_an_area_assigns_a_pigment_and_commits_it(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = declare_area(http, signed_in, name="Fitness", floorHours=4.5, budgetPercent=25)

    area = created["area"]
    assert isinstance(area, dict)
    assert area["name"] == "Fitness"
    assert area["pigmentIndex"] == PIGMENT_DEAL_ORDER[0]
    # A number on the wire, not a string: a Decimal that reached the client as "4.50" would
    # make every caller narrow before doing arithmetic.
    assert area["floorHours"] == 4.5
    assert area["budgetPercent"] == 25
    assert area["parentId"] is None
    # No preference identifier: a preference names its own owner, and this response states the
    # budget an Area declares rather than the relations that name it.
    assert "defaultPreferenceId" not in area, area

    rows = area_rows(live_database_url, owner.tenant_id)
    assert [(row.name, row.pigment_index) for row in rows] == [("Fitness", PIGMENT_DEAL_ORDER[0])]
    assert http.get(AREAS, headers=signed_in).json()["areas"] == [area]


def test_no_request_shape_accepts_a_colour(http: TestClient, signed_in: dict[str, str]) -> None:
    # There is no colour picker anywhere in the product, so the field that would carry one is
    # refused rather than ignored.
    for body in ({"name": "Fitness", "color": "#AB4757"}, {"name": "Fitness", "pigment": "madder"}):
        response = http.post(AREAS, json=body, headers=signed_in)
        assert response.status_code == ValidationFailed.status, response.text


def test_creation_does_not_accept_a_pigment_step_either(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Creation ASSIGNS the step. Accepting one here would make the deal advisory.
    response = http.post(AREAS, json={"name": "Fitness", "pigmentIndex": 3}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


def test_the_first_four_areas_take_four_distinct_pigments(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    dealt = [
        declare_area(http, signed_in, name=f"Area {index}")["area"]["pigmentIndex"]
        for index in range(4)
    ]

    assert dealt == list(PIGMENT_DEAL_ORDER[:4])
    assert len(set(dealt)) == 4


def test_a_thirteenth_area_is_refused_and_the_body_states_the_cap(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    for index in range(PIGMENT_COUNT):
        created = declare_area(http, signed_in, name=f"Area {index}")
        # Every step the ramp has is dealt to a declaration that is accepted, so nothing is
        # shared and nothing is stated. The twelfth is admitted here, not refused.
        assert created["ramp"] == {
            "pigmentCount": PIGMENT_COUNT,
            "pigmentsInUse": index + 1,
            "areasSharingAPigment": 0,
            "statement": None,
        }

    refused = http.post(AREAS, json={"name": "Thirteenth"}, headers=signed_in)

    assert refused.status_code == ValidationFailed.status, refused.text
    assert refused.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    problem = refused.json()
    assert problem["type"] == ValidationFailed.type
    # The sentence the api composes, reaching a client unaltered.
    assert problem["detail"] == FULL_RAMP_REFUSAL
    assert "errors" not in problem, problem

    rows = area_rows(live_database_url, owner.tenant_id)
    assert [row.name for row in rows] == [f"Area {index}" for index in range(PIGMENT_COUNT)]
    assert sorted(row.pigment_index for row in rows) == list(range(PIGMENT_COUNT))


def test_the_ramp_reading_states_how_many_pigments_are_in_use(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The setup screen's count, which is why it is on the list read as well.
    declare_area(http, signed_in, name="Fitness")
    declare_area(http, signed_in, name="Career")

    assert http.get(AREAS, headers=signed_in).json()["ramp"]["pigmentsInUse"] == 2


def test_a_share_that_does_not_fit_is_accepted_rather_than_refused(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    declare_area(http, signed_in, name="Fitness", budgetPercent=80)
    declare_area(http, signed_in, name="Career", budgetPercent=50)

    stored = [row.budget_percent for row in area_rows(live_database_url, owner.tenant_id)]
    assert [float(percent) for percent in stored if percent is not None] == [80.0, 50.0]


def test_a_duplicate_name_answers_409_and_stores_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    declare_area(http, signed_in, name="Fitness")

    duplicate = http.post(AREAS, json={"name": "Fitness"}, headers=signed_in)

    assert duplicate.status_code == Conflict.status
    problem = duplicate.json()
    assert problem["type"] == Conflict.type
    assert "hatch" in problem["detail"]
    assert "Nothing was changed" in problem["detail"]
    assert len(area_rows(live_database_url, owner.tenant_id)) == 1


def test_an_unknown_parent_answers_422_and_stores_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    response = http.post(
        AREAS, json={"name": "Learning", "parentId": str(uuid4())}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status, response.text
    assert [error["field"] for error in response.json()["errors"]] == ["parentId"]
    assert area_rows(live_database_url, owner.tenant_id) == []


def test_an_area_nests_under_one_that_exists(http: TestClient, signed_in: dict[str, str]) -> None:
    parent = declare_area(http, signed_in, name="Career")["area"]
    assert isinstance(parent, dict)

    child = declare_area(http, signed_in, name="Learning", parentId=parent["id"])["area"]

    assert child["parentId"] == parent["id"]


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "x" * 61},
        {"name": "Fitness", "budgetPercent": -1},
        {"name": "Fitness", "budgetPercent": 101},
        {"name": "Fitness", "floorHours": -1},
        {"name": "Fitness", "floorHours": 169},
    ],
    ids=[
        "an empty name",
        "an over-long name",
        "a negative share",
        "a share past 100",
        "a negative floor",
        "a floor no week could meet",
    ],
)
def test_a_value_outside_its_declared_bounds_is_refused_rather_than_stored(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    body: dict[str, object],
) -> None:
    response = http.post(AREAS, json=body, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    assert area_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize(
    "body",
    [{"name": "Fitness", "budgetPercent": 0}, {"name": "Fitness", "floorHours": 168}],
    ids=["a zero share", "a floor of a whole week"],
)
def test_a_value_at_the_edge_of_its_bounds_is_accepted(
    http: TestClient, signed_in: dict[str, str], body: dict[str, object]
) -> None:
    # The control at the other end of each bound: the rejections above must distinguish rather
    # than refuse everything near the edge.
    response = http.post(AREAS, json=body, headers=signed_in)

    assert response.status_code == HTTPStatus.CREATED, response.text


def test_a_patch_changes_only_what_it_names(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = declare_area(http, signed_in, name="Fitness", floorHours=4, budgetPercent=25)
    area_id = created["area"]["id"]

    patched = http.patch(f"{AREAS}/{area_id}", json={"budgetPercent": 30}, headers=signed_in)

    assert patched.status_code == HTTPStatus.OK, patched.text
    assert patched.json()["area"]["budgetPercent"] == 30
    assert patched.json()["area"]["floorHours"] == 4
    assert patched.json()["area"]["name"] == "Fitness"
    rows = area_rows(live_database_url, owner.tenant_id)
    assert [float(row.floor_hours or 0) for row in rows] == [4.0]


def test_an_explicit_null_clears_a_floor(http: TestClient, signed_in: dict[str, str]) -> None:
    created = declare_area(http, signed_in, name="Fitness", floorHours=4, budgetPercent=25)
    area_id = created["area"]["id"]

    patched = http.patch(f"{AREAS}/{area_id}", json={"floorHours": None}, headers=signed_in)

    assert patched.status_code == HTTPStatus.OK, patched.text
    assert patched.json()["area"]["floorHours"] is None
    # And the share it did not name is untouched, which is what makes the two cases distinct.
    assert patched.json()["area"]["budgetPercent"] == 25


def test_a_null_name_is_refused_rather_than_read_as_no_change(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = declare_area(http, signed_in, name="Fitness")
    area_id = created["area"]["id"]

    response = http.patch(f"{AREAS}/{area_id}", json={"name": None}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    assert "cannot be cleared" in response.text


def test_a_patch_cannot_move_an_area_between_parents(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = declare_area(http, signed_in, name="Fitness")
    area_id = created["area"]["id"]

    response = http.patch(f"{AREAS}/{area_id}", json={"parentId": str(uuid4())}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


def test_a_pigment_can_be_re_picked_from_the_ramp(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = declare_area(http, signed_in, name="Fitness")
    area_id = created["area"]["id"]

    patched = http.patch(f"{AREAS}/{area_id}", json={"pigmentIndex": 11}, headers=signed_in)

    assert patched.status_code == HTTPStatus.OK, patched.text
    assert patched.json()["area"]["pigmentIndex"] == 11


def test_a_pigment_step_off_the_ramp_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = declare_area(http, signed_in, name="Fitness")
    area_id = created["area"]["id"]

    for step in (-1, PIGMENT_COUNT):
        response = http.patch(f"{AREAS}/{area_id}", json={"pigmentIndex": step}, headers=signed_in)
        assert response.status_code == ValidationFailed.status, response.text


def test_reading_an_area_that_does_not_exist_is_a_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(f"{AREAS}/{uuid4()}", headers=signed_in)

    assert response.status_code == NotFound.status
    assert response.json()["type"] == NotFound.type


def test_another_tenants_area_is_a_404_rather_than_an_edit(
    http: TestClient, signed_in: dict[str, str], live_database_url: str
) -> None:
    stranger = provision_owner(live_database_url)
    try:
        stranger_headers = _sign_in(http, stranger.email)
        foreign = declare_area(http, stranger_headers, name="Their fitness")
        foreign_id = foreign["area"]["id"]

        read = http.get(f"{AREAS}/{foreign_id}", headers=signed_in)
        patched = http.patch(f"{AREAS}/{foreign_id}", json={"name": "Mine"}, headers=signed_in)

        assert read.status_code == NotFound.status
        assert patched.status_code == NotFound.status
        # And the row is untouched: a 404 that renamed it would be worse than a 403.
        rows = area_rows(live_database_url, stranger.tenant_id)
        assert [row.name for row in rows] == ["Their fitness"]
        # The same name is therefore available to this tenant, because uniqueness is per tenant.
        assert http.post(AREAS, json={"name": "Their fitness"}, headers=signed_in).status_code == (
            HTTPStatus.CREATED
        )
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


def test_an_unsafe_request_from_an_unserved_origin_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    forged = {**signed_in, "Origin": "https://evil.example"}

    response = http.post(AREAS, json={"name": "Fitness"}, headers=forged)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"] == "syncr:origin-rejected"


# --------------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------------


def test_declaring_listing_and_completing_a_project(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    area_id = declare_area(http, signed_in, name="Career")["area"]["id"]

    declared = http.post(
        PROJECTS,
        json={"areaId": area_id, "name": "Interview prep", "deadline": "2026-09-01T12:00:00+00:00"},
        headers=signed_in,
    )

    assert declared.status_code == HTTPStatus.CREATED, declared.text
    project = declared.json()
    assert project["areaId"] == area_id
    assert project["status"] == ProjectStatus.ACTIVE.value
    # No budget fields anywhere in the shape: a Project inherits its Area's allocation.
    assert sorted(project) == ["areaId", "deadline", "id", "name", "status"]

    listed = http.get(PROJECTS, headers=signed_in)
    assert [row["id"] for row in listed.json()["projects"]] == [project["id"]]

    completed = http.patch(
        f"{PROJECTS}/{project['id']}", json={"status": "completed"}, headers=signed_in
    )
    assert completed.status_code == HTTPStatus.OK, completed.text
    assert completed.json()["status"] == ProjectStatus.COMPLETED.value
    # The historical attribution is intact: the same Area, the same deadline, the same row.
    assert completed.json()["areaId"] == area_id
    assert completed.json()["deadline"] == project["deadline"]
    rows = project_rows(live_database_url, owner.tenant_id)
    assert [(str(row.area_id), row.status) for row in rows] == [(area_id, ProjectStatus.COMPLETED)]


def test_projects_can_be_filtered_by_area(http: TestClient, signed_in: dict[str, str]) -> None:
    career = declare_area(http, signed_in, name="Career")["area"]["id"]
    fitness = declare_area(http, signed_in, name="Fitness")["area"]["id"]
    for area_id, name in ((career, "Interview prep"), (fitness, "Marathon")):
        http.post(PROJECTS, json={"areaId": area_id, "name": name}, headers=signed_in)

    filtered = http.get(PROJECTS, params={"areaId": career}, headers=signed_in)

    assert [row["name"] for row in filtered.json()["projects"]] == ["Interview prep"]


def test_a_project_in_an_unknown_area_answers_422_and_stores_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    response = http.post(
        PROJECTS, json={"areaId": str(uuid4()), "name": "Interview prep"}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status, response.text
    assert [error["field"] for error in response.json()["errors"]] == ["areaId"]
    assert project_rows(live_database_url, owner.tenant_id) == []


def test_a_project_in_another_tenants_area_answers_422_and_stores_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # Answered identically to an unknown identifier, so the response discloses nothing about
    # which of the two it was.
    stranger = provision_owner(live_database_url)
    try:
        stranger_headers = _sign_in(http, stranger.email)
        foreign_area = declare_area(http, stranger_headers, name="Their career")
        foreign_id = foreign_area["area"]["id"]

        response = http.post(
            PROJECTS, json={"areaId": foreign_id, "name": "Interview prep"}, headers=signed_in
        )

        assert response.status_code == ValidationFailed.status, response.text
        assert project_rows(live_database_url, owner.tenant_id) == []
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


def test_a_project_body_cannot_carry_a_budget(http: TestClient, signed_in: dict[str, str]) -> None:
    area_id = declare_area(http, signed_in, name="Career")["area"]["id"]

    for field in ("budgetPercent", "floorHours"):
        response = http.post(
            PROJECTS,
            json={"areaId": area_id, "name": "Interview prep", field: 10},
            headers=signed_in,
        )
        assert response.status_code == ValidationFailed.status, response.text


def test_a_patch_cannot_move_a_project_between_areas(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    area_id = declare_area(http, signed_in, name="Career")["area"]["id"]
    declared = http.post(PROJECTS, json={"areaId": area_id, "name": "Prep"}, headers=signed_in)

    response = http.patch(
        f"{PROJECTS}/{declared.json()['id']}",
        json={"areaId": str(uuid4())},
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status, response.text


def test_a_project_deadline_can_be_cleared(http: TestClient, signed_in: dict[str, str]) -> None:
    area_id = declare_area(http, signed_in, name="Career")["area"]["id"]
    declared = http.post(
        PROJECTS,
        json={"areaId": area_id, "name": "Prep", "deadline": "2026-09-01T12:00:00+00:00"},
        headers=signed_in,
    )

    patched = http.patch(
        f"{PROJECTS}/{declared.json()['id']}", json={"deadline": None}, headers=signed_in
    )

    assert patched.status_code == HTTPStatus.OK, patched.text
    assert patched.json()["deadline"] is None


def test_a_project_that_does_not_exist_is_a_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(f"{PROJECTS}/{uuid4()}", headers=signed_in)

    assert response.status_code == NotFound.status


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
