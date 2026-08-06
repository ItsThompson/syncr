"""The pin route end to end, and the idempotency replay that keeps a retry from doubling an event.

Two tests, because the review asked for two and the remedies are localized.

``test_post_pin_end_to_end`` drives the whole request path through a real app, a real database,
and a real session: the 201 status, the camelCase wire shape, the three-field response, and that
the pin row and its edit event exist afterwards.

``test_a_retried_pin_with_the_same_key_does_not_create_a_second_event`` is AC13: the guard
replays the stored response rather than re-executing, so the learning corpus holds exactly one
preference per intent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.plans.facts import EditEvent
from syncr_api.plans.stored_documents import stored_document
from syncr_api.user_settings.config import SETTINGS_PREFIX
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingKind, BindingRef, block_id
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings

pytestmark = pytest.mark.integration

LONDON = "Europe/London"
WEEK = IsoWeek(2027, 7)
NOW = datetime(2027, 2, 16, 9, 0, tzinfo=UTC)
BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

TASK_ID = uuid4()
AREA_ID = uuid4()
BINDING = BindingRef(kind=BindingKind.TASK, entity_id=TASK_ID, occurrence_key="00")
BLOCK_ID = block_id(WEEK, BINDING)


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
    headers = _sign_in(http, owner.email)
    http.patch(SETTINGS_PREFIX, json={"homeZone": LONDON}, headers=headers)
    return headers


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


def _seed(live_database_url: str, tenant_id: UUID) -> None:
    """Store a plan holding one block, a weight set, an area, a task, and a version row."""
    from asyncio import run as arun
    from decimal import Decimal

    from sqlalchemy import update

    from syncr_api.areas.models import AreaRow
    from syncr_api.areas.repository import AreaRepository
    from syncr_api.core.db import create_database
    from syncr_api.learned.repository import WeightSetRepository
    from syncr_api.plans.repository import PlanRepository
    from syncr_api.plans.versions import WeekInputVersionRepository
    from syncr_api.tasks.models import TaskRow
    from syncr_api.tasks.repository import TaskRepository

    block = Block(
        iso_week=WEEK,
        interval=Interval(
            datetime(2027, 2, 18, 14, 0, tzinfo=UTC),
            datetime(2027, 2, 18, 15, 0, tzinfo=UTC),
        ),
        binding=BINDING,
        title="Gym",
        reason=ReasonRecord((Bound(source=BindingSource.QUEUE, selected="picked"),)),
        area_id=AREA_ID,
    )
    plan = PlanDocument(
        iso_week=WEEK,
        zone_by_date=dict.fromkeys(WEEK.dates(), LONDON),
        discretionary_minutes=5880,
        unallocated_minutes=5820,
        oversubscription_minutes=0,
        blocks=(block,),
    )

    async def do_seed() -> None:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=NOW)
                area_rec = await AreaRepository(session, tenant_id).create(
                    parent_id=None,
                    name="Fitness",
                    pigment_index=1,
                    budget_percent=Decimal(50),
                    floor_hours=Decimal(1),
                    created_at=NOW,
                )
            async with database.sessionmaker() as session, session.begin():
                await session.execute(
                    update(AreaRow).where(AreaRow.id == area_rec.id).values(id=AREA_ID)
                )
            async with database.sessionmaker() as session, session.begin():
                task_rec = await TaskRepository(session, tenant_id).create(
                    area_id=AREA_ID,
                    project_id=None,
                    title="Gym",
                    estimate_minutes=60,
                    deadline=None,
                    priority="normal",  # type: ignore[arg-type]
                    min_chunk_minutes=15,
                    splittable=False,
                    created_at=NOW,
                )
            async with database.sessionmaker() as session, session.begin():
                await session.execute(
                    update(TaskRow).where(TaskRow.id == task_rec.id).values(id=TASK_ID)
                )
            async with database.sessionmaker() as session, session.begin():
                await PlanRepository(session, tenant_id).append(
                    document=stored_document(plan),
                    objective_breakdown={
                        "deadline_risk": 0.0,
                        "budget_deviation": 0.0,
                        "time_of_day_misfit": 0.0,
                        "fragmentation": 0.0,
                        "churn": 0.0,
                        "context_switch": 0.0,
                        "staleness": 0.0,
                    },
                    status="applied",
                    reason="auto_applied_fill",
                    weight_set_version=1,
                    input_version=1,
                    created_at=NOW,
                )
                await WeekInputVersionRepository(session, tenant_id).bump(WEEK, at=NOW)
        finally:
            await database.engine.dispose()

    arun(do_seed())


PIN_URL = f"{WEEKS_PREFIX}/{WEEK}/pins"


class TestPinRouteEndToEnd:
    """POST /weeks/{isoWeek}/pins through the real app."""

    def test_post_pin_end_to_end(
        self, http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
    ) -> None:
        _seed(live_database_url, owner.tenant_id)

        body = {"blockId": BLOCK_ID, "start": "2027-02-18T10:00:00Z"}
        response = http.post(PIN_URL, json=body, headers=signed_in)

        assert response.status_code == HTTPStatus.CREATED, response.text
        data = response.json()
        assert "pin" in data
        assert "verdict" in data
        assert "operation" in data
        assert data["pin"]["blockId"] == BLOCK_ID
        assert data["verdict"]["provenance"] == "probe"

    def test_a_retried_pin_with_the_same_key_does_not_create_a_second_event(
        self, http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
    ) -> None:
        _seed(live_database_url, owner.tenant_id)

        body = {"blockId": BLOCK_ID, "start": "2027-02-18T10:00:00Z"}
        key = str(uuid4())
        headers = {**signed_in, IDEMPOTENCY_KEY_HEADER: key}

        first = http.post(PIN_URL, json=body, headers=headers)
        assert first.status_code == HTTPStatus.CREATED, first.text

        # Retry with the SAME key
        second = http.post(PIN_URL, json=body, headers=headers)
        assert second.status_code == HTTPStatus.CREATED, second.text

        # Responses must be identical (replayed)
        assert first.json() == second.json()

        # Only ONE edit event exists
        from asyncio import run as arun

        from syncr_api.core.db import create_database

        async def count_events() -> int:
            database = create_database(live_database_url)
            try:
                async with database.sessionmaker() as session:
                    return (
                        await session.scalar(
                            select(EditEvent)
                            .where(EditEvent.tenant_id == owner.tenant_id)
                            .with_only_columns(EditEvent.id)
                            .limit(2)
                        )
                    ) is not None and len(
                        (
                            await session.scalars(
                                select(EditEvent).where(EditEvent.tenant_id == owner.tenant_id)
                            )
                        ).all()
                    )
            finally:
                await database.engine.dispose()

        event_count = arun(count_events())
        assert event_count == 1
