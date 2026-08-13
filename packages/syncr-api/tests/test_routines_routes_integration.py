"""The five routine routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a real
database can: that a wall time survives a ``time without time zone`` column unchanged, that a
refused span is not stored, that the response carries no Area field, that the sleep floor has
exactly one home across two feature modules, that every mutation increments the input
version row a running solve is guarding against, and that a retried unsafe request sent under one
key is applied once.

Two tests are worth reading. ``test_the_stored_frame_resolves_to_the_span_the_dst_fixture_records``
takes the row back out of Postgres and resolves it against a real transition date, which is the
only place the round trip and the zone arithmetic are asserted together. And
``test_the_sleep_floor_is_set_on_the_routine_and_settings_refuses_it`` asserts both halves of the
one-home rule: the routine's ``PATCH`` takes effect, and the settings ``PATCH`` refuses the field
rather than dropping it.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import time, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.routines.config import ROUTINES_PREFIX
from syncr_api.routines.models import RoutineRow
from syncr_api.routines.records import RoutineRecord
from syncr_api.user_settings.config import SETTINGS_PREFIX
from syncr_domain.fixtures.dst_weeks import DST_WEEKS
from syncr_domain.routines import MAX_DURATION_MINUTES, MAX_FLEX_BAND_MINUTES, RoutineSpan
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
ROUTINES = ROUTINES_PREFIX
SETTINGS = SETTINGS_PREFIX

SLEEP = {"title": "Sleep", "targetTime": "23:00", "durationMinutes": 480}

# A week nothing has lived yet, and one already behind. A bump reaches the first and must not
# reach the second: an approved revision keeps the inputs it was computed with.
_TODAY = utc_now().date()
FUTURE_WEEK = IsoWeek.containing(_TODAY + timedelta(days=60))
PAST_WEEK = IsoWeek.containing(_TODAY - timedelta(days=60))


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


def _sign_in(http: TestClient, email: str) -> dict[str, str]:
    response = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    return {
        "Cookie": f"{SESSION_COOKIE_NAME}={response.cookies[SESSION_COOKIE_NAME]}",
        "Origin": BROWSER_ORIGIN,
    }


def routine_rows(database_url: str, tenant_id: TenantId) -> list[RoutineRow]:
    """The tenant's routine rows, read on a connection of this test's own."""

    async def read() -> list[RoutineRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(RoutineRow)
                    .where(RoutineRow.tenant_id == tenant_id)
                    .order_by(RoutineRow.target_time, RoutineRow.id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def track(database_url: str, tenant_id: TenantId, *weeks: IsoWeek) -> None:
    """Give each week an input-version row, so a bump has something to increment."""

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                versions = WeekInputVersionRepository(session, tenant_id)
                for week in weeks:
                    await versions.bump(week, at=utc_now())
        finally:
            await database.engine.dispose()

    run(seed())


def input_version(database_url: str, tenant_id: TenantId, week: IsoWeek) -> int | None:
    async def read() -> int | None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await WeekInputVersionRepository(session, tenant_id).current(week)
        finally:
            await database.engine.dispose()

    return run(read())


def declare_routine(http: TestClient, headers: dict[str, str], **body: object) -> dict[str, Any]:
    """The routine a successful declaration answers with, as the JSON a client receives."""
    response = http.post(ROUTINES, json={**SLEEP, **body}, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    payload: dict[str, Any] = response.json()
    return payload


# --------------------------------------------------------------------------------
# The shape, and the Area it does not have
# --------------------------------------------------------------------------------


def test_the_routines_route_needs_a_credential(http: TestClient) -> None:
    response = http.get(ROUTINES)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_declaring_a_routine_commits_it_and_carries_no_area(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = declare_routine(http, signed_in)

    # The whole shape, asserted as a set: no Area, no pigment, and nothing a later column could
    # add by sharing a name with a schema field.
    assert sorted(created) == [
        "durationMinutes",
        "flexBandMinutes",
        "id",
        "minDurationMinutes",
        "targetTime",
        "title",
    ]
    assert created["targetTime"] == "23:00:00"
    assert created["durationMinutes"] == 480
    assert created["flexBandMinutes"] == 0

    rows = routine_rows(live_database_url, owner.tenant_id)
    assert [(row.title, row.target_time, row.duration_minutes) for row in rows] == [
        ("Sleep", time(23, 0), 480)
    ]
    assert http.get(ROUTINES, headers=signed_in).json()["routines"] == [created]


@pytest.mark.parametrize("body", [{"areaId": str(uuid4())}, {"pigmentIndex": 3}])
def test_no_request_shape_accepts_an_area_or_a_pigment(
    http: TestClient, signed_in: dict[str, str], body: dict[str, object]
) -> None:
    # A routine defines how much time exists rather than competing for it, so the field that
    # would give it a wedge of the pie is refused rather than ignored.
    created = declare_routine(http, signed_in)

    declared = http.post(ROUTINES, json={**SLEEP, **body}, headers=signed_in)
    patched = http.patch(f"{ROUTINES}/{created['id']}", json=body, headers=signed_in)

    assert declared.status_code == ValidationFailed.status, declared.text
    assert patched.status_code == ValidationFailed.status, patched.text


def test_the_frame_is_listed_in_the_order_the_day_runs(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    declare_routine(http, signed_in)
    declare_routine(http, signed_in, title="Wake", targetTime="05:00", durationMinutes=30)
    declare_routine(http, signed_in, title="Lunch", targetTime="12:30", durationMinutes=45)

    listed = http.get(ROUTINES, headers=signed_in).json()["routines"]

    assert [row["title"] for row in listed] == ["Wake", "Lunch", "Sleep"]


def test_the_stored_frame_resolves_to_the_span_the_dst_fixture_records(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The round trip and the zone arithmetic, asserted together. A `time without time zone`
    # column that shifted the wall time by an offset, or a duration read as wall-clock
    # arithmetic, would both produce a plausible interval on an ordinary week and the wrong one
    # here.
    declare_routine(http, signed_in)
    row = routine_rows(live_database_url, owner.tenant_id)[0]

    for week in DST_WEEKS:
        stored = _as_record_span(row)
        assert stored.occurrence_on(week.transition_date, week.zone) == week.sunday_night_frame
        assert stored.occurrence_on(week.transition_date, week.zone).total_minutes() == 480


def _as_record_span(row: RoutineRow) -> RoutineSpan:
    """The domain span the stored row carries, built the way the repository's record does."""
    return RoutineRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        title=row.title,
        target_time=row.target_time,
        duration_minutes=row.duration_minutes,
        min_duration_minutes=row.min_duration_minutes,
        flex_band_minutes=row.flex_band_minutes,
        created_at=row.created_at,
    ).as_span()


