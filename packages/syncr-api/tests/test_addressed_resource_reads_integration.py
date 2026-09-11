"""The reads left after the content resources: each driven by a record the api itself holds.

Every parameterized read outside the content collections is either a record this api stored --
an anchor, an anchor type, a calendar source, a day of the plan of record, an enqueued
operation, a declared off-plan period -- or the one read that leaves this api: the calendars
behind a feed, which answers from the provider behind it rather than from these tables. The
record reads are driven here, and the provider read stays exempt in
``tests.boundaries.EXEMPT_PARAMETERIZED_READS`` with the reason it cannot be driven: a drive
would be an outbound call to a third party.

*A read is not a mutation.* Every read ``tests.boundaries.addressed_resource_reads`` derives is
driven with a real addressed resource, and the row count of every tenant-scoped table this
application declares is compared against the same snapshot after EACH read. The paths come from
that contribution to the census in ``test_parameterized_read_census.py``, so a record read added
beside these is driven here without this module being extended.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from syncr_api.anchors.config import ANCHOR_TYPES_PREFIX, ANCHORS_PREFIX
from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import ANCHOR_SOURCE, CALENDAR_SOURCES_PREFIX, ICS
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.calendars.records import CalendarSourceRecord
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.offplan.config import OFF_PLAN_PREFIX
from syncr_api.outcomes.config import DAYS_PREFIX
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.solving.config import OPERATIONS_PREFIX, SOLVE
from syncr_api.solving.repository import OperationRepository
from syncr_api.user_settings.solve_inputs import TrackedWeekInputVersions
from syncr_domain.intervals import Interval
from tests.boundaries import addressed_resource_reads, path_parameters
from tests.live_tenants import provision_owner, remove_tenant, row_counts, run
from tests.live_weeks import (
    declare_the_minimum,
    produce_a_plan,
    set_home_zone,
    sign_in,
    the_live_plan,
    this_week,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

pytestmark = pytest.mark.integration

UTC_ZONE = "UTC"

NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)
TIMETABLE = "https://example.ac.uk/timetable.ics"

# The reads this module exists for, spelled so their arrival in or departure from the derived set
# is a diff a reader sees rather than a change a walk swallows. The provider-backed sub-collection
# under a calendar source is deliberately absent: it reaches past the record to the third party
# behind it, and no driver here can answer for that call.
RECORD_READS = (
    f"{ANCHORS_PREFIX}/{{anchor_id}}",
    f"{ANCHOR_TYPES_PREFIX}/{{anchor_type_id}}",
    f"{CALENDAR_SOURCES_PREFIX}/{{source_id}}",
    f"{DAYS_PREFIX}/{{date}}",
    f"{OFF_PLAN_PREFIX}/{{period_id}}",
    f"{OPERATIONS_PREFIX}/{{operation_id}}",
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


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    """The headers a signed-in browser sends, for a tenant whose home zone is UTC."""
    headers = sign_in(http, owner.email)
    set_home_zone(http, headers, UTC_ZONE)
    return headers


def add_source(http: TestClient, headers: dict[str, str]) -> str:
    """One declared ICS feed, created through its own declaring route."""
    answered = http.post(
        CALENDAR_SOURCES_PREFIX,
        json={"provider": ICS, "displayName": "University timetable", "externalId": TIMETABLE},
        headers=headers,
    )
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return str(answered.json()["id"])


def declare_an_anchor_type(http: TestClient, headers: dict[str, str]) -> str:
    answered = http.post(
        ANCHOR_TYPES_PREFIX,
        json={"name": "Lecture", "matchTitleContains": "Lecture"},
        headers=headers,
    )
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return str(answered.json()["id"])


def seed_anchors(database_url: str, tenant_id: TenantId, source_id: str) -> None:
    """Put one commitment in the table the way a sync would, on a loop of this fixture's own.

    Through the reconciler rather than through a route, because there is no route that creates an
    anchor: that absence is the invariant, not a gap in the fixtures.
    """

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                reconciler = AnchorReconciler(
                    AnchorRepository(session, tenant_id),
                    AnchorTypeRepository(session, tenant_id),
                    versions=TrackedWeekInputVersions(
                        WeekInputVersionRepository(session, tenant_id), clock=lambda: NOW
                    ),
                    home_zone=UTC_ZONE,
                )
                event = RawEvent(
                    uid="anchor-11@timetable",
                    series_uid=None,
                    title="Lecture",
                    interval=Interval(NOW, NOW + timedelta(minutes=120)),
                    location=None,
                    sequence=0,
                    all_day=False,
                )
                await reconciler.reconcile(
                    _a_source(UUID(source_id), tenant_id),
                    FetchOutcome(events=(event,), events_read=1, reparsed=True),
                )
        finally:
            await database.engine.dispose()

    run(seed())


def existing_solve(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> str:
    """The solve the fixture's declarations already requested for this week."""

    async def read() -> str:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                operation = await OperationRepository(session, tenant_id).latest_of(
                    iso_week, kinds=(SOLVE,)
                )
                assert operation is not None, "the declarations did not request a solve"
                return str(operation.id)
        finally:
            await database.engine.dispose()

    return run(read())


