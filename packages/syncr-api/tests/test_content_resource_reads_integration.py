"""The content resource reads end to end, against a real Postgres and a real request.

A tenant's Areas, Projects, habits, routines, tasks and week templates are declared records, and
each has a read addressed by the identifier the declaring route itself created. Until those reads
were driven, nothing proved that reading one brings no row into existence.

*A read is not a mutation.* Every parameterized GET under one of these collections' own prefixes
is driven with a record the fixture created through the declaring routes, and the row count of
every tenant-scoped table this application declares is compared against the same snapshot after
EACH read. The paths come from ``tests.boundaries.content_resource_reads``, this suite's
contribution to the census in ``test_parameterized_read_census.py``, so a read added beside these
is driven here without this module being extended.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX, PROJECTS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.routines.config import ROUTINES_PREFIX
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_api.templates.config import DAY_TYPES_PREFIX, TEMPLATES_PREFIX
from tests.boundaries import content_resource_reads, path_parameters
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, row_counts

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# The reads this module exists for, spelled so their arrival in or departure from the derived set
# is a diff a reader sees rather than a change a walk swallows.
CONTENT_READS = (
    f"{AREAS_PREFIX}/{{area_id}}",
    f"{AREAS_PREFIX}/{{area_id}}/preference",
    f"{HABITS_PREFIX}/{{habit_id}}",
    f"{HABITS_PREFIX}/{{habit_id}}/preference",
    f"{PROJECTS_PREFIX}/{{project_id}}",
    f"{ROUTINES_PREFIX}/{{routine_id}}",
    f"{TASKS_PREFIX}/{{task_id}}",
    f"{TASKS_PREFIX}/{{task_id}}/preference",
    f"{TEMPLATES_PREFIX}/{{template_id}}",
)


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


def sign_in(http: TestClient, email: str) -> dict[str, str]:
    """The headers a signed-in browser sends. The cookie is replayed rather than jarred.

    The cookie is ``Secure`` and a client honoring that attribute will not send it back over
    ``http://testserver``.
    """
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    return sign_in(http, owner.email)


# The one declaring route that wraps its record; every other one answers the record itself.
WRAPPED_UNDER = {AREAS_PREFIX: "area"}


def declare(http: TestClient, headers: dict[str, str], path: str, body: dict[str, Any]) -> str:
    """The identifier of the record this declaring route just created."""
    answered = http.post(path, json=body, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    payload = answered.json()
    wrapper = WRAPPED_UNDER.get(path)
    return str((payload[wrapper] if wrapper else payload)["id"])


@pytest.fixture
def identifiers(http: TestClient, signed_in: dict[str, str]) -> dict[str, str]:
    """One declared record of each kind, each created through its own declaring route.

    Shared by every test below rather than declared per route: every read under guard addresses
    one of these records, and each preference read addresses the same identifier its owner's own
    read spells.
    """
    area = declare(http, signed_in, AREAS_PREFIX, {"name": "Career"})
    project = declare(http, signed_in, PROJECTS_PREFIX, {"areaId": area, "name": "Interview prep"})
    habit = declare(
        http,
        signed_in,
        HABITS_PREFIX,
        {
            "areaId": area,
            "title": "Gym",
            "cadence": {"kind": "times_per_week", "timesPerWeek": 4},
            "minDurationMinutes": 90,
        },
    )
    routine = declare(
        http,
        signed_in,
        ROUTINES_PREFIX,
        {"title": "Wake", "targetTime": "06:00", "durationMinutes": 30},
    )
    task = declare(http, signed_in, TASKS_PREFIX, {"areaId": area, "title": "Leetcode"})
    day_type = declare(http, signed_in, DAY_TYPES_PREFIX, {"name": "Weekday"})
    template = declare(
        http, signed_in, TEMPLATES_PREFIX, {"dayTypeId": day_type, "name": "Weekday shape"}
    )
    return {
        "area_id": area,
        "project_id": project,
        "habit_id": habit,
        "routine_id": routine,
        "task_id": task,
        "template_id": template,
    }


def every_content_resource_read(settings: ServiceSettings) -> list[str]:
    """Every parameterized GET under a content resource's own prefix.

    Read off the published contribution rather than filtered here, which is what the consumption
    rule in ``test_parameterized_read_census.py`` holds this module to.
    """
    paths = content_resource_reads(create_app(settings))
    assert paths, "no content resource read was found, so the guards below asserted nothing"
    return paths


def addressed(path: str, identifiers: dict[str, str]) -> str:
    """The template with each parameter replaced by the identifier that names it.

    A parameter outside ``identifiers`` means a route arrived under these prefixes that this
    module's fixture does not declare a record for; name it rather than raise bare ``KeyError``.
    """
    for name in sorted(path_parameters(path)):
        if name not in identifiers:
            pytest.fail(f"{path} takes {{{name}}}, which the fixture declares no record for")
        path = path.replace(f"{{{name}}}", identifiers[name])
    return path


def test_every_content_resource_read_is_driven_here_and_answers_its_record(
    http: TestClient,
    signed_in: dict[str, str],
    identifiers: dict[str, str],
    settings: ServiceSettings,
) -> None:
    """Named so the arrival or departure of a read is a diff, and so the walk is not empty."""
    paths = every_content_resource_read(settings)
    assert set(paths) >= set(CONTENT_READS)

    for path in paths:
        answered = http.get(addressed(path, identifiers), headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, (path, answered.text)


def test_no_content_resource_read_brings_a_row_into_existence(
    http: TestClient,
    signed_in: dict[str, str],
    identifiers: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    settings: ServiceSettings,
    source_root: Path,
) -> None:
    """Every scoped table is counted once, and again after EACH read, against that same snapshot.

    A preference read is the interesting one: answering what is in effect could be done by writing
    the inherited declaration onto the owner, and this is the assertion that says it is not.
    """
    before = row_counts(live_database_url, owner.tenant_id, source_root)

    for path in every_content_resource_read(settings):
        answered = http.get(addressed(path, identifiers), headers=signed_in)
        assert answered.status_code == HTTPStatus.OK, (path, answered.text)

        assert row_counts(live_database_url, owner.tenant_id, source_root) == before, path


def test_counting_rows_would_have_caught_a_write(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    source_root: Path,
) -> None:
    """The control: the same counts DO move when a route that writes is driven."""
    before = row_counts(live_database_url, owner.tenant_id, source_root)

    assert http.post(AREAS_PREFIX, json={"name": "Health"}, headers=signed_in).status_code == (
        HTTPStatus.CREATED
    )

    assert row_counts(live_database_url, owner.tenant_id, source_root) != before
