"""The four outcome and day routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a real
database can:

- the wire shape is camelCase, and a span reaches it as two instants
- one outcome row per block, whichever plan of record recorded it, enforced by the index
- a `moved` outcome creates no `Pin` row, which cannot be asserted anywhere a pin table does not
  exist
- a retried recording under one `Idempotency-Key` does not become a second row
- a correction after a confirmation re-derives the rotation cursor with no further call, through
  HTTP
- another tenant's block is a 404 rather than an edit
- confirming bumps the week input version rows the next solve reads

A plan of record is seeded through ``PlanRepository`` rather than over HTTP, because materialization
is deliberately not a user-facing act: there is no route that creates a plan, and there is not meant
to be one.

**The dates are derived from the real clock**, because the confirmation routes refuse a day that
has not begun and the count of unconfirmed days is taken relative to today. A fixed date would pass
until it went past and then fail for a reason that had nothing to do with the code.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.outcomes.config import BLOCKS_PREFIX, DAYS_PREFIX
from syncr_api.plans.config import APPLIED
from syncr_api.plans.facts import BlockOutcome, Pin
from syncr_api.plans.models import WeekInputVersion
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.config import SETTINGS_PREFIX
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

A_REASON = ReasonRecord((Bound(BindingSource.ROTATION, "Gym · rotation"),))
GYM = uuid4()

# Yesterday, so every block this suite plans is behind `now` and every day it confirms has begun.
YESTERDAY = (utc_now() - timedelta(days=1)).date()
WEEK = IsoWeek.containing(YESTERDAY)


def an_instant(on: Date, hour: int) -> datetime:
    return datetime.combine(on, time(hour), tzinfo=UTC)


def a_gym_block(
    *, on: Date, hour: int, index: int, area_id: AreaId, make_up: bool = False
) -> Block:
    return Block(
        iso_week=IsoWeek.containing(on),
        interval=Interval(an_instant(on, hour), an_instant(on, hour + 1)),
        binding=BindingRef.for_habit(GYM, index=index),
        title="Gym",
        reason=A_REASON,
        area_id=area_id,
        make_up=make_up,
    )


def a_week(blocks: Sequence[Block], *, iso_week: IsoWeek = WEEK) -> PlanDocument:
    return PlanDocument(
        iso_week=iso_week,
        zone_by_date=active_zone_by_date(iso_week, ZoneProfile(UTC_ZONE)),
        discretionary_minutes=0,
        unallocated_minutes=0,
        oversubscription_minutes=0,
        blocks=tuple(blocks),
    )


@pytest.fixture
def owner(live_database_url: str) -> Iterator[UserRecord]:
    account = provision_owner(live_database_url)
    yield account
    remove_tenant(live_database_url, account.tenant_id)


@pytest.fixture
def other_owner(live_database_url: str) -> Iterator[UserRecord]:
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
    """The headers a signed-in browser sends, for a tenant whose home zone is UTC."""
    headers = sign_in(http, owner.email)
    answered = http.patch(SETTINGS_PREFIX, json={"homeZone": UTC_ZONE}, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    return headers


def declare_area(http: TestClient, headers: dict[str, str], name: str = "Fitness") -> AreaId:
    answered = http.post(AREAS_PREFIX, json={"name": name}, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return UUID(answered.json()["area"]["id"])


def seed_plan(database_url: str, tenant_id: TenantId, document: PlanDocument) -> str:
    """One applied revision holding ``document``, appended through the repository that owns it."""

    async def append() -> str:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                revision = await PlanRepository(session, tenant_id).append(
                    document=stored_document(document),
                    objective_breakdown={},
                    status=APPLIED,
                    reason="materialized",
                    weight_set_version=1,
                    input_version=1,
                    created_at=utc_now(),
                )
                return str(revision.id)
        finally:
            await database.engine.dispose()

    return run(append())


def outcome_rows(database_url: str, tenant_id: TenantId) -> list[BlockOutcome]:
    async def read() -> list[BlockOutcome]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(BlockOutcome)
                    .where(BlockOutcome.tenant_id == tenant_id)
                    .order_by(BlockOutcome.occurred_at, BlockOutcome.block_id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def counted(
    database_url: str, tenant_id: TenantId, model: type[Pin] | type[WeekInputVersion]
) -> int:
    async def count() -> int:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
                )
                return found or 0
        finally:
            await database.engine.dispose()

    return run(count())


def seed_versions(database_url: str, tenant_id: TenantId, weeks: Sequence[IsoWeek]) -> None:
    """A version row per week, as the first reference to a week creates one."""

    async def bump() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                versions = WeekInputVersionRepository(session, tenant_id)
                for week in weeks:
                    await versions.bump(week, at=utc_now())
        finally:
            await database.engine.dispose()

    run(bump())


def versions_of(database_url: str, tenant_id: TenantId) -> dict[str, int]:
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


def record(
    http: TestClient,
    headers: dict[str, str],
    block_id: str,
    body: dict[str, Any],
    *,
    key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    sent = dict(headers)
    if key is not None:
        sent[IDEMPOTENCY_KEY_HEADER] = key
    answered = http.put(
        f"{BLOCKS_PREFIX}/{block_id}/outcome",
        json={"isoWeek": str(WEEK), **body},
        headers=sent,
    )
    return answered.status_code, answered.json()


def read_day(http: TestClient, headers: dict[str, str], on: Date) -> dict[str, Any]:
    answered = http.get(f"{DAYS_PREFIX}/{on.isoformat()}", headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    body: dict[str, Any] = answered.json()
    return body


def confirm(
    http: TestClient, headers: dict[str, str], on: Date, *, key: str | None = None
) -> tuple[int, dict[str, Any]]:
    sent = dict(headers)
    if key is not None:
        sent[IDEMPOTENCY_KEY_HEADER] = key
    answered = http.post(f"{DAYS_PREFIX}/{on.isoformat()}/confirm", headers=sent)
    return answered.status_code, answered.json()


def confirm_range(
    http: TestClient, headers: dict[str, str], first: Date, last: Date
) -> tuple[int, dict[str, Any]]:
    answered = http.post(
        f"{DAYS_PREFIX}/confirm-range",
        json={"from": first.isoformat(), "to": last.isoformat()},
        headers=headers,
    )
    return answered.status_code, answered.json()


@pytest.fixture
def planned(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> tuple[Block, Block]:
    """Two Gym blocks yesterday, in a plan of record this tenant holds."""
    area_id = declare_area(http, signed_in)
    first = a_gym_block(on=YESTERDAY, hour=9, index=0, area_id=area_id)
    second = a_gym_block(on=YESTERDAY, hour=11, index=1, area_id=area_id)
    seed_plan(live_database_url, owner.tenant_id, a_week([first, second]))
    return (first, second)


# --------------------------------------------------------------------------------
# The ledger
# --------------------------------------------------------------------------------


def test_the_ledger_states_the_block_count_and_how_many_are_presumed(
    http: TestClient, signed_in: dict[str, str], planned: tuple[Block, Block]
) -> None:
    day = read_day(http, signed_in, YESTERDAY)

    assert day["date"] == YESTERDAY.isoformat()
    assert day["blockCount"] == 2
    assert day["presumedCount"] == 2
    assert day["confirmedAt"] is None
    assert day["unconfirmedDays"] == 1
    assert [row["blockId"] for row in day["behind"]] == [one.id for one in planned]
    assert day["ahead"] == []


def test_a_row_carries_the_range_the_duration_the_area_and_the_title(
    http: TestClient, signed_in: dict[str, str], planned: tuple[Block, Block]
) -> None:
    first, _ = planned

    row = read_day(http, signed_in, YESTERDAY)["behind"][0]

    assert row["interval"]["start"] == first.interval.start.isoformat().replace("+00:00", "Z")
    assert row["interval"]["end"] == first.interval.end.isoformat().replace("+00:00", "Z")
    assert row["durationMinutes"] == 60
    assert row["areaName"] == "Fitness"
    assert row["title"] == "Gym"
    assert row["origin"] == "habit"
    assert row["outcome"] is None


def test_a_day_the_tenants_zone_does_not_hold_is_a_422_naming_the_date(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Pacific/Apia skipped 30 December 2011 when it crossed the date line, and any past day may be
    # named. There is no day to render, so the refusal names the date and the zone.
    answered = http.patch(SETTINGS_PREFIX, json={"homeZone": "Pacific/Apia"}, headers=signed_in)
    assert answered.status_code == HTTPStatus.OK, answered.text

    refused = http.get(f"{DAYS_PREFIX}/2011-12-30", headers=signed_in)

    assert refused.status_code == ValidationFailed.status
    assert "does not exist in Pacific/Apia" in refused.json()["detail"]


def test_a_malformed_date_is_the_frameworks_own_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    refused = http.get(f"{DAYS_PREFIX}/not-a-date", headers=signed_in)

    assert refused.status_code == ValidationFailed.status


# --------------------------------------------------------------------------------
# Recording an outcome
# --------------------------------------------------------------------------------


def test_a_partial_outcome_reaches_the_wire_with_its_minutes(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    first, _ = planned

    status, recorded = record(http, signed_in, first.id, {"state": "partial", "actualMinutes": 35})

    assert status == HTTPStatus.OK, recorded
    assert recorded["state"] == "partial"
    assert recorded["actualMinutes"] == 35
    assert recorded["confirmedAt"] is None
    stored = outcome_rows(live_database_url, owner.tenant_id)
    assert [(row.block_id, row.state, row.actual_minutes) for row in stored] == [
        (first.id, "partial", 35)
    ]


def test_a_partial_without_its_minutes_is_refused_and_stores_nothing(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    first, _ = planned

    status, refused = record(http, signed_in, first.id, {"state": "partial"})

    assert status == ValidationFailed.status, refused
    assert "duration-estimate signal" in refused["detail"]
    assert outcome_rows(live_database_url, owner.tenant_id) == []


def test_a_moved_outcome_records_its_interval_and_creates_no_pin(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # A `moved` outcome describes the past and a pin constrains the future, so no pin appears. This
    # is the assertion that needs a real pin table to mean anything.
    first, _ = planned
    elsewhere = Interval(an_instant(YESTERDAY, 14), an_instant(YESTERDAY, 15))

    status, recorded = record(
        http,
        signed_in,
        first.id,
        {
            "state": "moved",
            "actualInterval": {
                "start": elsewhere.start.isoformat(),
                "end": elsewhere.end.isoformat(),
            },
        },
    )

    assert status == HTTPStatus.OK, recorded
    assert recorded["actualInterval"]["start"] == elsewhere.start.isoformat().replace("+00:00", "Z")
    assert counted(live_database_url, owner.tenant_id, Pin) == 0


def test_recording_the_same_block_twice_replaces_the_row_rather_than_adding_one(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # The identity the schema enforces: one row per block, whichever plan of record recorded it.
    # Two rows for one habit occurrence would put a rotation cursor a variant past the truth.
    first, _ = planned

    record(http, signed_in, first.id, {"state": "completed"})
    status, corrected = record(http, signed_in, first.id, {"state": "skipped"})

    assert status == HTTPStatus.OK, corrected
    stored = outcome_rows(live_database_url, owner.tenant_id)
    assert [(row.block_id, row.state) for row in stored] == [(first.id, "skipped")]


def test_recording_a_made_up_occurrence_stores_the_mark_on_the_rows_binding(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    """The mark travels from the block to the log, so the debt derivation can read it there.

    Both halves are asserted against the stored document, because the projection reads the
    binding's own keys: a mark stored beside the binding rather than inside it would match no
    read and every made-up completion would silently discharge nothing.
    """
    area_id = declare_area(http, signed_in)
    fresh = a_gym_block(on=YESTERDAY, hour=9, index=0, area_id=area_id)
    made_up = a_gym_block(on=YESTERDAY, hour=11, index=1, area_id=area_id, make_up=True)
    seed_plan(live_database_url, owner.tenant_id, a_week([fresh, made_up]))

    for block in (fresh, made_up):
        status, body = record(http, signed_in, block.id, {"state": "completed"})
        assert status == HTTPStatus.OK, body

    stored = {row.block_id: row.binding for row in outcome_rows(live_database_url, owner.tenant_id)}

    assert stored[fresh.id]["make_up"] is False
    assert stored[made_up.id]["make_up"] is True


def test_confirming_a_day_presumes_a_made_up_occurrence_with_its_mark(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    """A made-up occurrence the user never touched is presumed complete AS a make-up.

    The day's confirmation writes its rows through ``settle``, so this is the half of the write
    path a recording never reaches: without the mark here, a disengaged user's presumed completions
    would stop settling the misses they were placed for.
    """
    area_id = declare_area(http, signed_in)
    made_up = a_gym_block(on=YESTERDAY, hour=11, index=1, area_id=area_id, make_up=True)
    seed_plan(live_database_url, owner.tenant_id, a_week([made_up]))

    status, _ = confirm(http, signed_in, YESTERDAY)
    assert status == HTTPStatus.OK

    (row,) = outcome_rows(live_database_url, owner.tenant_id)
    assert (row.state, row.binding["make_up"]) == ("presumed", True)


def test_a_move_longer_than_a_day_is_refused_over_the_wire(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # The bound `partial`'s minutes already carry, on the span `moved` reports. The write is live
    # and the row is permanent, so an unbounded span would sit in the log attributing five million
    # minutes to its content for every future reader of the attribution table.
    first, _ = planned
    a_decade = Interval(an_instant(YESTERDAY, 9), an_instant(YESTERDAY, 9) + timedelta(days=3650))

    status, refused = record(
        http,
        signed_in,
        first.id,
        {
            "state": "moved",
            "actualInterval": {
                "start": a_decade.start.isoformat(),
                "end": a_decade.end.isoformat(),
            },
        },
    )

    assert status == ValidationFailed.status, refused
    assert "may report at most 1440" in refused["detail"]
    assert outcome_rows(live_database_url, owner.tenant_id) == []


def test_one_idempotency_key_replaying_a_recording_does_not_write_a_second_row(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    first, _ = planned
    key = uuid4().hex

    once = record(http, signed_in, first.id, {"state": "completed"}, key=key)
    twice = record(http, signed_in, first.id, {"state": "completed"}, key=key)

    assert once == twice
    assert len(outcome_rows(live_database_url, owner.tenant_id)) == 1


def test_another_tenants_block_is_a_404_rather_than_an_edit(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    other_owner: UserRecord,
    live_database_url: str,
) -> None:
    first, _ = planned
    intruder = sign_in(http, other_owner.email)

    status, refused = record(http, intruder, first.id, {"state": "completed"})

    assert status == NotFound.status, refused
    assert outcome_rows(live_database_url, other_owner.tenant_id) == []


# --------------------------------------------------------------------------------
# Confirming, and what a confirmation re-derives
# --------------------------------------------------------------------------------


def test_confirming_a_day_records_every_block_and_keeps_what_was_already_said(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    first, second = planned
    record(http, signed_in, first.id, {"state": "skipped"})

    status, day = confirm(http, signed_in, YESTERDAY)

    assert status == HTTPStatus.OK, day
    assert day["confirmedAt"] is not None
    assert day["unconfirmedDays"] == 0
    stored = outcome_rows(live_database_url, owner.tenant_id)
    assert {(row.block_id, row.state) for row in stored} == {
        (first.id, "skipped"),
        (second.id, "presumed"),
    }
    assert all(row.confirmed_at is not None for row in stored)


def test_confirming_a_day_twice_keeps_the_instant_it_was_first_settled_at(
    http: TestClient, signed_in: dict[str, str], planned: tuple[Block, Block]
) -> None:
    _, first_answer = confirm(http, signed_in, YESTERDAY)

    _, second_answer = confirm(http, signed_in, YESTERDAY)

    assert first_answer["confirmedAt"] == second_answer["confirmedAt"]


def test_correcting_an_outcome_after_a_confirmation_keeps_the_stored_confirmation(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # The write's own rule, against the real statement rather than against a fake of it: recording
    # states the state and the two carried columns and NOTHING else, so a correction in March
    # against a day settled in February leaves the day settled in February.
    #
    # Read at the row rather than through the cursor, because the cursor cannot tell the two apart:
    # a correction that cleared `confirmed_at` would leave the row neither a completion nor a miss,
    # which reads as the same variant a corrected skip does. The column is the only witness.
    first, _ = planned
    _, day = confirm(http, signed_in, YESTERDAY)
    settled_at_first = day["confirmedAt"]

    status, corrected = record(http, signed_in, first.id, {"state": "skipped"})

    assert status == HTTPStatus.OK, corrected
    assert corrected["confirmedAt"] == settled_at_first
    stored = {row.block_id: row for row in outcome_rows(live_database_url, owner.tenant_id)}
    assert stored[first.id].state == "skipped"
    assert stored[first.id].confirmed_at is not None
    assert read_day(http, signed_in, YESTERDAY)["confirmedAt"] == settled_at_first



def seed_a_debt_habit(database_url: str, tenant_id: TenantId, habit_id: UUID, area_id: AreaId) -> None:
    """One ``debt``-policy habit row behind the blocks the suite binds, charge at zero."""
    async def write() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await session.execute(
                    text(
                        "INSERT INTO habits (id, tenant_id, area_id, title, cadence_kind, "
                        "cadence_times_per_week, duration_min_minutes, duration_max_minutes, "
                        "miss_policy, binding_source, variants, debt_cap_periods, "
                        "charged_misses, created_at) VALUES (:id, :tenant, :area, 'Gym', "
                        "'times_per_week', 4, 60, 90, 'debt', 'fixed', cast('[]' as jsonb), "
                        "2, 0, now())"
                    ),
                    {"id": habit_id, "tenant": tenant_id, "area": area_id},
                )
        finally:
            await database.engine.dispose()

    run(write())


@pytest.mark.integration
def test_recording_a_skip_restates_the_stored_charge_the_habit_route_answers_from(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    """The figure a habit response answers is the row the outcome write restated.

    The skip is recorded over HTTP and the debt read back from the habit resource in a second
    request. Nothing walks the log to answer it: the count was restated inside the recording's
    own transaction, which is what keeps it standing whatever windows later readers take.
    """
    # The day is settled FIRST, so the recording lands as a correction onto an already-confirmed
    # row: the charge moves through the recording act alone, not through the day's confirmation.
    area_id = declare_area(http, signed_in)
    block = a_gym_block(on=YESTERDAY, hour=9, index=0, area_id=area_id)
    seed_plan(live_database_url, owner.tenant_id, a_week([block]))
    seed_a_debt_habit(live_database_url, owner.tenant_id, GYM, area_id)
    confirmed, _ = confirm(http, signed_in, YESTERDAY)
    assert confirmed == HTTPStatus.OK

    status, _ = record(http, signed_in, block.id, {"state": "skipped"})
    assert status == HTTPStatus.OK

    answered = http.get(f"{HABITS_PREFIX}/{GYM}", headers=signed_in)
    assert answered.status_code == HTTPStatus.OK
    debt = answered.json()["debt"]
    assert (debt["misses"], debt["outstanding"]) == (1, 1)


@pytest.mark.integration
def test_confirming_a_day_sets_what_its_recorded_skips_charge(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    """A recorded-but-unconfirmed skip charges nothing until the day is settled."""
    first, _ = planned
    area_id = first.area_id
    assert area_id is not None
    seed_a_debt_habit(live_database_url, owner.tenant_id, GYM, area_id)
    status, _ = record(http, signed_in, first.id, {"state": "skipped"})
    assert status == HTTPStatus.OK

    before = http.get(f"{HABITS_PREFIX}/{GYM}", headers=signed_in).json()["debt"]
    assert (before["misses"], before["outstanding"]) == (0, 0)

    confirmed, _ = confirm(http, signed_in, YESTERDAY)
    assert confirmed == HTTPStatus.OK

    after = http.get(f"{HABITS_PREFIX}/{GYM}", headers=signed_in).json()["debt"]
    assert (after["misses"], after["outstanding"]) == (1, 1)


def test_a_backfill_over_a_range_the_zone_does_not_hold_settles_nothing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Reachable: Pacific/Apia skipped 30 December 2011, and a range naming only that date holds no
    # day at all. The range bounds pass, so the walk has to answer for an empty one rather than
    # reading the first of no days.
    answered = http.patch(SETTINGS_PREFIX, json={"homeZone": "Pacific/Apia"}, headers=signed_in)
    assert answered.status_code == HTTPStatus.OK, answered.text

    status, backfill = confirm_range(http, signed_in, date(2011, 12, 30), date(2011, 12, 30))

    assert status == HTTPStatus.OK, backfill
    assert backfill["confirmedDays"] == 0
    assert backfill["blocksRecorded"] == 0


def test_one_idempotency_key_replaying_a_confirmation_answers_the_stored_body(
    http: TestClient, signed_in: dict[str, str], planned: tuple[Block, Block]
) -> None:
    key = uuid4().hex

    once = confirm(http, signed_in, YESTERDAY, key=key)
    twice = confirm(http, signed_in, YESTERDAY, key=key)

    assert once == twice


def test_one_key_across_two_days_does_not_silently_skip_the_second(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # Confirming is bodyless and names its day in the path, so the day is carried by the request
    # hash alone: a claim is keyed by the tenant, the handler and the key. Two days under one key
    # are one key used for two different requests, which is a 422, and the second day stays
    # unconfirmed for the caller to settle under a key of its own.
    other_day = YESTERDAY - timedelta(days=1)
    key = uuid4().hex

    _, first_answer = confirm(http, signed_in, YESTERDAY, key=key)
    status, _ = confirm(http, signed_in, other_day, key=key)

    assert first_answer["date"] == YESTERDAY.isoformat()
    assert status == ValidationFailed.status
    assert read_day(http, signed_in, other_day)["confirmedAt"] is None


def test_one_key_across_two_blocks_with_one_body_does_not_silently_skip_the_second(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # The CONDITIONAL half of the same exposure, on the record route. The confirm route's
    # case does not stand proxy for it: a fix scoped to bodyless routes would close that one and
    # leave this open with nothing failing, and an evening pass marking two blocks of one day
    # `completed` sends two requests whose bodies are byte-identical.
    first, second = planned
    key = uuid4().hex

    record(http, signed_in, first.id, {"state": "completed"}, key=key)
    status, _ = record(http, signed_in, second.id, {"state": "completed"}, key=key)

    assert status == ValidationFailed.status
    stored = {row.block_id: row.state for row in outcome_rows(live_database_url, owner.tenant_id)}
    assert stored == {first.id: "completed"}


def test_a_day_that_has_not_begun_cannot_be_confirmed(
    http: TestClient, signed_in: dict[str, str], planned: tuple[Block, Block]
) -> None:
    status, refused = confirm(http, signed_in, YESTERDAY + timedelta(days=3))

    assert status == ValidationFailed.status
    assert "has not begun yet" in refused["detail"]


def test_a_backfill_settles_several_days_and_reports_how_many(
    http: TestClient, signed_in: dict[str, str], planned: tuple[Block, Block]
) -> None:
    status, backfill = confirm_range(http, signed_in, YESTERDAY - timedelta(days=2), YESTERDAY)

    assert status == HTTPStatus.OK, backfill
    assert backfill["confirmedDays"] == 1
    assert backfill["blocksRecorded"] == 2
    assert backfill["unconfirmedDays"] == 0


def test_a_backfill_reaching_into_the_future_is_refused(
    http: TestClient, signed_in: dict[str, str], planned: tuple[Block, Block]
) -> None:
    status, refused = confirm_range(http, signed_in, YESTERDAY, YESTERDAY + timedelta(days=2))

    assert status == ValidationFailed.status
    assert "has not begun yet" in refused["detail"]


def test_confirming_a_day_bumps_the_future_weeks_and_leaves_a_past_week_alone(
    http: TestClient,
    signed_in: dict[str, str],
    planned: tuple[Block, Block],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # A confirmation moves the rotation cursor and outstanding debt, which are inputs to weeks the
    # user has NOT yet lived. A solve already running for such a week has to fail its conditional
    # write, and the version row is the only signal that makes it do so.
    #
    # A past week is deliberately left alone: its approved revision is immutable and keeps the
    # inputs it was computed with, so re-deriving it would change history rather than the plan.
    behind = WEEK.preceding().preceding()
    ahead = WEEK.following()
    seed_versions(live_database_url, owner.tenant_id, [behind, WEEK, ahead])

    confirm(http, signed_in, YESTERDAY)

    assert versions_of(live_database_url, owner.tenant_id) == {
        str(behind): 1,
        str(WEEK): 2,
        str(ahead): 2,
    }


def test_correcting_a_past_confirmation_re_derives_the_rotation_cursor(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # Correcting a past confirmation re-derives what the log projects, through HTTP, and it is the
    # whole reason the binding is denormalized onto an outcome. The cursor is derived from the log
    # on every read, so correcting a confirmation moves it with no further call: there is no stored
    # projection for the correction to disagree with.
    area_id = declare_area(http, signed_in)
    declared = http.post(
        HABITS_PREFIX,
        json={
            "title": "Gym",
            "areaId": str(area_id),
            "cadence": {"kind": "times_per_week", "timesPerWeek": 3},
            "minDurationMinutes": 60,
            "bindingSource": "rotation",
            "variants": ["Push", "Pull", "Legs"],
            "missPolicy": "forgive",
        },
        headers=signed_in,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text
    habit_id = declared.json()["id"]
    block = Block(
        iso_week=WEEK,
        interval=Interval(an_instant(YESTERDAY, 9), an_instant(YESTERDAY, 10)),
        binding=BindingRef.for_habit(UUID(habit_id), index=0),
        title="Gym · Push",
        reason=A_REASON,
        area_id=area_id,
    )
    seed_plan(live_database_url, owner.tenant_id, a_week([block]))

    def cursor() -> dict[str, Any]:
        answered = http.get(f"{HABITS_PREFIX}/{habit_id}", headers=signed_in)
        assert answered.status_code == HTTPStatus.OK, answered.text
        read: dict[str, Any] = answered.json()["cursor"]
        return read

    before = cursor()
    confirm(http, signed_in, YESTERDAY)
    after_confirming = cursor()
    record(http, signed_in, block.id, {"state": "skipped"})
    after_correcting = cursor()

    # A confirmed presumption is a completion, so the cursor advances to the next variant.
    assert before["variant"] == "Push"
    assert after_confirming["variant"] == "Pull"
    # Correcting it to a skip removes the completion entirely, and the cursor is back where it was.
    assert after_correcting["variant"] == "Push"


def test_one_habits_outcomes_are_not_counted_toward_another(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The read is keyed on the entity the binding names, and a filter that matched too widely would
    # advance every rotation habit whenever any one of them was confirmed.
    area_id = declare_area(http, signed_in)
    habits = []
    for title in ("Gym", "Leetcode"):
        declared = http.post(
            HABITS_PREFIX,
            json={
                "title": title,
                "areaId": str(area_id),
                "cadence": {"kind": "times_per_week", "timesPerWeek": 3},
                "minDurationMinutes": 60,
                "bindingSource": "rotation",
                "variants": ["One", "Two", "Three"],
                "missPolicy": "forgive",
            },
            headers=signed_in,
        )
        assert declared.status_code == HTTPStatus.CREATED, declared.text
        habits.append(declared.json()["id"])
    confirmed, untouched = habits
    block = Block(
        iso_week=WEEK,
        interval=Interval(an_instant(YESTERDAY, 9), an_instant(YESTERDAY, 10)),
        binding=BindingRef.for_habit(UUID(confirmed), index=0),
        title="Gym · One",
        reason=A_REASON,
        area_id=area_id,
    )
    seed_plan(live_database_url, owner.tenant_id, a_week([block]))

    confirm(http, signed_in, YESTERDAY)

    def variant(habit_id: str) -> str:
        answered = http.get(f"{HABITS_PREFIX}/{habit_id}", headers=signed_in)
        assert answered.status_code == HTTPStatus.OK, answered.text
        read: str = answered.json()["cursor"]["variant"]
        return read

    assert variant(confirmed) == "Two"
    assert variant(untouched) == "One"