def _a_source(source_id: UUID, tenant_id: TenantId) -> CalendarSourceRecord:
    return CalendarSourceRecord(
        id=source_id,
        tenant_id=tenant_id,
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="University timetable",
        external_id=TIMETABLE,
        included=True,
        horizon_days=None,
        created_at=NOW,
    )


@pytest.fixture
def identifiers(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> dict[str, str]:
    """One real record of each kind, each created the way production creates it.

    The day is a date the tenant's plan has blocks on: the produced week's first block, which is
    what the ledger read addresses rather than a date it would answer with an empty grid.
    """
    week: IsoWeek = this_week()
    declare_the_minimum(http, signed_in, live_database_url, owner.tenant_id)
    produce_a_plan(live_database_url, owner.tenant_id, week)
    planned = the_live_plan(live_database_url, owner.tenant_id, week)
    assert planned.blocks, "the produced week holds no block, so the day below addresses nothing"
    day = planned.blocks[0].interval.start.date()

    source = add_source(http, signed_in)
    anchor_type = declare_an_anchor_type(http, signed_in)
    seed_anchors(live_database_url, owner.tenant_id, source)
    listed = http.get(
        ANCHORS_PREFIX,
        params={
            "from": (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "to": (NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        },
        headers=signed_in,
    )
    assert listed.status_code == HTTPStatus.OK, listed.text
    anchors: list[dict[str, str]] = listed.json()["anchors"]
    assert anchors, "no anchor was seeded, so the anchor read below addresses nothing"

    declared = http.post(
        OFF_PLAN_PREFIX,
        json={
            "start": "2026-10-23T14:00:00Z",
            "end": "2026-10-26T09:00:00Z",
            "keepFrame": False,
            "label": "Away",
        },
        headers=signed_in,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text

    return {
        "anchor_id": anchors[0]["id"],
        "anchor_type_id": anchor_type,
        "source_id": source,
        "date": day.isoformat(),
        "period_id": str(declared.json()["id"]),
        # The declarations request the one non-terminal solve the week may hold.
        "operation_id": existing_solve(live_database_url, owner.tenant_id, week),
    }


def every_record_read(settings: ServiceSettings) -> list[str]:
    """Every read the published contribution derives, off the app's own route table.

    Read off the contribution rather than filtered here, which is what the consumption rule in
    ``test_parameterized_read_census.py`` holds this module to. Nothing is excluded by name:
    the derivation's shape rule already keeps the provider-backed sub-collection out, and a
    derivation widened to include it must redden the drive below rather than be absorbed.
    """
    paths = addressed_resource_reads(create_app(settings))
    assert paths, "no record read was found, so the guards below asserted nothing"
    return paths


def addressed(path: str, identifiers: dict[str, str]) -> str:
    """The template with each parameter replaced by the identifier that names it."""
    for name in sorted(path_parameters(path)):
        path = path.replace(f"{{{name}}}", identifiers[name])
    return path


def test_every_record_read_is_driven_here_and_answers_its_record(
    http: TestClient,
    signed_in: dict[str, str],
    identifiers: dict[str, str],
    settings: ServiceSettings,
) -> None:
    """Named so the arrival or departure of a read is a diff, and so the walk is not empty."""
    reads = every_record_read(settings)
    assert set(reads) >= set(RECORD_READS)

    for path in reads:
        answered = http.get(addressed(path, identifiers), headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, (path, answered.text)


def test_the_day_read_answers_the_blocks_the_plan_holds(
    http: TestClient, signed_in: dict[str, str], identifiers: dict[str, str]
) -> None:
    """A date without blocks would make the drive pass while addressing nothing."""
    answered = http.get(f"{DAYS_PREFIX}/{identifiers['date']}", headers=signed_in)

    assert answered.status_code == HTTPStatus.OK, answered.text
    body: dict[str, object] = answered.json()
    assert body["date"] == identifiers["date"]
    block_count = body["blockCount"]
    assert isinstance(block_count, int)
    assert block_count >= 1


def test_no_record_read_brings_a_row_into_existence(
    http: TestClient,
    signed_in: dict[str, str],
    identifiers: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    settings: ServiceSettings,
    source_root: Path,
) -> None:
    """Every scoped table is counted once, and again after EACH read, against that same snapshot.

    The operation read is the interesting one: reporting an operation's truth could be done by
    writing a receipt onto it, and this is the assertion that says it is not.
    """
    before = row_counts(live_database_url, owner.tenant_id, source_root)

    for path in every_record_read(settings):
        answered = http.get(addressed(path, identifiers), headers=signed_in)
        assert answered.status_code == HTTPStatus.OK, (path, answered.text)

        assert row_counts(live_database_url, owner.tenant_id, source_root) == before, path
