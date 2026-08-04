"""The nine preference routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a real
database can: that a wall time survives a JSONB round trip unchanged, that a refused declaration is
not stored, that a daily cap is not a field an override's request shape has, that removing an
override really restores its Area's preference, and that every mutation increments the input-version
row a running solve is guarding against.

Three tests are worth reading.

``test_a_cap_on_an_override_is_refused_at_the_boundary`` is X13 over both other owners. It is a
boundary refusal rather than a service refusal: the request shape has no field for a cap, so the
framework rejects the body before a handler runs, and the response names the field.

``test_the_stored_window_is_the_wall_time_that_was_sent`` reads the JSONB back out of Postgres. A
``TIME WITHOUT TIME ZONE`` column drops an offset in silence, and this is the assertion that the
strings stored here carry no offset to drop because the boundary refused one.

``test_removing_an_override_restores_its_areas_preference`` is the criterion on the wire: the
response states which preference is in effect and where it came from, before and after.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.preferences.models import PreferenceRow
from syncr_api.tasks.config import TASKS_PREFIX
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

EARLY = {"start": "05:30", "end": "07:00"}
MIDDAY = {"start": "13:15", "end": "14:15"}
EVENING = {"start": "19:00", "end": "21:00"}

GYM_WINDOWS = {"windows": [EARLY, MIDDAY], "strength": "strong"}

# A week nothing has lived yet, and one already behind. A bump reaches the first and must not reach
# the second: an approved revision keeps the inputs it was computed with.
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


class Owned:
    """One Area with a habit and a task inside it, declared through the product's own routes."""

    def __init__(self, http: TestClient, headers: dict[str, str]) -> None:
        area = http.post(
            AREAS_PREFIX,
            json={"name": f"Fitness {uuid4().hex[:8]}"},
            headers=headers,
        )
        assert area.status_code == HTTPStatus.CREATED, area.text
        self.area_id: str = area.json()["area"]["id"]

        habit = http.post(
            HABITS_PREFIX,
            json={
                "areaId": self.area_id,
                "title": "Anki",
                "cadence": {"kind": "daily"},
                "minDurationMinutes": 15,
            },
            headers=headers,
        )
        assert habit.status_code == HTTPStatus.CREATED, habit.text
        self.habit_id: str = habit.json()["id"]

        task = http.post(
            TASKS_PREFIX,
            json={"areaId": self.area_id, "title": "Essay"},
            headers=headers,
        )
        assert task.status_code == HTTPStatus.CREATED, task.text
        self.task_id: str = task.json()["id"]

    @property
    def area(self) -> str:
        return f"{AREAS_PREFIX}/{self.area_id}/preference"

    @property
    def habit(self) -> str:
        return f"{HABITS_PREFIX}/{self.habit_id}/preference"

    @property
    def task(self) -> str:
        return f"{TASKS_PREFIX}/{self.task_id}/preference"

    def path(self, kind: str) -> str:
        return {"area": self.area, "habit": self.habit, "task": self.task}[kind]

    def owner_id(self, kind: str) -> str:
        return {"area": self.area_id, "habit": self.habit_id, "task": self.task_id}[kind]


@pytest.fixture
def owned(http: TestClient, signed_in: dict[str, str]) -> Owned:
    return Owned(http, signed_in)


