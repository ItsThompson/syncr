"""The budget route end to end, against a real Postgres and a real request.

The service suite proves the arithmetic with fakes. This proves what only a real request and a
real database can: that the Areas the report divides are the committed rows, that every duration
reaches the wire as an integer number of minutes, and that a malformed period is a stated 422
rather than a 500 from inside the span derivation.

Nothing in this deployment can occupy a week's time yet, so every report here has the whole span
as its denominator and every discretionary minute in no block. That is the honest reading of the
schema rather than a gap in the test: what the arithmetic does with a week that IS occupied is
asserted in ``test_budget_service.py``, where the occupancy can be supplied.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.budgets.config import BUDGET_PREFIX, PERIOD_PARAMETER
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.plans.models import WeekInputVersion
from syncr_api.user_settings.config import SETTINGS_PREFIX
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

LONDON = "Europe/London"
# An ordinary week in Europe/London, and the spring-forward week that loses an hour.
ORDINARY_WEEK = "2026-W10"
ORDINARY_WEEK_MINUTES = 168 * 60
SPRING_FORWARD_WEEK = "2026-W13"


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
    headers = _sign_in(http, owner.email)
    # The span is resolved in the tenant's own zone, so the zone is declared rather than left at
    # the UTC default: a report whose denominator ignored the user's zone would be wrong by an
    # hour on exactly the weeks that matter.
    assert (
        http.patch(SETTINGS_PREFIX, json={"homeZone": LONDON}, headers=headers).status_code == 200
    )
    return headers


def budget(http: TestClient, headers: dict[str, str], period: str) -> dict[str, Any]:
    """The report body a successful read answers with.

    Typed loosely on purpose: every assertion below reads the JSON a real client receives,
    rather than a shape reconstructed from the schema it was serialized by.
    """
    response = http.get(BUDGET_PREFIX, params={PERIOD_PARAMETER: period}, headers=headers)
    assert response.status_code == HTTPStatus.OK, response.text
    payload: dict[str, Any] = response.json()
    return payload


def declare_area(http: TestClient, headers: dict[str, str], **body: object) -> str:
    response = http.post(AREAS_PREFIX, json=body, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    return str(response.json()["area"]["id"])


def test_the_budget_route_needs_a_credential(http: TestClient) -> None:
    response = http.get(BUDGET_PREFIX, params={PERIOD_PARAMETER: ORDINARY_WEEK})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_a_period_with_no_areas_reports_the_whole_span_as_unallocated(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    report = budget(http, signed_in, ORDINARY_WEEK)

    assert report["period"] == ORDINARY_WEEK
    assert report["discretionaryMinutes"] == ORDINARY_WEEK_MINUTES
    assert report["unallocatedMinutes"] == ORDINARY_WEEK_MINUTES
    assert report["oversubscriptionMinutes"] == 0
    assert report["areas"] == []
    # No time off was declared, so nothing left the denominator and there is nothing to explain.
    assert report["offPlanMinutes"] == 0
    assert report["offPlanStatement"] is None
    # The span the denominator was derived from, so a reader can check the figure rather than
    # trust it.
    assert report["span"] == {"start": "2026-03-02T00:00:00Z", "end": "2026-03-09T00:00:00Z"}


def test_the_report_divides_discretionary_time_between_the_declared_areas(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    fitness = declare_area(http, signed_in, name="Fitness", budgetPercent=25)
    career = declare_area(http, signed_in, name="Career", budgetPercent=75)

    report = budget(http, signed_in, ORDINARY_WEEK)

    readings = {row["areaId"]: row for row in report["areas"]}
    assert readings[fitness]["targetMinutes"] == ORDINARY_WEEK_MINUTES // 4
    assert readings[career]["targetMinutes"] == ORDINARY_WEEK_MINUTES * 3 // 4
    # Nothing is planned, so no Area has consumed anything and the residual is the whole week.
    assert [row["actualMinutes"] for row in report["areas"]] == [0, 0]
    assert report["unallocatedMinutes"] == ORDINARY_WEEK_MINUTES


def test_shares_summing_to_exactly_one_hundred_do_not_zero_the_residual(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The flagship figure. `discretionary - sum(area_target)` would report zero here, and hours
    # are sitting in no block.
    declare_area(http, signed_in, name="Fitness", budgetPercent=40)
    declare_area(http, signed_in, name="Career", budgetPercent=60)

    report = budget(http, signed_in, ORDINARY_WEEK)

    assert sum(row["targetMinutes"] for row in report["areas"]) == ORDINARY_WEEK_MINUTES
    assert report["unallocatedMinutes"] == ORDINARY_WEEK_MINUTES
    assert report["oversubscriptionMinutes"] == 0


def test_shares_summing_past_one_hundred_are_reported_separately(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    declare_area(http, signed_in, name="Fitness", budgetPercent=80)
    declare_area(http, signed_in, name="Career", budgetPercent=50)

    report = budget(http, signed_in, ORDINARY_WEEK)

    assert report["oversubscriptionMinutes"] == ORDINARY_WEEK_MINUTES * 30 // 100
    # Never a negative residual, and never the same quantity as the residual.
    assert report["unallocatedMinutes"] == ORDINARY_WEEK_MINUTES
    assert report["oversubscriptionMinutes"] != report["unallocatedMinutes"]


def test_a_floor_is_honored_before_the_remainder_is_divided(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    fitness = declare_area(http, signed_in, name="Fitness", floorHours=4, budgetPercent=0)
    career = declare_area(http, signed_in, name="Career", budgetPercent=100)

    report = budget(http, signed_in, ORDINARY_WEEK)

    readings = {row["areaId"]: row for row in report["areas"]}
    assert readings[fitness]["targetMinutes"] == 240
    assert readings[career]["targetMinutes"] == ORDINARY_WEEK_MINUTES - 240


def test_a_child_areas_target_rolls_up_into_its_parent(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    career = declare_area(http, signed_in, name="Career", budgetPercent=50)
    learning = declare_area(http, signed_in, name="Learning", budgetPercent=10, parentId=career)

    report = budget(http, signed_in, ORDINARY_WEEK)

    readings = {row["areaId"]: row for row in report["areas"]}
    assert readings[career]["rolledUpTargetMinutes"] == (
        readings[career]["targetMinutes"] + readings[learning]["targetMinutes"]
    )
    # A leaf rolls up to itself, so one column renders both.
    assert readings[learning]["rolledUpTargetMinutes"] == readings[learning]["targetMinutes"]


def test_a_transition_week_reports_one_hour_less_discretionary_time(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # A spring-forward week is 167 hours. Every figure derives from the span's own minutes, so
    # the denominator says so without a special case.
    transition = budget(http, signed_in, SPRING_FORWARD_WEEK)

    assert transition["discretionaryMinutes"] == 167 * 60
    assert transition["discretionaryMinutes"] == ORDINARY_WEEK_MINUTES - 60


@pytest.mark.parametrize(
    "period",
    ["", "2026", "2026-W99", "last week"],
    ids=["empty", "a year", "week 99", "prose"],
)
def test_a_period_that_names_no_iso_week_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str], period: str
) -> None:
    response = http.get(BUDGET_PREFIX, params={PERIOD_PARAMETER: period}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    assert [error["field"] for error in response.json()["errors"]] == ["period"]


def test_the_period_is_required(http: TestClient, signed_in: dict[str, str]) -> None:
    response = http.get(BUDGET_PREFIX, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


def test_two_identical_reads_answer_identically_and_write_nothing(
    http: TestClient, signed_in: dict[str, str], live_database_url: str, owner: UserRecord
) -> None:
    # Declaring the Area is a mutation and this is not. Nothing has planned a week yet, so no
    # week carries a version row, and a read must not create one: a read that queued work would
    # make navigating to a week a mutation.
    declare_area(http, signed_in, name="Fitness", budgetPercent=40)

    first = budget(http, signed_in, ORDINARY_WEEK)
    second = budget(http, signed_in, ORDINARY_WEEK)

    assert first == second
    assert first["areas"] != []
    assert _week_input_versions(live_database_url, owner) == []


def test_another_tenants_areas_are_absent_from_this_tenants_report(
    http: TestClient, signed_in: dict[str, str], live_database_url: str
) -> None:
    stranger = provision_owner(live_database_url)
    try:
        stranger_headers = _sign_in(http, stranger.email)
        declare_area(http, stranger_headers, name="Their fitness", budgetPercent=100)

        report = budget(http, signed_in, ORDINARY_WEEK)

        assert report["areas"] == []
        assert report["unallocatedMinutes"] == ORDINARY_WEEK_MINUTES
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


def _week_input_versions(database_url: str, owner: UserRecord) -> list[tuple[str, int]]:
    """Each week's input version for this tenant, read on a connection of this test's own."""

    async def read() -> list[tuple[str, int]]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.execute(
                    select(WeekInputVersion.iso_week, WeekInputVersion.version)
                    .where(WeekInputVersion.tenant_id == owner.tenant_id)
                    .order_by(WeekInputVersion.iso_week)
                )
                return [(week, version) for week, version in found]
        finally:
            await database.engine.dispose()

    return run(read())


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
