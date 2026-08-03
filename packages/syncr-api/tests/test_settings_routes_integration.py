"""The five settings routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a
real database can: that a `GET` on a tenant with no row answers the defaults and creates
nothing, that a `PATCH` is committed rather than merely written, that the 409 reaches the
wire as problem details naming both ranges, and that another tenant's override identifier
is a 404 rather than a deletion.

The sleep-floor test is the one to read. `PATCH /api/v1/settings` rejects a `sleepFloor`
field, because the floor is `minDurationMinutes` on the sleep routine and an endpoint that
accepted it here would store a value nothing reads.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie
is `Secure`, and an HTTP client that honors that attribute will not send it back over
`http://testserver`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, Conflict, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.user_settings.config import (
    DAY_END_DEFAULT,
    DAY_START_DEFAULT,
    HOME_ZONE_DEFAULT,
    REVIEW_CADENCE_DEFAULT,
    SETTINGS_PREFIX,
    VISIBLE_HOURS_DEFAULT,
    ReviewCadence,
)
from syncr_api.user_settings.models import Settings, TravelOverrideRow
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
SETTINGS = SETTINGS_PREFIX
TRAVEL_OVERRIDES = f"{SETTINGS_PREFIX}/travel-overrides"

LONDON = "Europe/London"
TOKYO = "Asia/Tokyo"


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


def settings_rows(database_url: str, tenant_id: TenantId) -> list[Settings]:
    """The tenant's settings rows, read on a connection of this test's own."""

    async def read() -> list[Settings]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(Settings).where(Settings.tenant_id == tenant_id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def override_rows(database_url: str, tenant_id: TenantId) -> list[TravelOverrideRow]:
    async def read() -> list[TravelOverrideRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(TravelOverrideRow)
                    .where(TravelOverrideRow.tenant_id == tenant_id)
                    .order_by(TravelOverrideRow.start_date)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


# --------------------------------------------------------------------------------
# GET and PATCH /api/v1/settings
# --------------------------------------------------------------------------------


def test_the_settings_route_needs_a_credential(http: TestClient) -> None:
    response = http.get(SETTINGS)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_a_first_read_answers_the_defaults_and_writes_nothing(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    before = datetime.now(UTC).date()
    response = http.get(SETTINGS, headers=signed_in)
    after = datetime.now(UTC).date()

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    # The default home zone IS UTC, so today in it is today in UTC. Bracketed by the two
    # dates either side of the request rather than read back from the response, which would
    # assert nothing about which date the server chose, and rather than one computed date,
    # which a run crossing UTC midnight would fail on.
    assert body.pop("activeZoneDate") in {before.isoformat(), after.isoformat()}
    assert body == {
        "visibleHours": VISIBLE_HOURS_DEFAULT,
        "dayStart": DAY_START_DEFAULT.isoformat(),
        "dayEnd": DAY_END_DEFAULT.isoformat(),
        "reviewCadence": REVIEW_CADENCE_DEFAULT.value,
        "homeZone": HOME_ZONE_DEFAULT,
        "activeZone": HOME_ZONE_DEFAULT,
    }
    # A read never writes. Without this the endpoint would still look correct while
    # putting an INSERT on the read path of every screen that shows a setting.
    assert settings_rows(live_database_url, owner.tenant_id) == []


def test_a_patch_is_committed_and_read_back(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    patched = http.patch(
        SETTINGS,
        json={"visibleHours": 18, "dayStart": "06:30", "homeZone": LONDON},
        headers=signed_in,
    )

    assert patched.status_code == HTTPStatus.OK, patched.text
    assert patched.json()["visibleHours"] == 18
    assert patched.json()["dayStart"] == "06:30:00"
    assert patched.json()["homeZone"] == LONDON
    # Unnamed fields kept their values.
    assert patched.json()["dayEnd"] == DAY_END_DEFAULT.isoformat()

    rows = settings_rows(live_database_url, owner.tenant_id)
    assert [(row.visible_hours, row.home_zone) for row in rows] == [(18, LONDON)]
    assert http.get(SETTINGS, headers=signed_in).json() == patched.json()


def test_a_second_patch_updates_the_row_rather_than_adding_one(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # One row per tenant is the primary key's promise. This is the request pair that would
    # violate it if the write were an insert.
    http.patch(SETTINGS, json={"visibleHours": 18}, headers=signed_in)
    http.patch(SETTINGS, json={"reviewCadence": ReviewCadence.QUARTERLY.value}, headers=signed_in)

    rows = settings_rows(live_database_url, owner.tenant_id)
    assert [(row.visible_hours, row.review_cadence) for row in rows] == [
        (18, ReviewCadence.QUARTERLY)
    ]


def test_the_patch_rejects_a_sleep_floor(http: TestClient, signed_in: dict[str, str]) -> None:
    # The floor is `minDurationMinutes` on the sleep routine, set through
    # `PATCH /api/v1/routines/{id}`. An earlier draft put it here, where nothing read it,
    # so accepting the field would store a number with no consumer.
    response = http.patch(SETTINGS, json={"sleepFloor": 360}, headers=signed_in)

    assert response.status_code == ValidationFailed.status
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    fields = [error["field"] for error in response.json()["errors"]]
    assert any("sleepFloor" in field for field in fields), response.text


@pytest.mark.parametrize(
    "body",
    [
        {"visibleHours": 5},
        {"visibleHours": 25},
        {"visibleHours": 0},
        {"homeZone": "x" * 65},
        {"homeZone": ""},
    ],
)
def test_a_value_outside_its_declared_bounds_is_rejected_at_the_edge(
    http: TestClient, signed_in: dict[str, str], body: dict[str, object]
) -> None:
    response = http.patch(SETTINGS, json=body, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


def test_a_zone_the_database_does_not_name_is_rejected_rather_than_stored(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # `Europe` is a DIRECTORY in the tz tree. Before the zone layer caught that shape it
    # raised IsADirectoryError, which would have reached the wire as a 500 here.
    response = http.patch(SETTINGS, json={"homeZone": "Europe"}, headers=signed_in)

    assert response.status_code == ValidationFailed.status
    assert "IANA" in response.json()["detail"]
    assert settings_rows(live_database_url, owner.tenant_id) == []


def test_day_bounds_that_describe_no_day_are_rejected(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.patch(SETTINGS, json={"dayStart": "23:00"}, headers=signed_in)

    assert response.status_code == ValidationFailed.status
    assert "earlier than day end" in response.json()["detail"]


# --------------------------------------------------------------------------------
# The travel-override routes
# --------------------------------------------------------------------------------


def test_declaring_listing_and_removing_an_override(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    declared = http.post(
        TRAVEL_OVERRIDES,
        json={"startDate": "2026-09-01", "endDate": "2026-09-10", "zone": TOKYO},
        headers=signed_in,
    )

    assert declared.status_code == HTTPStatus.CREATED, declared.text
    override_id = declared.json()["id"]
    assert declared.json()["startDate"] == "2026-09-01"
    assert declared.json()["zone"] == TOKYO

    listed = http.get(TRAVEL_OVERRIDES, headers=signed_in)
    assert [row["id"] for row in listed.json()["overrides"]] == [override_id]
    assert [str(row.id) for row in override_rows(live_database_url, owner.tenant_id)] == [
        override_id
    ]

    removed = http.delete(f"{TRAVEL_OVERRIDES}/{override_id}", headers=signed_in)
    assert removed.status_code == HTTPStatus.NO_CONTENT
    assert removed.content == b""
    assert override_rows(live_database_url, owner.tenant_id) == []


def test_an_overlapping_declaration_answers_409_naming_both_ranges(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    first = http.post(
        TRAVEL_OVERRIDES,
        json={"startDate": "2026-09-01", "endDate": "2026-09-10", "zone": TOKYO},
        headers=signed_in,
    )
    assert first.status_code == HTTPStatus.CREATED, first.text

    overlapping = http.post(
        TRAVEL_OVERRIDES,
        json={"startDate": "2026-09-10", "endDate": "2026-09-14", "zone": "Asia/Seoul"},
        headers=signed_in,
    )

    assert overlapping.status_code == Conflict.status
    problem = overlapping.json()
    assert problem["type"] == Conflict.type
    assert "2026-09-01" in problem["detail"]
    assert "2026-09-10" in problem["detail"]
    # The reason is stated, and so is what still works.
    assert "Nothing was changed" in problem["detail"]


def test_two_overrides_that_abut_exactly_are_both_accepted(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Adjacency is not overlap. The 409 above and this pair differ by ONE day, which is
    # what makes the boundary condition tested rather than assumed.
    http.post(
        TRAVEL_OVERRIDES,
        json={"startDate": "2026-09-01", "endDate": "2026-09-10", "zone": TOKYO},
        headers=signed_in,
    )
    abutting = http.post(
        TRAVEL_OVERRIDES,
        json={"startDate": "2026-09-11", "endDate": "2026-09-14", "zone": "Asia/Seoul"},
        headers=signed_in,
    )

    assert abutting.status_code == HTTPStatus.CREATED, abutting.text
    listed = http.get(TRAVEL_OVERRIDES, headers=signed_in)
    assert [row["startDate"] for row in listed.json()["overrides"]] == [
        "2026-09-01",
        "2026-09-11",
    ]


def test_the_settings_read_states_the_zone_an_override_makes_active_today(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The home zone is set FIRST and the date read afterwards, because the date is resolved
    # IN the home zone: read before the change and the answer can be yesterday's, which is
    # a real difference for a few hours either side of midnight rather than a nicety.
    http.patch(SETTINGS, json={"homeZone": LONDON}, headers=signed_in)
    today = http.get(SETTINGS, headers=signed_in).json()["activeZoneDate"]

    declared = http.post(
        TRAVEL_OVERRIDES,
        json={"startDate": today, "endDate": today, "zone": TOKYO},
        headers=signed_in,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text

    read = http.get(SETTINGS, headers=signed_in).json()
    assert read["homeZone"] == LONDON
    assert read["activeZone"] == TOKYO
    # One reading, of one zone. The response carries no second zone for the same date.
    assert sorted(read) == [
        "activeZone",
        "activeZoneDate",
        "dayEnd",
        "dayStart",
        "homeZone",
        "reviewCadence",
        "visibleHours",
    ]


def test_a_range_that_ends_before_it_starts_is_rejected(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Rejected at the schema, so the 422 points at the field that has to move and offers no
    # zone identifier as the remedy: the zone in this body is perfectly readable.
    response = http.post(
        TRAVEL_OVERRIDES,
        json={"startDate": "2026-09-10", "endDate": "2026-09-01", "zone": TOKYO},
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status
    fields = [error["field"] for error in response.json()["errors"]]
    assert fields == ["body.endDate"], response.text
    # The message names both dates, so a form can explain itself without a second request.
    assert "2026-09-01 is before the start date 2026-09-10" in response.text
    assert "IANA" not in response.text


def test_a_malformed_start_date_is_reported_on_its_own_field(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The control for the pair rule above: it compares `endDate` against `startDate`, so a
    # `startDate` that never parsed must not produce a second, invented complaint.
    response = http.post(
        TRAVEL_OVERRIDES,
        json={"startDate": "the ninth", "endDate": "2026-09-10", "zone": TOKYO},
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status
    fields = [error["field"] for error in response.json()["errors"]]
    assert fields == ["body.startDate"], response.text


def test_removing_an_override_that_does_not_exist_is_a_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.delete(f"{TRAVEL_OVERRIDES}/{uuid4()}", headers=signed_in)

    assert response.status_code == NotFound.status
    assert response.json()["type"] == NotFound.type


def test_another_tenants_override_is_a_404_rather_than_a_deletion(
    http: TestClient, signed_in: dict[str, str], live_database_url: str
) -> None:
    # The cross-tenant rule, expressed through HTTP for the first time: the repository is
    # scoped, so a foreign identifier reads as absent, and the status says nothing about
    # whether the row exists.
    stranger = provision_owner(live_database_url)
    try:
        stranger_headers = _sign_in(http, stranger.email)
        declared = http.post(
            TRAVEL_OVERRIDES,
            json={"startDate": "2026-09-01", "endDate": "2026-09-10", "zone": TOKYO},
            headers=stranger_headers,
        )
        assert declared.status_code == HTTPStatus.CREATED, declared.text
        foreign_id = declared.json()["id"]

        response = http.delete(f"{TRAVEL_OVERRIDES}/{foreign_id}", headers=signed_in)

        assert response.status_code == NotFound.status
        # And the row is still there: a 404 that deleted it would be worse than a 403.
        assert [str(row.id) for row in override_rows(live_database_url, stranger.tenant_id)] == [
            foreign_id
        ]
        # The stranger cannot see this tenant's overrides either.
        assert http.get(TRAVEL_OVERRIDES, headers=signed_in).json()["overrides"] == []
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


def test_an_unsafe_request_from_an_unserved_origin_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    forged = {**signed_in, "Origin": "https://evil.example"}

    response = http.patch(SETTINGS, json={"visibleHours": 18}, headers=forged)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"] == "syncr:origin-rejected"


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