def preference_rows(database_url: str, tenant_id: TenantId) -> list[PreferenceRow]:
    """The tenant's preference rows, read on a connection of this test's own."""

    async def read() -> list[PreferenceRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(PreferenceRow)
                    .where(PreferenceRow.tenant_id == tenant_id)
                    .order_by(PreferenceRow.created_at, PreferenceRow.id)
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


def store_a_window_no_reader_will_accept(database_url: str, tenant_id: TenantId) -> None:
    """Write an offset into every stored window, around the application.

    The only way into this state: the request validator refuses an offset and so does the entity, so
    nothing the product does can produce it. A JSONB string keeps the offset verbatim rather than
    dropping it the way a column with no offset would, which is why the read path refuses it too.
    """

    async def corrupt() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await session.execute(
                    text(
                        "UPDATE preferences SET windows = CAST(:windows AS jsonb) "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {
                        "windows": '[{"start": "05:30:00+01:00", "end": "07:00:00"}]',
                        "tenant_id": tenant_id,
                    },
                )
        finally:
            await database.engine.dispose()

    run(corrupt())


def put(http: TestClient, headers: dict[str, str], path: str, **body: object) -> dict[str, Any]:
    """The preference a successful replacement answers with, as the JSON a client receives."""
    response = http.put(path, json=body, headers=headers)
    assert response.status_code == HTTPStatus.OK, response.text
    payload: dict[str, Any] = response.json()
    return payload


# --------------------------------------------------------------------------------
# The shape, and the read model's two halves
# --------------------------------------------------------------------------------


def test_an_area_declares_its_windows_and_reads_them_back(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    body = put(http, signed_in, owned.area, **GYM_WINDOWS, maxPerDayMinutes=180)

    assert body["owner"] == {"kind": "area", "id": owned.area_id}
    assert body["declared"] == {
        "windows": [
            {"start": "05:30:00", "end": "07:00:00"},
            {"start": "13:15:00", "end": "14:15:00"},
        ],
        "strength": "strong",
        "preferredDurationMinutes": None,
        "maxPerDayMinutes": 180,
    }
    assert http.get(owned.area, headers=signed_in).json() == body


def test_an_areas_own_preference_is_what_is_in_effect_for_it(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    body = put(http, signed_in, owned.area, **GYM_WINDOWS)

    assert body["effective"]["source"] == {"kind": "area", "id": owned.area_id}
    assert body["effective"]["statement"] == "Set on this area: 05:30-07:00 or 13:15-14:15, strong."


def test_the_effective_preference_carries_no_daily_cap_even_on_an_area(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    # The cap reaches the solver through the Area's budget rather than through the preference
    # resolved down an override chain, which is what makes an override unable to relax it.
    body = put(http, signed_in, owned.area, **GYM_WINDOWS, maxPerDayMinutes=180)

    assert "maxPerDayMinutes" not in body["effective"]
    assert body["declared"]["maxPerDayMinutes"] == 180


@pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
def test_an_owner_with_no_override_inherits_its_areas_preference(
    http: TestClient, signed_in: dict[str, str], owned: Owned, kind: str
) -> None:
    put(http, signed_in, owned.area, **GYM_WINDOWS)

    read = http.get(owned.path(kind), headers=signed_in)

    assert read.status_code == HTTPStatus.OK, read.text
    body = read.json()
    assert body["declared"] is None
    assert body["effective"]["source"] == {"kind": "area", "id": owned.area_id}
    assert body["effective"]["statement"].startswith("Inherited from its Area:")


@pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
def test_an_override_replaces_its_areas_preference(
    http: TestClient, signed_in: dict[str, str], owned: Owned, kind: str
) -> None:
    put(http, signed_in, owned.area, **GYM_WINDOWS, preferredDurationMinutes=90)

    body = put(http, signed_in, owned.path(kind), windows=[EVENING], strength="soft")

    assert body["effective"]["source"] == {"kind": kind, "id": owned.owner_id(kind)}
    assert body["effective"]["windows"] == [{"start": "19:00:00", "end": "21:00:00"}]
    assert body["effective"]["strength"] == "soft"
    # Replaced wholly rather than merged: the Area's 90 does not fill the override's null.
    assert body["effective"]["preferredDurationMinutes"] is None
    assert body["effective"]["statement"] == f"Set on this {kind}: 19:00-21:00, soft."


def test_an_override_with_no_windows_opts_out_of_its_areas(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    put(http, signed_in, owned.area, **GYM_WINDOWS)

    body = put(http, signed_in, owned.habit, windows=[], strength="soft")

    assert body["declared"]["windows"] == []
    assert body["effective"]["windows"] == []
    assert body["effective"]["statement"] == "Set on this habit: no preferred time."


def test_an_owner_whose_area_declares_nothing_reads_nothing_in_effect(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    read = http.get(owned.habit, headers=signed_in)

    assert read.status_code == HTTPStatus.OK, read.text
    assert read.json() == {
        "owner": {"kind": "habit", "id": owned.habit_id},
        "declared": None,
        "effective": None,
    }


def test_windows_come_back_earliest_first_whatever_order_they_were_sent(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    body = put(http, signed_in, owned.area, windows=[EVENING, EARLY, MIDDAY], strength="soft")

    assert [window["start"] for window in body["declared"]["windows"]] == [
        "05:30:00",
        "13:15:00",
        "19:00:00",
    ]


def test_the_areas_default_preference_id_stays_null_after_a_preference_is_set(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    # The Area response's own field says "always null, nothing writes this column", and this is what
    # keeps that claim true. A preference names its own owner, so the relation lives on the
    # preference and a second home for it on the Area would be a value that can disagree.
    put(http, signed_in, owned.area, **GYM_WINDOWS)

    area = http.get(f"{AREAS_PREFIX}/{owned.area_id}", headers=signed_in)

    assert area.status_code == HTTPStatus.OK, area.text
    assert area.json()["defaultPreferenceId"] is None


# --------------------------------------------------------------------------------
# X13: a daily cap is an Area's alone
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
def test_a_cap_on_an_override_is_refused_at_the_boundary(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    kind: str,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # X13. The request shape has no field for a cap, so this is refused before a handler runs and
    # there is no code path that could store one.
    refused = http.put(
        owned.path(kind),
        json={"windows": [MIDDAY], "strength": "soft", "maxPerDayMinutes": 180},
        headers=signed_in,
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert "maxPerDayMinutes" in refused.text
    assert preference_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
def test_a_cap_is_absent_from_an_overrides_request_shape_in_the_document(
    http: TestClient, kind: str
) -> None:
    # The structural half of the refusal above, read out of the contract the client generates from.
    document = http.get("/openapi.json").json()
    prefix = {"habit": "habits/{habit_id}", "task": "tasks/{task_id}"}[kind]
    body = document["paths"][f"/api/v1/{prefix}/preference"]["put"]["requestBody"]
    named = body["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]

    assert named == "OverridePreferenceRequest"
    assert "maxPerDayMinutes" not in document["components"]["schemas"][named]["properties"]


def test_an_area_may_declare_a_cap_and_an_area_alone(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    # The control for the two refusals above: without it, a shape that refused every cap would pass.
    body = put(http, signed_in, owned.area, windows=[MIDDAY], strength="soft", maxPerDayMinutes=180)

    assert body["declared"]["maxPerDayMinutes"] == 180


# --------------------------------------------------------------------------------
# P1: a strength is never hard
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["area", "habit", "task"], ids=["area", "habit", "task"])
def test_a_hard_strength_is_refused_on_every_owner(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    kind: str,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # A hard temporal rule with a conditional escape is not a hard rule, so there is no value to
    # send. The enum has two members and the framework refuses the third.
    refused = http.put(
        owned.path(kind), json={"windows": [MIDDAY], "strength": "hard"}, headers=signed_in
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert preference_rows(live_database_url, owner.tenant_id) == []


def test_the_document_advertises_two_strengths_and_no_more(http: TestClient) -> None:
    document = http.get("/openapi.json").json()

    assert document["components"]["schemas"]["PreferenceStrength"]["enum"] == ["strong", "soft"]


# --------------------------------------------------------------------------------
# A window is wall time on the grid
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "start", "field"),
    [
        ("an offset", "05:30:00+01:00", "body.windows.0.start"),
        ("seconds", "05:30:30", "body.windows.0.start"),
        ("off the quarter hour", "05:07", "windows"),
    ],
    ids=["offset", "seconds", "off-grid"],
)
def test_a_window_bound_that_is_not_wall_time_on_the_grid_is_refused(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    case: str,
    start: str,
    field: str,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # The offset case is the one that would otherwise be silent: pydantic parses an offset into an
    # aware time, and a JSONB string carries it verbatim rather than refusing it.
    #
    # The FIELD each refusal names is asserted, not just the status, and that is what earns the
    # boundary validator its place beside the entity's. The first two are refused where the request
    # is read, so they point at the exact bound in a list of up to six; the quarter-hour rule is
    # stated once in the domain, which sees the window rather than the request, so it names the
    # list. Without this assertion the boundary validator could be deleted and nothing would fail.
    refused = http.put(
        owned.area,
        json={"windows": [{"start": start, "end": "08:00"}], "strength": "soft"},
        headers=signed_in,
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert [error["field"] for error in refused.json()["errors"]] == [field]
    assert preference_rows(live_database_url, owner.tenant_id) == []


def test_a_window_that_does_not_run_forward_is_refused(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    refused = http.put(
        owned.area,
        json={"windows": [{"start": "23:00", "end": "01:00"}], "strength": "soft"},
        headers=signed_in,
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    # The FIELD rather than a substring of the whole body, so a different refusal that happened to
    # contain the word cannot pass for this one.
    assert [error["field"] for error in refused.json()["errors"]] == ["windows"]
    assert "two stretches" in refused.json()["detail"]


def test_two_overlapping_windows_are_refused(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    refused = http.put(
        owned.area,
        json={"windows": [EARLY, {"start": "06:00", "end": "08:00"}], "strength": "soft"},
        headers=signed_in,
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert [error["field"] for error in refused.json()["errors"]] == ["windows"]
    assert "overlap" in refused.json()["detail"]


def test_an_ideal_session_off_the_grid_is_refused(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    refused = http.put(
        owned.area,
        json={"windows": [MIDDAY], "strength": "soft", "preferredDurationMinutes": 25},
        headers=signed_in,
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert [error["field"] for error in refused.json()["errors"]] == ["preferredDurationMinutes"]


@pytest.mark.parametrize("kind", ["area", "habit", "task"], ids=["area", "habit", "task"])
def test_an_omitted_window_list_is_refused_rather_than_read_as_an_opt_out(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    kind: str,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # An empty list is a statement: on an override it opts this one thing out of its Area's
    # windows. A defaulted key could not carry that, because a forgotten key would make the same
    # statement, which is a placement decision nobody made. So the key is required.
    refused = http.put(owned.path(kind), json={"strength": "soft"}, headers=signed_in)

    assert refused.status_code == ValidationFailed.status, refused.text
    assert [error["field"] for error in refused.json()["errors"]] == ["body.windows"]
    assert preference_rows(live_database_url, owner.tenant_id) == []


def test_an_explicit_empty_list_is_accepted_and_is_the_opt_out(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    # The control for the refusal above: the statement is sendable, and only sendable on purpose.
    put(http, signed_in, owned.area, **GYM_WINDOWS)

    body = put(http, signed_in, owned.habit, windows=[], strength="soft")

    assert body["declared"]["windows"] == []
    assert body["effective"]["source"] == {"kind": "habit", "id": owned.habit_id}


def test_the_stored_window_is_the_wall_time_that_was_sent(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # Read out of Postgres rather than out of the response. The strings carry no offset, because the
    # boundary refused one, so there is nothing for a column to drop in silence.
    put(http, signed_in, owned.area, **GYM_WINDOWS)

    rows = preference_rows(live_database_url, owner.tenant_id)

    assert len(rows) == 1
    assert rows[0].windows == [
        {"start": "05:30:00", "end": "07:00:00"},
        {"start": "13:15:00", "end": "14:15:00"},
    ]
    assert rows[0].owner_kind == "area"
    assert (rows[0].habit_id, rows[0].task_id) == (None, None)


@pytest.mark.parametrize("kind", ["area", "habit", "task"], ids=["area", "habit", "task"])
def test_an_unknown_field_is_refused(
    http: TestClient, signed_in: dict[str, str], owned: Owned, kind: str
) -> None:
    refused = http.put(
        owned.path(kind),
        json={"windows": [MIDDAY], "strength": "soft", "preferredTimes": ["05:30"]},
        headers=signed_in,
    )

    assert refused.status_code == ValidationFailed.status, refused.text


# --------------------------------------------------------------------------------
# Replacement and removal
# --------------------------------------------------------------------------------


def test_a_replacement_leaves_one_row_and_the_last_body_wins(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    put(http, signed_in, owned.area, windows=[EARLY], strength="strong", maxPerDayMinutes=180)

    body = put(http, signed_in, owned.area, windows=[EVENING], strength="soft")

    rows = preference_rows(live_database_url, owner.tenant_id)
    assert len(rows) == 1
    # A field the second body left out is null afterwards rather than left at what the first set.
    assert rows[0].max_per_day_minutes is None
    assert body["declared"]["windows"] == [{"start": "19:00:00", "end": "21:00:00"}]


def test_a_repeated_replacement_answers_the_same_body(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    # Which is why these routes take no idempotency guard: a repeat is indistinguishable from the
    # first call, so there is nothing for a guard to protect.
    first = put(http, signed_in, owned.area, **GYM_WINDOWS)
    second = put(http, signed_in, owned.area, **GYM_WINDOWS)

    assert first == second


@pytest.mark.parametrize("kind", ["habit", "task"], ids=["habit", "task"])
def test_removing_an_override_restores_its_areas_preference(
    http: TestClient, signed_in: dict[str, str], owned: Owned, kind: str
) -> None:
    put(http, signed_in, owned.area, **GYM_WINDOWS)
    overridden = put(http, signed_in, owned.path(kind), windows=[EVENING], strength="soft")
    assert overridden["effective"]["source"]["kind"] == kind

    removed = http.delete(owned.path(kind), headers=signed_in)

    assert removed.status_code == HTTPStatus.OK, removed.text
    body = removed.json()
    assert body["declared"] is None
    assert body["effective"]["source"] == {"kind": "area", "id": owned.area_id}
    assert http.get(owned.path(kind), headers=signed_in).json() == body


def test_removing_a_preference_that_was_never_set_answers_the_same_state(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    # Idempotent by construction: the caller asked for a state it is already in, and the response
    # says what that state is rather than refusing a request that changed nothing.
    removed = http.delete(owned.habit, headers=signed_in)

    assert removed.status_code == HTTPStatus.OK, removed.text
    assert removed.json()["declared"] is None


def test_removing_an_areas_preference_leaves_its_overrides_alone(
    http: TestClient, signed_in: dict[str, str], owned: Owned
) -> None:
    put(http, signed_in, owned.area, **GYM_WINDOWS)
    put(http, signed_in, owned.habit, windows=[EVENING], strength="soft")

    assert http.delete(owned.area, headers=signed_in).status_code == HTTPStatus.OK

    habit = http.get(owned.habit, headers=signed_in).json()
    assert habit["effective"]["source"] == {"kind": "habit", "id": owned.habit_id}


def test_removing_a_habit_removes_the_preference_it_owned(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # The cascade, which is why the owner is a real reference rather than an untyped identifier: a
    # preference addressed to a row that no longer exists would be a window the resolution still
    # read after the user deleted the thing it belonged to.
    put(http, signed_in, owned.habit, windows=[EVENING], strength="soft")
    assert len(preference_rows(live_database_url, owner.tenant_id)) == 1

    removed = http.delete(f"{HABITS_PREFIX}/{owned.habit_id}", headers=signed_in)

    assert removed.status_code == HTTPStatus.NO_CONTENT, removed.text
    assert preference_rows(live_database_url, owner.tenant_id) == []


# --------------------------------------------------------------------------------
# A stored row nothing can read, and the path that repairs it
# --------------------------------------------------------------------------------


def test_a_stored_window_carrying_an_offset_is_a_422_on_read(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # The read-back refusal, driven over a real request. A 422 rather than a 500, and rather than a
    # window silently resolved against the wrong hour, which is the failure this layer exists for.
    put(http, signed_in, owned.area, **GYM_WINDOWS)
    store_a_window_no_reader_will_accept(live_database_url, owner.tenant_id)

    refused = http.get(owned.area, headers=signed_in)

    assert refused.status_code == ValidationFailed.status, refused.text
    assert "names no zone" in refused.json()["detail"]
    # The message names a time rather than a Python repr, because it reaches a caller here: the
    # request validator that would normally refuse an offset never saw this value.
    assert "05:30:00+01:00" in refused.json()["detail"]
    assert "tzinfo" not in refused.json()["detail"]


def test_a_corrupt_area_row_makes_its_habit_unreadable_too(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # Correct, and worth pinning: a habit inheriting a window nothing can read must not be handed a
    # resolved preference an hour off. The repair path below is what keeps this recoverable.
    put(http, signed_in, owned.area, **GYM_WINDOWS)
    store_a_window_no_reader_will_accept(live_database_url, owner.tenant_id)

    refused = http.get(owned.habit, headers=signed_in)

    assert refused.status_code == ValidationFailed.status, refused.text


def test_a_clean_replacement_repairs_a_stored_row_nothing_could_read(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # The row a replacement is about to overwrite is read OUTSIDE the context that maps a domain
    # refusal to a 422, so a row nothing can read cannot refuse the request that would fix it.
    # Without that, removal would be the only way to clear one.
    put(http, signed_in, owned.area, **GYM_WINDOWS)
    store_a_window_no_reader_will_accept(live_database_url, owner.tenant_id)

    repaired = put(http, signed_in, owned.area, windows=[EVENING], strength="soft")

    assert repaired["declared"]["windows"] == [{"start": "19:00:00", "end": "21:00:00"}]
    assert http.get(owned.area, headers=signed_in).status_code == HTTPStatus.OK
    rows = preference_rows(live_database_url, owner.tenant_id)
    assert len(rows) == 1
    assert rows[0].windows == [{"start": "19:00:00", "end": "21:00:00"}]


def test_repairing_a_row_nothing_could_read_bumps_the_week(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # A row nothing can read is a row nothing is equal to, so the gate treats the repair as a
    # change. Anything else would leave a solve reading the value the repair replaced.
    put(http, signed_in, owned.area, **GYM_WINDOWS)
    store_a_window_no_reader_will_accept(live_database_url, owner.tenant_id)
    track(live_database_url, owner.tenant_id, FUTURE_WEEK)
    before = input_version(live_database_url, owner.tenant_id, FUTURE_WEEK)
    assert before is not None

    put(http, signed_in, owned.area, windows=[EVENING], strength="soft")

    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == before + 1


def test_a_removal_still_clears_a_row_nothing_could_read(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    # The escape that existed before the repair path did. It still works, and now it is a choice
    # rather than the only option.
    put(http, signed_in, owned.habit, windows=[EVENING], strength="soft")
    store_a_window_no_reader_will_accept(live_database_url, owner.tenant_id)

    removed = http.delete(owned.habit, headers=signed_in)

    assert removed.status_code == HTTPStatus.OK, removed.text
    assert preference_rows(live_database_url, owner.tenant_id) == []


# --------------------------------------------------------------------------------
# The owner has to exist, and it is the only thing these routes 404 on
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "prefix"),
    [("area", AREAS_PREFIX), ("habit", HABITS_PREFIX), ("task", TASKS_PREFIX)],
    ids=["area", "habit", "task"],
)
@pytest.mark.parametrize("method", ["get", "put", "delete"], ids=["get", "put", "delete"])
def test_an_unknown_owner_is_a_404_on_every_method(
    http: TestClient, signed_in: dict[str, str], kind: str, prefix: str, method: str
) -> None:
    path = f"{prefix}/{uuid4()}/preference"

    answered = http.request(
        method.upper(),
        path,
        json={"windows": [MIDDAY], "strength": "soft"} if method == "put" else None,
        headers=signed_in,
    )

    assert answered.status_code == NotFound.status, answered.text


def test_another_tenants_area_is_a_404_rather_than_an_edit(
    http: TestClient, signed_in: dict[str, str], owned: Owned, live_database_url: str
) -> None:
    intruder = provision_owner(live_database_url)
    try:
        response = http.post(
            f"{AUTH_PREFIX}/login",
            json={"email": intruder.email, "password": PASSWORD},
            headers={"Origin": BROWSER_ORIGIN},
        )
        assert response.status_code == HTTPStatus.OK, response.text
        theirs = {
            "Cookie": f"{SESSION_COOKIE_NAME}={response.cookies[SESSION_COOKIE_NAME]}",
            "Origin": BROWSER_ORIGIN,
        }

        refused = http.put(
            owned.area, json={"windows": [MIDDAY], "strength": "soft"}, headers=theirs
        )

        assert refused.status_code == NotFound.status, refused.text
    finally:
        remove_tenant(live_database_url, intruder.tenant_id)


# --------------------------------------------------------------------------------
# The week input version
# --------------------------------------------------------------------------------


def test_every_mutation_bumps_the_tracked_week_and_leaves_a_past_one_alone(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # A preference is read by the time-of-day misfit cost and by the Area's daily cap, so a running
    # solve has to be superseded. Read from the row a solve's conditional write guards on.
    track(live_database_url, owner.tenant_id, FUTURE_WEEK, PAST_WEEK)
    before = input_version(live_database_url, owner.tenant_id, FUTURE_WEEK)
    assert before is not None

    put(http, signed_in, owned.area, **GYM_WINDOWS)
    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == before + 1

    put(http, signed_in, owned.habit, windows=[EVENING], strength="soft")
    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == before + 2

    assert http.delete(owned.habit, headers=signed_in).status_code == HTTPStatus.OK
    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == before + 3

    # An approved revision is immutable and keeps the inputs it was computed with, so a past week is
    # not re-derived by a preference change.
    assert input_version(live_database_url, owner.tenant_id, PAST_WEEK) == 1


def test_a_replacement_that_changed_nothing_bumps_nothing(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    # The control for the bumps above: invalidating a week for a request that changed nothing would
    # discard a running solve for free.
    put(http, signed_in, owned.area, **GYM_WINDOWS)
    track(live_database_url, owner.tenant_id, FUTURE_WEEK)
    before = input_version(live_database_url, owner.tenant_id, FUTURE_WEEK)

    put(http, signed_in, owned.area, **GYM_WINDOWS)

    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == before


def test_a_refused_mutation_and_a_read_bump_nothing(
    http: TestClient,
    signed_in: dict[str, str],
    owned: Owned,
    owner: UserRecord,
    live_database_url: str,
) -> None:
    track(live_database_url, owner.tenant_id, FUTURE_WEEK)
    before = input_version(live_database_url, owner.tenant_id, FUTURE_WEEK)

    refused = http.put(
        owned.habit,
        json={"windows": [MIDDAY], "strength": "soft", "maxPerDayMinutes": 180},
        headers=signed_in,
    )
    assert refused.status_code == ValidationFailed.status, refused.text
    assert http.get(owned.area, headers=signed_in).status_code == HTTPStatus.OK

    assert input_version(live_database_url, owner.tenant_id, FUTURE_WEEK) == before