# --------------------------------------------------------------------------------
# A routine is a span, and a wall time is a wall time
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"title": "Sleep", "targetTime": "23:00"},
        {"title": "Sleep", "targetTime": "23:00", "durationMinutes": 0},
        {"title": "Sleep", "targetTime": "23:00", "durationMinutes": -30},
        {"title": "Sleep", "targetTime": "23:00", "durationMinutes": MAX_DURATION_MINUTES + 1},
    ],
    ids=["no duration at all", "a duration of nothing", "a negative duration", "longer than a day"],
)
def test_a_routine_without_a_usable_duration_is_refused_and_not_stored(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    body: dict[str, object],
) -> None:
    response = http.post(ROUTINES, json=body, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    assert [error["field"] for error in response.json()["errors"]] == ["body.durationMinutes"]
    assert routine_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize(
    "target_time",
    ["23:00:00+01:00", "23:00:00Z", "23:00:30", "23:00:00.500000"],
    ids=["an offset", "a UTC marker", "a second", "a microsecond"],
)
def test_a_target_time_that_is_not_wall_time_is_refused(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    target_time: str,
) -> None:
    # A wall time names no zone and no second. An offset would be dropped by the column and the
    # frame would sit in the wrong hour with nothing to say so.
    response = http.post(ROUTINES, json={**SLEEP, "targetTime": target_time}, headers=signed_in)
    assert response.status_code == ValidationFailed.status, response.text
    assert [error["field"] for error in response.json()["errors"]] == ["body.targetTime"]
    assert routine_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize(
    "target_time",
    ["23:00:00+01:00", "23:00:00Z", "23:00:30", "23:00:00.500000"],
    ids=["an offset", "a UTC marker", "a second", "a microsecond"],
)
def test_a_patch_refuses_a_target_time_that_is_not_wall_time_either(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    target_time: str,
) -> None:
    # The rule reaches the patch through `WallTime | None`, which is exactly the seam where a
    # validator stops applying under a later refactor. Driven over both verbs so nothing but the
    # create path is standing between a refactor and a silently dropped offset.
    created = declare_routine(http, signed_in)

    response = http.patch(
        f"{ROUTINES}/{created['id']}", json={"targetTime": target_time}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status, response.text
    assert [error["field"] for error in response.json()["errors"]] == ["body.targetTime"]
    stored = routine_rows(live_database_url, owner.tenant_id)
    assert [row.target_time for row in stored] == [time(23, 0)]


@pytest.mark.parametrize(
    "target_time",
    ["00:00", "05:00", "23:59", "01:30"],
    ids=["midnight", "wake", "late", "in a gap"],
)
def test_a_wall_time_on_any_minute_of_the_day_is_accepted(
    http: TestClient, signed_in: dict[str, str], target_time: str
) -> None:
    # The control for the rejections above: they must distinguish rather than refuse a time.
    # 01:30 is the one that does not exist on a spring-forward date, and it is accepted here
    # because the frame shifts it forward on that day rather than refusing to be authored.
    created = declare_routine(http, signed_in, targetTime=target_time, durationMinutes=30)

    assert created["targetTime"].startswith(target_time)


def test_a_floor_above_its_target_is_refused_and_nothing_is_stored(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    response = http.post(ROUTINES, json={**SLEEP, "minDurationMinutes": 600}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    problem = response.json()
    assert [error["field"] for error in problem["errors"]] == ["minDurationMinutes"]
    assert "Nothing was changed" in problem["detail"]
    assert routine_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize(
    "body",
    [
        {"durationMinutes": MAX_DURATION_MINUTES, "minDurationMinutes": MAX_DURATION_MINUTES},
        {"durationMinutes": 1, "minDurationMinutes": 1},
        {"flexBandMinutes": MAX_FLEX_BAND_MINUTES},
        {"flexBandMinutes": 0},
    ],
    ids=["a whole day", "a single minute", "the widest band", "no band"],
)
def test_a_value_at_the_edge_of_its_bounds_is_accepted(
    http: TestClient, signed_in: dict[str, str], body: dict[str, object]
) -> None:
    response = http.post(ROUTINES, json={**SLEEP, **body}, headers=signed_in)

    assert response.status_code == HTTPStatus.CREATED, response.text


@pytest.mark.parametrize(
    "body",
    [{"flexBandMinutes": MAX_FLEX_BAND_MINUTES + 1}, {"flexBandMinutes": -1}, {"title": ""}],
    ids=["a band past half a day", "a negative band", "an empty title"],
)
def test_a_value_outside_its_bounds_is_refused(
    http: TestClient, signed_in: dict[str, str], body: dict[str, object]
) -> None:
    response = http.post(ROUTINES, json={**SLEEP, **body}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


# --------------------------------------------------------------------------------
# The sleep floor's one home
# --------------------------------------------------------------------------------


def test_the_sleep_floor_is_set_on_the_routine_and_settings_refuses_it(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = declare_routine(http, signed_in)
    # Inelastic on arrival: nothing offers to compress a routine the user has not given give.
    assert created["minDurationMinutes"] == created["durationMinutes"]

    patched = http.patch(
        f"{ROUTINES}/{created['id']}", json={"minDurationMinutes": 360}, headers=signed_in
    )

    assert patched.status_code == HTTPStatus.OK, patched.text
    assert patched.json()["minDurationMinutes"] == 360
    stored = routine_rows(live_database_url, owner.tenant_id)
    assert [row.min_duration_minutes for row in stored] == [360]

    # The other half of the rule: there is no second home for the value. Settings forbids the
    # unknown field, so an attempt to set it there is stated rather than silently dropped.
    for field in ("sleepFloorMinutes", "minDurationMinutes", "sleepFloor"):
        refused = http.patch(SETTINGS, json={field: 360}, headers=signed_in)
        assert refused.status_code == ValidationFailed.status, refused.text

    reading = http.get(SETTINGS, headers=signed_in).json()
    assert [key for key in reading if "floor" in key.lower() or "sleep" in key.lower()] == []


def test_a_routine_whose_floor_equals_its_target_offers_no_reduction(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The predicate a tradeoff enumerator will read, asserted on the stored row: `reduce_routine`
    # is offered only where the floor is strictly below the target, and the default equality is
    # what keeps `Lunch` out of every tradeoff list.
    declare_routine(http, signed_in, title="Lunch", targetTime="12:30", durationMinutes=45)
    declare_routine(http, signed_in, minDurationMinutes=360)

    stored = {
        row.title: _as_record_span(row).is_elastic
        for row in routine_rows(live_database_url, owner.tenant_id)
    }

    assert stored == {"Lunch": False, "Sleep": True}


# --------------------------------------------------------------------------------
# Patching, removing, and what a mutation invalidates
# --------------------------------------------------------------------------------


def test_a_patch_changes_only_what_it_names(http: TestClient, signed_in: dict[str, str]) -> None:
    created = declare_routine(http, signed_in, flexBandMinutes=30)

    patched = http.patch(
        f"{ROUTINES}/{created['id']}", json={"targetTime": "22:30"}, headers=signed_in
    )

    assert patched.status_code == HTTPStatus.OK, patched.text
    body = patched.json()
    assert body["targetTime"] == "22:30:00"
    assert body["durationMinutes"] == 480
    assert body["flexBandMinutes"] == 30
    assert body["title"] == "Sleep"


@pytest.mark.parametrize(
    "field",
    ["title", "targetTime", "durationMinutes", "minDurationMinutes", "flexBandMinutes"],
)
def test_a_null_is_refused_rather_than_read_as_no_change(
    http: TestClient, signed_in: dict[str, str], field: str
) -> None:
    # Nothing on a routine is nullable, so there is nothing for an explicit null to clear.
    created = declare_routine(http, signed_in)

    response = http.patch(f"{ROUTINES}/{created['id']}", json={field: None}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    assert "null is refused" in response.text


def test_removing_a_routine_answers_204_and_deletes_the_row(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    created = declare_routine(http, signed_in)

    removed = http.delete(f"{ROUTINES}/{created['id']}", headers=signed_in)

    assert removed.status_code == HTTPStatus.NO_CONTENT
    assert removed.content == b""
    assert routine_rows(live_database_url, owner.tenant_id) == []
    assert http.get(f"{ROUTINES}/{created['id']}", headers=signed_in).status_code == (
        NotFound.status
    )


def test_every_mutation_bumps_the_tracked_week_and_leaves_a_past_one_alone(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # Changing the frame changes the denominator, so a running solve has to be superseded. Three
    # mutations, three increments, read from the row a solve's conditional write guards on.
    track(live_database_url, owner.tenant_id, FUTURE_WEEK, PAST_WEEK)
    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == 1

    created = declare_routine(http, signed_in)
    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == 2

    renamed = http.patch(
        f"{ROUTINES}/{created['id']}", json={"title": "Sleep, properly"}, headers=signed_in
    )
    assert renamed.status_code == HTTPStatus.OK, renamed.text
    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == 3

    assert http.delete(f"{ROUTINES}/{created['id']}", headers=signed_in).status_code == (
        HTTPStatus.NO_CONTENT
    )
    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == 4

    # An approved revision is immutable and keeps the inputs it was computed with, so a past
    # week is not re-derived by a frame change.
    assert input_version(live_database_url, owner.tenant_id, PAST_WEEK) == 1


def test_a_refused_mutation_bumps_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The control for the bumps above: invalidating a week for a request that changed nothing
    # would discard a running solve for free.
    created = declare_routine(http, signed_in)
    track(live_database_url, owner.tenant_id, FUTURE_WEEK)
    before = input_version(live_database_url, owner.tenant_id, FUTURE_WEEK)

    refused = http.patch(
        f"{ROUTINES}/{created['id']}", json={"minDurationMinutes": 600}, headers=signed_in
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == before


# --------------------------------------------------------------------------------
# Idempotency, on all three unsafe methods
# --------------------------------------------------------------------------------


def test_a_retried_declaration_replays_rather_than_declaring_a_second_routine(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # Nothing about a routine is unique, and the table says so on purpose: two routines may share
    # a title. So a repeat is a second row rather than a refusal, and the frame carries the same
    # span twice with nothing downstream able to tell the copy from a deliberate second span.
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: str(uuid4())}

    first = http.post(ROUTINES, json=SLEEP, headers=keyed)
    second = http.post(ROUTINES, json=SLEEP, headers=keyed)

    # The row set first: the second write is the defect and the response is only its symptom.
    assert [row.title for row in routine_rows(live_database_url, owner.tenant_id)] == ["Sleep"]
    assert first.status_code == HTTPStatus.CREATED, first.text
    assert second.status_code == HTTPStatus.CREATED, second.text
    assert second.json() == first.json()


def test_a_repeated_declaration_without_a_key_still_declares_a_second_routine(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The control on the offered-not-demanded rule. The header buys the guarantee and its absence
    # leaves the route as it was, so this is what says the tests around it assert a guarantee a
    # caller opted into rather than a constraint the route now enforces for everyone.
    declare_routine(http, signed_in)
    declare_routine(http, signed_in)

    assert len(routine_rows(live_database_url, owner.tenant_id)) == 2


def test_a_retried_patch_replays_rather_than_bumping_the_week_again(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # A rename converges: sent twice it leaves the same row either way, so an assertion on the
    # response alone could not tell a replay from a second execution and would be decoration.
    # What separates them is the week input version, which every frame mutation bumps and which
    # is the figure a running solve's conditional write compares.
    created = declare_routine(http, signed_in)
    track(live_database_url, owner.tenant_id, FUTURE_WEEK)
    before = input_version(live_database_url, owner.tenant_id, FUTURE_WEEK)
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: str(uuid4())}
    renamed = {"title": "Sleep, properly"}

    first = http.patch(f"{ROUTINES}/{created['id']}", json=renamed, headers=keyed)
    second = http.patch(f"{ROUTINES}/{created['id']}", json=renamed, headers=keyed)

    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == before + 1
    assert first.status_code == HTTPStatus.OK, first.text
    assert second.status_code == HTTPStatus.OK, second.text
    assert second.json() == first.json()


def test_a_retried_removal_replays_the_stored_answer_rather_than_404ing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The row is gone once the first removal commits, so re-running the work answers 404: a client
    # that resends a request it never saw the answer to is told the routine it just removed does
    # not exist. The replay answers the stored 204 instead, and carries no body.
    created = declare_routine(http, signed_in)
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: str(uuid4())}

    first = http.delete(f"{ROUTINES}/{created['id']}", headers=keyed)
    second = http.delete(f"{ROUTINES}/{created['id']}", headers=keyed)

    assert second.status_code == HTTPStatus.NO_CONTENT, second.text
    assert second.content == b""
    assert first.status_code == HTTPStatus.NO_CONTENT, first.text
    assert routine_rows(live_database_url, owner.tenant_id) == []


def test_a_repeated_removal_without_a_key_still_answers_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The control for the replay above, and the reading that says the 404 is the route's real
    # behavior rather than something the test constructed.
    created = declare_routine(http, signed_in)

    first = http.delete(f"{ROUTINES}/{created['id']}", headers=signed_in)
    second = http.delete(f"{ROUTINES}/{created['id']}", headers=signed_in)

    assert first.status_code == HTTPStatus.NO_CONTENT
    assert second.status_code == NotFound.status, second.text


# --------------------------------------------------------------------------------
# Tenancy and the origin check
# --------------------------------------------------------------------------------


def test_reading_a_routine_that_does_not_exist_is_a_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(f"{ROUTINES}/{uuid4()}", headers=signed_in)

    assert response.status_code == NotFound.status
    assert response.json()["type"] == NotFound.type


def test_another_tenants_routine_is_a_404_rather_than_an_edit(
    http: TestClient, signed_in: dict[str, str], live_database_url: str
) -> None:
    stranger = provision_owner(live_database_url)
    try:
        theirs = declare_routine(http, _sign_in(http, stranger.email), title="Their sleep")

        read = http.get(f"{ROUTINES}/{theirs['id']}", headers=signed_in)
        patched = http.patch(
            f"{ROUTINES}/{theirs['id']}", json={"durationMinutes": 60}, headers=signed_in
        )
        removed = http.delete(f"{ROUTINES}/{theirs['id']}", headers=signed_in)

        assert [read.status_code, patched.status_code, removed.status_code] == (
            [NotFound.status] * 3
        )
        # And the row is untouched: a 404 that deleted it would be worse than a 403.
        rows = routine_rows(live_database_url, stranger.tenant_id)
        assert [(row.title, row.duration_minutes) for row in rows] == [("Their sleep", 480)]
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


@pytest.mark.parametrize("method", ["post", "patch", "delete"])
def test_an_unsafe_request_from_an_unserved_origin_is_refused(
    http: TestClient, signed_in: dict[str, str], method: str
) -> None:
    created = declare_routine(http, signed_in)
    forged = {**signed_in, "Origin": "https://evil.example"}
    target = ROUTINES if method == "post" else f"{ROUTINES}/{created['id']}"

    response = getattr(http, method)(target, headers=forged)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["type"] == "syncr:origin-rejected"
