"""Every route that takes an instant, refusing one that names no instant, through a real request.

The unit tier asserts the reading a field is built on. This asserts what a caller gets: a 422 that
NAMES the field, from the real route, with the real perimeter in front of it. The two are not the
same claim. A refusal proved only by validating a type is a refusal that may never be reached: the
authentication perimeter, the origin guard and the idempotency guard all resolve before a body is
read, and a request that never reaches validation is a request whose field was never checked.

The population is discovered rather than listed, so a route that starts carrying an instant is
driven here without anyone remembering to add it, and the walk is crossed against the routes it
found: every site names a real path, and the aware control on the parameter route answers 200, so a
refusal cannot be a request that was broken for some other reason.

WHAT DRIVES WHAT. A body carries the instant under test and nothing else. Every other field is then
missing, and a missing field is refused too, so the assertion is on the ERROR THAT NAMES THIS FIELD
and on its reason: a 422 whose only complaint is a required field elsewhere would otherwise pass.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import ValidationFailed
from syncr_api.core.settings import EnvSettings, build_service_settings
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_api.tasks.models import TaskRow
from tests.live_tenants import provision_owner, remove_tenant, run
from tests.live_weeks import sign_in, this_week
from tests.wire_census import (
    InstantBodySite,
    InstantParameter,
    instant_body_sites,
    instant_parameters,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

# The three readings that name no instant, as a caller sends them.
NAIVE_TEXT: Final = "2026-03-08T09:00"
BARE_DATE: Final = "2026-03-08"

# An instant that does, for the field not under test and for the control.
AWARE_TEXT: Final = "2026-03-08T09:00:00Z"
AN_HOUR: Final = datetime(2026, 3, 8, 9, 0, tzinfo=UTC)

# What pydantic says when the value names no instant. Asserted because the STATUS alone does not
# distinguish this refusal from a missing field, and a test that accepted any 422 would pass on a
# route that had stopped reading the instant at all.
NO_OFFSET: Final = "timezone info"

AN_INSTANT: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
AN_OFFSET: Final = re.compile(r"(Z|[+-]\d{2}:\d{2})$")

# A deadline sent from a zone that is not UTC, so what round-trips is the INSTANT rather than the
# text: the column is timestamptz, so the reading comes back in UTC and has to name the same moment.
KATHMANDU_DEADLINE: Final = "2026-03-08T09:00:00+05:45"

_COLLECTED = create_app(
    build_service_settings(service="syncr-api-census", env=EnvSettings(_env_file=None))
)
BODY_SITES: Final = instant_body_sites(_COLLECTED)
PARAMETERS: Final = instant_parameters(_COLLECTED)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """One case per site, named after the route and field it drives."""
    if "site" in metafunc.fixturenames:
        metafunc.parametrize("site", BODY_SITES, ids=[one.where for one in BODY_SITES])
    if "parameter" in metafunc.fixturenames:
        metafunc.parametrize("parameter", PARAMETERS, ids=[one.where for one in PARAMETERS])


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
    return sign_in(http, owner.email)


def addressed(path: str) -> str:
    """``path`` with a value for every parameter it carries.

    The values only have to parse: validation runs before the handler, so a refused instant is
    answered without the addressed resource being looked up. An unknown parameter raises rather
    than being guessed at, because a driver that invented a value the route cannot parse would
    report a 422 that says nothing about the instant.
    """
    filled = path
    for name in re.findall(r"{([a-z_]+)}", path):
        filled = filled.replace(f"{{{name}}}", _value_for(name))
    return filled


def _value_for(name: str) -> str:
    if name == "iso_week":
        return str(this_week())
    if name.endswith("_id"):
        return str(uuid4())
    message = f"no value is declared for the path parameter {name!r}"
    raise AssertionError(message)


def named_errors(answered: Any) -> dict[str, str]:
    """The field-level errors a 422 carries, by the field each one names."""
    return {one["field"]: one["message"] for one in answered.json()["errors"]}


def instants_in(payload: object) -> list[str]:
    """Every value in ``payload`` that renders a moment, wherever it sits."""
    if isinstance(payload, str):
        return [payload] if AN_INSTANT.match(payload) else []
    if isinstance(payload, dict):
        return [one for value in payload.values() for one in instants_in(value)]
    if isinstance(payload, list):
        return [one for value in payload for one in instants_in(value)]
    return []


class TestEveryBodyFieldThatTakesAnInstantRefusesOneThatNamesNone:
    def test_the_walk_reaches_a_site_on_more_than_one_route(self) -> None:
        # Non-vacuity, stated over the routes rather than over the count of sites: an equality
        # between two empty sets is what a narrowed walk would otherwise satisfy.
        assert len({site.path for site in BODY_SITES}) > 1

    @pytest.mark.parametrize("naive", [NAIVE_TEXT, BARE_DATE], ids=["wall", "date"])
    def test_the_route_names_the_field(
        self, http: TestClient, signed_in: dict[str, str], site: InstantBodySite, naive: str
    ) -> None:
        answered = http.request(
            site.method, addressed(site.path), json=site.body(naive), headers=signed_in
        )

        assert answered.status_code == ValidationFailed.status, answered.text
        errors = named_errors(answered)
        assert site.field in errors, errors
        assert NO_OFFSET in errors[site.field], errors[site.field]


class TestEveryParameterThatTakesAnInstantRefusesOneThatNamesNone:
    def test_an_aware_request_is_answered(
        self, http: TestClient, signed_in: dict[str, str], parameter: InstantParameter
    ) -> None:
        # The control the refusals need. Without it a 422 could be this request being wrong in some
        # way that has nothing to do with the instant, and every refusal below would still pass.
        answered = http.request(
            parameter.method,
            addressed(parameter.path),
            params=_aware_query(parameter),
            headers=signed_in,
        )

        assert answered.status_code == HTTPStatus.OK, answered.text

    @pytest.mark.parametrize("naive", [NAIVE_TEXT, BARE_DATE], ids=["wall", "date"])
    def test_the_route_names_the_parameter(
        self,
        http: TestClient,
        signed_in: dict[str, str],
        parameter: InstantParameter,
        naive: str,
    ) -> None:
        query = {**_aware_query(parameter), parameter.alias: naive}

        answered = http.request(
            parameter.method, addressed(parameter.path), params=query, headers=signed_in
        )

        assert answered.status_code == ValidationFailed.status, answered.text
        errors = named_errors(answered)
        field = f"query.{parameter.alias}"
        assert field in errors, errors
        assert NO_OFFSET in errors[field], errors[field]


def _aware_query(parameter: InstantParameter) -> dict[str, str]:
    """An aware value for every instant parameter of the route under test.

    Every one of them, because a route may require both bounds of a span: sending only the one
    under test would be refused for the other's absence and prove nothing about this one. Each gets
    a LATER instant than the one declared before it, because a span whose bounds are equal is
    refused for that instead, which is the same false red one value would have produced.
    """
    return {
        other.alias: _hours_on(other.position)
        for other in PARAMETERS
        if (other.method, other.path) == (parameter.method, parameter.path)
    }


def _hours_on(position: int) -> str:
    """An aware instant, distinct per position, rendered as a caller sends one."""
    return (AN_HOUR + timedelta(hours=position)).isoformat().replace("+00:00", "Z")


class TestACreatedDeadlineRoundTrips:
    def test_it_comes_back_naming_the_same_moment_with_an_offset(
        self,
        http: TestClient,
        signed_in: dict[str, str],
        owner: UserRecord,
        live_database_url: str,
    ) -> None:
        created = _capture(http, signed_in, deadline=KATHMANDU_DEADLINE)

        echoed = created["deadline"]
        assert AN_OFFSET.search(echoed), echoed
        assert datetime.fromisoformat(echoed) == datetime.fromisoformat(KATHMANDU_DEADLINE)
        assert datetime.fromisoformat(echoed).utcoffset() is not None
        stored = _deadlines(live_database_url, owner.tenant_id)
        assert [one.utcoffset() for one in stored] == [UTC.utcoffset(None)]

    def test_every_moment_the_backlog_renders_carries_an_offset(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        # The composed reading of the rendering claim: a real payload, scanned whole. The unit
        # tier asserts it per field; this asserts nothing in between dropped the offset.
        _capture(http, signed_in, deadline=KATHMANDU_DEADLINE)

        listed = http.get(TASKS_PREFIX, headers=signed_in)

        assert listed.status_code == HTTPStatus.OK, listed.text
        rendered = instants_in(listed.json())
        assert rendered, "the payload carried no moment at all, so this asserted nothing"
        assert [one for one in rendered if not AN_OFFSET.search(one)] == []


def _capture(http: TestClient, signed_in: dict[str, str], *, deadline: str) -> dict[str, Any]:
    area = http.post(AREAS_PREFIX, json={"name": "Career"}, headers=signed_in)
    assert area.status_code == HTTPStatus.CREATED, area.text
    created = http.post(
        TASKS_PREFIX,
        json={"areaId": area.json()["area"]["id"], "title": "Leetcode", "deadline": deadline},
        headers=signed_in,
    )
    assert created.status_code == HTTPStatus.CREATED, created.text
    task: dict[str, Any] = created.json()
    return task


def _deadlines(database_url: str, tenant_id: TenantId) -> list[datetime]:
    """The stored deadlines, read on a connection of this test's own."""

    async def read() -> list[datetime]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(TaskRow.deadline).where(TaskRow.tenant_id == tenant_id)
                )
                return [one for one in found if one is not None]
        finally:
            await database.engine.dispose()

    return run(read())
