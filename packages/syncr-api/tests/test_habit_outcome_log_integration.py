"""Both habit figures against a log a real request wrote, read through the wiring production uses.

The service suite asserts the two derivations against a log handed in through the reader seam, so
it holds whatever the fake was given. This asserts the half a fake cannot: that the rows a habit
response answers from are rows in ``block_outcomes``, found by the projection the habit module is
wired to. Wire the seam back to an empty log and both figures collapse, which is the whole claim.

**The rows are written by the outcome routes rather than by this suite.** A binding reaches the
table in the spelling ``stored_binding`` writes, and the projection extracts two of its keys, so a
seeded row spelled by hand would prove the reader matches the seeder rather than the writer. That
is the failure mode worth defending against here: a key nobody writes matches no row, and the
symptom is every rotation habit reading as sitting on its first variant with nothing reporting it.

**The index is asserted against the live schema.** The model-level assertion in
``test_plan_storage_boundary.py`` says the projection states both keys the index leads with, and it
passes against a database that never created the index: the two facts are declared in different
files and only one of them is what makes the read cheap.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.outcomes.config import BLOCKS_PREFIX, DAYS_PREFIX
from syncr_api.plans.config import APPLIED, BLOCK_OUTCOMES_TABLE
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import BINDING, ENTITY_ID, KIND, stored_document
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef
from syncr_domain.intervals import Interval
from syncr_domain.plan import Block, PlanDocument
from syncr_domain.reasons import Bound, ReasonRecord
from syncr_domain.weeks import IsoWeek, active_zone_by_date
from syncr_domain.zones import ZoneProfile
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import AreaId, TenantId
    from syncr_domain.zones import Date

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
UTC_ZONE = "UTC"

# The index the projection's two predicates exist to reach.
BINDING_INDEX = "ix_block_outcomes_tenant_id_binding_entity"
INDEX_DEFINITION = text(
    "SELECT indexdef FROM pg_indexes WHERE tablename = :table AND indexname = :index"
)

A_REASON = ReasonRecord((Bound(BindingSource.ROTATION, "Gym · rotation"),))
GYM_SPLIT = ["Push", "Pull", "Legs"]
THREE_A_WEEK: dict[str, Any] = {"kind": "times_per_week", "timesPerWeek": 3}

# Yesterday, so every block is behind `now`: a day that has not begun is not confirmable, and an
# occurrence that has not come due is not missed.
YESTERDAY = (utc_now() - timedelta(days=1)).date()
WEEK = IsoWeek.containing(YESTERDAY)


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
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def declare_area(http: TestClient, headers: dict[str, str]) -> AreaId:
    answered = http.post(AREAS_PREFIX, json={"name": f"Fitness {uuid4().hex[:8]}"}, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return UUID(answered.json()["area"]["id"])


def declare_habit(
    http: TestClient, headers: dict[str, str], area_id: AreaId, **overrides: object
) -> UUID:
    body: dict[str, Any] = {
        "areaId": str(area_id),
        "title": "Gym",
        "cadence": dict(THREE_A_WEEK),
        "minDurationMinutes": 60,
        "missPolicy": "forgive",
    }
    body.update(overrides)
    answered = http.post(HABITS_PREFIX, json=body, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return UUID(answered.json()["id"])


def read_habit(http: TestClient, headers: dict[str, str], habit_id: UUID) -> dict[str, Any]:
    answered = http.get(f"{HABITS_PREFIX}/{habit_id}", headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    read: dict[str, Any] = answered.json()
    return read


def an_occurrence(*, habit_id: UUID, index: int, hour: int, area_id: AreaId) -> Block:
    """One habit occurrence as the assembler places it: a block bound to the habit and its index."""
    starts = datetime.combine(YESTERDAY, time(hour), tzinfo=UTC)
    return Block(
        iso_week=WEEK,
        interval=Interval(starts, starts + timedelta(hours=1)),
        binding=BindingRef.for_habit(habit_id, index=index),
        title="Gym",
        reason=A_REASON,
        area_id=area_id,
    )


def seed_plan(database_url: str, tenant_id: TenantId, blocks: Sequence[Block]) -> None:
    """One applied revision holding ``blocks``, appended through the repository that owns it.

    There is no route that produces a plan and there is not meant to be one, so the plan of record
    the outcome routes address a block through is written the way the horizon maintainer writes it.
    """
    document = PlanDocument(
        iso_week=WEEK,
        zone_by_date=active_zone_by_date(WEEK, ZoneProfile(UTC_ZONE)),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
        blocks=tuple(blocks),
    )

    async def append() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await PlanRepository(session, tenant_id).append(
                    document=stored_document(document),
                    objective_breakdown={},
                    status=APPLIED,
                    reason="materialized",
                    weight_set_version=1,
                    input_version=1,
                    created_at=utc_now(),
                )
        finally:
            await database.engine.dispose()

    run(append())


def record_skip(http: TestClient, headers: dict[str, str], block: Block) -> None:
    answered = http.put(
        f"{BLOCKS_PREFIX}/{block.id}/outcome",
        json={"isoWeek": str(WEEK), "state": "skipped"},
        headers=headers,
    )
    assert answered.status_code == HTTPStatus.OK, answered.text


def confirm_day(http: TestClient, headers: dict[str, str], on: Date) -> None:
    answered = http.post(f"{DAYS_PREFIX}/{on.isoformat()}/confirm", headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text


def test_a_confirmed_completion_moves_the_cursor_the_habit_resource_reports(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The cursor is a count of confirmed completions in the log, so a habit whose occurrence was
    # confirmed reads one variant on from a habit whose log holds nothing.
    area_id = declare_area(http, signed_in)
    habit_id = declare_habit(http, signed_in, area_id, bindingSource="rotation", variants=GYM_SPLIT)
    seed_plan(
        live_database_url,
        owner.tenant_id,
        [an_occurrence(habit_id=habit_id, index=0, hour=9, area_id=area_id)],
    )

    before = read_habit(http, signed_in, habit_id)["cursor"]
    confirm_day(http, signed_in, YESTERDAY)
    after = read_habit(http, signed_in, habit_id)["cursor"]

    assert (before["variant"], before["confirmedCompletions"]) == ("Push", 0)
    assert (after["variant"], after["confirmedCompletions"]) == ("Pull", 1)
    assert after["previousVariant"] == "Push"


def test_confirmed_skips_reach_the_debt_figure_the_habit_resource_reports(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The other derivation over the same read, and the one no test has ever taken through the
    # database: two skips of a `debt` habit's occurrences are two outstanding sessions, under a cap
    # of two periods times three a week.
    area_id = declare_area(http, signed_in)
    habit_id = declare_habit(http, signed_in, area_id, title="Anki", missPolicy="debt")
    occurrences = [
        an_occurrence(habit_id=habit_id, index=index, hour=hour, area_id=area_id)
        for index, hour in enumerate((9, 11))
    ]
    seed_plan(live_database_url, owner.tenant_id, occurrences)

    before = read_habit(http, signed_in, habit_id)["debt"]
    for occurrence in occurrences:
        record_skip(http, signed_in, occurrence)
    confirm_day(http, signed_in, YESTERDAY)
    after = read_habit(http, signed_in, habit_id)["debt"]

    assert (before["misses"], before["outstanding"]) == (0, 0)
    assert (after["misses"], after["outstanding"], after["cap"]) == (2, 2, 6)
    assert not after["raisedInWeeklySession"]


def test_the_live_schema_carries_the_index_the_projection_reads_through(
    live_database_url: str,
) -> None:
    # The read runs once per habit collection and its two predicates buy nothing but this index, so
    # an index the migration failed to create has no symptom other than a sequential scan. Asserted
    # over the database's own definition, in the order a B-tree is read in: the tenant leads, so the
    # scope is part of the index condition rather than a filter applied after another tenant's rows
    # have been read.
    async def definition() -> str | None:
        database = create_database(live_database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalar(
                    INDEX_DEFINITION,
                    {"table": BLOCK_OUTCOMES_TABLE, "index": BINDING_INDEX},
                )
                return None if found is None else str(found)
        finally:
            await database.engine.dispose()

    indexdef = run(definition())

    assert indexdef is not None, f"{BLOCK_OUTCOMES_TABLE} has no index named {BINDING_INDEX}"
    keys = [TENANT_ID_COLUMN, f"({BINDING} ->> '{KIND}'", f"({BINDING} ->> '{ENTITY_ID}'"]
    for key in keys:
        assert key in indexdef, f"{BINDING_INDEX} does not read {key}: {indexdef}"
    assert [indexdef.index(key) for key in keys] == sorted(indexdef.index(key) for key in keys)
