"""Content mutations queue debounced solves for every tracked horizon week."""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.calendars.config import HORIZON_DAYS_DEFAULT
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEFAULT_SOLVE_DEBOUNCE_MS, DEV_ALLOWED_ORIGINS
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.horizon.weeks import horizon_weeks
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.routines.config import ROUTINES_PREFIX
from syncr_api.solving.config import PENDING, SOLVE
from syncr_api.solving.injection import debounce_window
from syncr_api.solving.models import Operation
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def http(live_database_url: str, settings: ServiceSettings) -> Iterator[TestClient]:
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    response = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return {
        "Cookie": f"{SESSION_COOKIE_NAME}={response.cookies[SESSION_COOKIE_NAME]}",
        "Origin": BROWSER_ORIGIN,
    }


def declare_area(http: TestClient, headers: dict[str, str], name: str) -> str:
    response = http.post(AREAS_PREFIX, json={"name": name}, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    area_id: str = response.json()["area"]["id"]
    return area_id


def track_horizon(database_url: str, tenant_id: TenantId) -> tuple[IsoWeek, ...]:
    weeks = horizon_weeks_at(datetime.now(tz=UTC))

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                versions = WeekInputVersionRepository(session, tenant_id)
                for week in weeks:
                    await versions.bump(week, at=datetime.now(tz=UTC))
        finally:
            await database.engine.dispose()

    run(seed())
    return weeks


def pending_solves(database_url: str, tenant_id: TenantId) -> list[tuple[str | None, datetime]]:
    async def read() -> list[tuple[str | None, datetime]]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(Operation)
                    .where(
                        Operation.tenant_id == tenant_id,
                        Operation.kind == SOLVE,
                        Operation.status == PENDING,
                    )
                    .order_by(Operation.iso_week)
                )
                return [(row.iso_week, row.scheduled_for) for row in found]
        finally:
            await database.engine.dispose()

    return run(read())


def horizon_weeks_at(now: datetime) -> tuple[IsoWeek, ...]:
    return horizon_weeks(today=now.date(), horizon_days=HORIZON_DAYS_DEFAULT)


def assert_pending_horizon_solves(
    database_url: str,
    tenant_id: TenantId,
    weeks: tuple[IsoWeek, ...],
    before: datetime,
    after: datetime,
) -> None:
    solves = pending_solves(database_url, tenant_id)

    assert [week for week, _due_at in solves] == [str(week) for week in weeks]
    debounce = debounce_window(DEFAULT_SOLVE_DEBOUNCE_MS)
    for _week, due_at in solves:
        assert before + debounce <= due_at <= after + debounce


def test_a_habit_mutation_requests_horizon_solves_after_the_debounce_window(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    area_id = declare_area(http, signed_in, "Fitness")
    weeks = track_horizon(live_database_url, owner.tenant_id)

    before = datetime.now(tz=UTC)
    response = http.post(
        HABITS_PREFIX,
        json={
            "areaId": area_id,
            "title": "Gym",
            "cadence": {"kind": "daily"},
            "minDurationMinutes": 30,
        },
        headers=signed_in,
    )
    after = datetime.now(tz=UTC)

    assert response.status_code == HTTPStatus.CREATED, response.text
    assert_pending_horizon_solves(live_database_url, owner.tenant_id, weeks, before, after)


def test_a_routine_mutation_requests_horizon_solves_after_the_debounce_window(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    weeks = track_horizon(live_database_url, owner.tenant_id)

    before = datetime.now(tz=UTC)
    response = http.post(
        ROUTINES_PREFIX,
        json={"title": "Sleep", "targetTime": "23:00", "durationMinutes": 480},
        headers=signed_in,
    )
    after = datetime.now(tz=UTC)

    assert response.status_code == HTTPStatus.CREATED, response.text
    assert_pending_horizon_solves(live_database_url, owner.tenant_id, weeks, before, after)


def test_a_preference_mutation_requests_horizon_solves_after_the_debounce_window(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    area_id = declare_area(http, signed_in, "Fitness")
    weeks = track_horizon(live_database_url, owner.tenant_id)

    before = datetime.now(tz=UTC)
    response = http.put(
        f"{AREAS_PREFIX}/{area_id}/preference",
        json={"windows": [{"start": "05:30", "end": "07:00"}], "strength": "strong"},
        headers=signed_in,
    )
    after = datetime.now(tz=UTC)

    assert response.status_code == HTTPStatus.OK, response.text
    assert_pending_horizon_solves(live_database_url, owner.tenant_id, weeks, before, after)


def test_an_area_mutation_requests_horizon_solves_after_the_debounce_window(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    weeks = track_horizon(live_database_url, owner.tenant_id)

    before = datetime.now(tz=UTC)
    response = http.post(
        AREAS_PREFIX,
        json={"name": "Fitness", "floorHours": 4},
        headers=signed_in,
    )
    after = datetime.now(tz=UTC)

    assert response.status_code == HTTPStatus.CREATED, response.text
    assert_pending_horizon_solves(live_database_url, owner.tenant_id, weeks, before, after)


def test_an_area_rename_requests_no_solve(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    area_id = declare_area(http, signed_in, "Fitness")
    track_horizon(live_database_url, owner.tenant_id)

    response = http.patch(
        f"{AREAS_PREFIX}/{area_id}",
        json={"name": "Fitness training"},
        headers=signed_in,
    )

    assert response.status_code == HTTPStatus.OK, response.text
    assert pending_solves(live_database_url, owner.tenant_id) == []


def test_an_unchanged_preference_requests_no_solve(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    area_id = declare_area(http, signed_in, "Fitness")
    path = f"{AREAS_PREFIX}/{area_id}/preference"
    preference = {"windows": [{"start": "05:30", "end": "07:00"}], "strength": "strong"}
    first = http.put(path, json=preference, headers=signed_in)
    assert first.status_code == HTTPStatus.OK, first.text
    track_horizon(live_database_url, owner.tenant_id)

    response = http.put(path, json=preference, headers=signed_in)

    assert response.status_code == HTTPStatus.OK, response.text
    assert pending_solves(live_database_url, owner.tenant_id) == []


def test_removing_an_absent_preference_requests_no_solve(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    area_id = declare_area(http, signed_in, "Fitness")
    track_horizon(live_database_url, owner.tenant_id)

    response = http.delete(f"{AREAS_PREFIX}/{area_id}/preference", headers=signed_in)

    assert response.status_code == HTTPStatus.OK, response.text
    assert pending_solves(live_database_url, owner.tenant_id) == []
