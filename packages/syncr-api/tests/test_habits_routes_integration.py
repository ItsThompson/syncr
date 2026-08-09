"""The five habit routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a real
database can: that a rejected declaration is not stored, that both derived figures reach the wire
read-only, that no request shape has a field for either of them, and that another tenant's
identifier is a 404 rather than an edit.

Two groups are worth reading. **The cursor group** is the shape this ticket exists to preserve:
every response renders it read-only with its provenance, a fixed habit renders ``null``, and a
body carrying one is refused rather than ignored. **The absence group** asserts the two fields
that do not exist, because an absence nothing tests is an absence a later ticket adds back.

Every occurrence-derived figure reads from an empty log here, because this suite seeds no plan of
record and records no outcome. The figures themselves are asserted against an occupied log in the
service suite through the reader seam, and against rows the outcome routes wrote in
``test_habit_outcome_log_integration.py``.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.habits.config import HABITS_PREFIX
from syncr_api.habits.models import HabitRow
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_domain.habits import MAX_VARIANTS, BindingSource, CadenceKind, MissPolicy
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
AREAS = AREAS_PREFIX
HABITS = HABITS_PREFIX

GYM_SPLIT = ["Shoulder & Arms", "Legs", "Chest & Back", "Cardio"]
FOUR_A_WEEK: dict[str, Any] = {"kind": CadenceKind.TIMES_PER_WEEK.value, "timesPerWeek": 4}
DAILY: dict[str, Any] = {"kind": CadenceKind.DAILY.value}


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


@pytest.fixture
def area_id(http: TestClient, signed_in: dict[str, str]) -> str:
    """One Area to declare habits inside. A habit's occurrences count toward exactly one."""
    response = http.post(AREAS, json={"name": f"Fitness {uuid4().hex[:8]}"}, headers=signed_in)
    assert response.status_code == HTTPStatus.CREATED, response.text
    identifier: str = response.json()["area"]["id"]
    return identifier


def habit_rows(database_url: str, tenant_id: TenantId) -> list[HabitRow]:
    """The tenant's habit rows, read on a connection of this test's own."""

    async def read() -> list[HabitRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(HabitRow)
                    .where(HabitRow.tenant_id == tenant_id)
                    .order_by(HabitRow.created_at, HabitRow.id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def body(area: str, **overrides: object) -> dict[str, Any]:
    """A fixed, forgiving, four-times-a-week 90-minute habit, with fields replaced."""
    declared: dict[str, Any] = {
        "areaId": area,
        "title": "Gym",
        "cadence": dict(FOUR_A_WEEK),
        "minDurationMinutes": 90,
    }
    declared.update(overrides)
    return declared


def declare(http: TestClient, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    """The habit body a successful declaration answers with.

    Typed loosely on purpose: every assertion below reads the JSON a real client receives rather
    than a shape reconstructed from the schema it was serialized by.
    """
    response = http.post(HABITS, json=payload, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    created: dict[str, Any] = response.json()
    return created


# --------------------------------------------------------------------------------
# Declaring, reading, and the round trip through the wire
# --------------------------------------------------------------------------------


def test_the_habits_route_needs_a_credential(http: TestClient) -> None:
    response = http.get(HABITS)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_declaring_a_habit_commits_it_and_answers_with_both_derived_figures(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    area_id: str,
) -> None:
    created = declare(http, signed_in, body(area_id))

    assert created["title"] == "Gym"
    assert created["cadence"] == {"kind": "times_per_week", "timesPerWeek": 4, "approxDays": None}
    # Fixed is min == max, so a caller writes the number once and reads it twice.
    assert (created["minDurationMinutes"], created["maxDurationMinutes"]) == (90, 90)
    assert created["missPolicy"] == MissPolicy.FORGIVE.value
    assert created["bindingSource"] == BindingSource.FIXED.value
    assert created["variants"] == []
    assert created["debtCapPeriods"] == 2
    assert created["cursor"] is None
    assert created["debt"]["outstanding"] == 0
    assert created["debt"]["cap"] == 8

    rows = habit_rows(live_database_url, owner.tenant_id)
    assert [(row.title, row.cadence_times_per_week) for row in rows] == [("Gym", 4)]
    assert http.get(HABITS, headers=signed_in).json()["habits"] == [created]


def test_every_cadence_kind_round_trips_through_the_wire_and_the_columns(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    """Three kinds, and the number each carries survives the row it is stored in."""
    cadences: list[dict[str, Any]] = [
        {"kind": "times_per_week", "timesPerWeek": 4, "approxDays": None},
        {"kind": "daily", "timesPerWeek": None, "approxDays": None},
        {"kind": "every_approx_days", "timesPerWeek": None, "approxDays": 7},
    ]

    for index, cadence in enumerate(cadences):
        created = declare(http, signed_in, body(area_id, title=f"Habit {index}", cadence=cadence))
        read = http.get(f"{HABITS}/{created['id']}", headers=signed_in)

        assert read.status_code == HTTPStatus.OK, read.text
        assert read.json()["cadence"] == cadence


def test_a_body_whose_cadence_numbers_do_not_match_its_kind_is_refused_and_not_stored(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    area_id: str,
) -> None:
    for cadence in (
        {"kind": "daily", "timesPerWeek": 4},
        {"kind": "times_per_week"},
        {"kind": "times_per_week", "timesPerWeek": 4, "approxDays": 7},
        {"kind": "every_approx_days"},
    ):
        response = http.post(HABITS, json=body(area_id, cadence=cadence), headers=signed_in)

        assert response.status_code == ValidationFailed.status, response.text
    assert habit_rows(live_database_url, owner.tenant_id) == []


def test_an_interval_of_one_day_is_refused_because_daily_already_says_it(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    response = http.post(
        HABITS,
        json=body(area_id, cadence={"kind": "every_approx_days", "approxDays": 1}),
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status, response.text


def test_a_habit_in_an_area_that_does_not_exist_is_refused_and_not_stored(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    response = http.post(HABITS, json=body(str(uuid4())), headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text
    assert response.json()["errors"][0]["field"] == "areaId"
    assert habit_rows(live_database_url, owner.tenant_id) == []


def test_an_elastic_duration_reaches_the_wire_as_two_numbers(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    created = declare(http, signed_in, body(area_id, minDurationMinutes=30, maxDurationMinutes=90))

    assert (created["minDurationMinutes"], created["maxDurationMinutes"]) == (30, 90)


@pytest.mark.parametrize("minutes", [25, 20, 0, 1445])
def test_a_duration_off_the_grid_or_off_the_bound_is_refused(
    http: TestClient, signed_in: dict[str, str], area_id: str, minutes: int
) -> None:
    response = http.post(HABITS, json=body(area_id, minDurationMinutes=minutes), headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


# --------------------------------------------------------------------------------
# X3 and X4 through HTTP, in both directions
# --------------------------------------------------------------------------------


def test_a_rotation_habit_holds_its_variants_in_order(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    created = declare(
        http,
        signed_in,
        body(area_id, bindingSource=BindingSource.ROTATION.value, variants=GYM_SPLIT),
    )

    assert created["variants"] == GYM_SPLIT


def test_a_rotation_habit_without_variants_is_refused_and_not_stored(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    area_id: str,
) -> None:
    response = http.post(
        HABITS, json=body(area_id, bindingSource=BindingSource.ROTATION.value), headers=signed_in
    )

    assert response.status_code == ValidationFailed.status, response.text
    assert habit_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize(
    "source", [BindingSource.FIXED, BindingSource.QUEUE], ids=lambda source: source.value
)
def test_a_habit_that_does_not_rotate_carrying_variants_is_refused(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    area_id: str,
    source: BindingSource,
) -> None:
    response = http.post(
        HABITS,
        json=body(area_id, bindingSource=source.value, variants=GYM_SPLIT),
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status, response.text
    assert habit_rows(live_database_url, owner.tenant_id) == []


def test_a_queue_habit_records_its_source_and_names_no_content(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    """Queue selection happens at solve time. What a habit records is that it draws from one."""
    created = declare(http, signed_in, body(area_id, bindingSource=BindingSource.QUEUE.value))

    assert created["bindingSource"] == BindingSource.QUEUE.value
    assert created["variants"] == []
    assert created["cursor"] is None


def test_a_variant_list_longer_than_a_rotation_holds_is_refused(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    response = http.post(
        HABITS,
        json=body(
            area_id,
            bindingSource=BindingSource.ROTATION.value,
            variants=[f"Day {index}" for index in range(MAX_VARIANTS + 1)],
        ),
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status, response.text


# --------------------------------------------------------------------------------
# The cursor: read-only, with its provenance, and nowhere to set it
# --------------------------------------------------------------------------------


def test_a_rotation_habit_renders_its_cursor_read_only_with_its_provenance(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    created = declare(
        http,
        signed_in,
        body(area_id, bindingSource=BindingSource.ROTATION.value, variants=GYM_SPLIT),
    )

    cursor = created["cursor"]
    assert cursor["index"] == 0
    assert cursor["variant"] == "Shoulder & Arms"
    assert cursor["confirmedCompletions"] == 0
    assert cursor["previousVariant"] is None
    assert cursor["advancedAt"] is None
    assert "no control to set it" in cursor["statement"]


def test_a_fixed_source_habit_displays_no_cursor_at_all(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    created = declare(http, signed_in, body(area_id))

    assert created["cursor"] is None
    assert http.get(f"{HABITS}/{created['id']}", headers=signed_in).json()["cursor"] is None


@pytest.mark.parametrize(
    "field", ["cursor", "cursorIndex", "rotationCursor", "variantIndex", "debt", "outstandingDebt"]
)
def test_no_request_shape_accepts_a_cursor_or_a_debt_figure(
    http: TestClient, signed_in: dict[str, str], area_id: str, field: str
) -> None:
    """Both are projections of the outcome log, so there is no field that could carry one back.

    Refused rather than ignored: a body a caller believes set the cursor and that silently did
    not is worse than a stated rejection.
    """
    created = declare(http, signed_in, body(area_id, title=f"Gym {field}"))

    declared = http.post(HABITS, json=body(area_id, **{field: 2}), headers=signed_in)
    patched = http.patch(f"{HABITS}/{created['id']}", json={field: 2}, headers=signed_in)

    assert declared.status_code == ValidationFailed.status, declared.text
    assert patched.status_code == ValidationFailed.status, patched.text


@pytest.mark.parametrize(
    "field",
    ["preferredTime", "preferredTimes", "windows", "targetTime", "preferredDurationMinutes"],
)
def test_no_request_shape_accepts_a_preferred_time(
    http: TestClient, signed_in: dict[str, str], area_id: str, field: str
) -> None:
    """When a habit's work should happen is a Preference, authored through its own route."""
    created = declare(http, signed_in, body(area_id, title=f"Gym {field}"))

    declared = http.post(HABITS, json=body(area_id, **{field: "05:30"}), headers=signed_in)
    patched = http.patch(f"{HABITS}/{created['id']}", json={field: "05:30"}, headers=signed_in)

    assert declared.status_code == ValidationFailed.status, declared.text
    assert patched.status_code == ValidationFailed.status, patched.text


def test_a_habit_response_carries_no_field_beyond_the_ones_this_contract_names(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    """The absence of a preferred time and of a settable cursor, asserted against the wire."""
    created = declare(http, signed_in, body(area_id))

    assert set(created) == {
        "id",
        "areaId",
        "title",
        "cadence",
        "minDurationMinutes",
        "maxDurationMinutes",
        "missPolicy",
        "bindingSource",
        "variants",
        "debtCapPeriods",
        "cursor",
        "debt",
    }


# --------------------------------------------------------------------------------
# Debt on the habit
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cadence", "periods", "cap"),
    [(FOUR_A_WEEK, 2, 8), (FOUR_A_WEEK, 1, 4), (DAILY, 2, 2), (DAILY, 3, 3)],
)
def test_the_current_debt_figure_and_its_cap_are_visible_on_the_habit(
    http: TestClient,
    signed_in: dict[str, str],
    area_id: str,
    cadence: dict[str, Any],
    periods: int,
    cap: int,
) -> None:
    created = declare(
        http,
        signed_in,
        body(
            area_id,
            title=f"Habit {cadence['kind']} {periods}",
            cadence=dict(cadence),
            missPolicy=MissPolicy.DEBT.value,
            debtCapPeriods=periods,
        ),
    )

    assert created["debt"]["cap"] == cap
    assert created["debt"]["outstanding"] == 0
    assert created["debt"]["raisedInWeeklySession"] is False


def test_a_debt_cap_of_zero_is_refused_because_escalate_already_says_it(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    response = http.post(
        HABITS,
        json=body(area_id, missPolicy=MissPolicy.DEBT.value, debtCapPeriods=0),
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status, response.text


# --------------------------------------------------------------------------------
# Changing and removing
# --------------------------------------------------------------------------------


def test_a_patch_changes_the_stated_fields_and_leaves_the_rest(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    created = declare(http, signed_in, body(area_id))

    response = http.patch(
        f"{HABITS}/{created['id']}",
        json={"cadence": {"kind": "daily"}, "missPolicy": MissPolicy.DEBT.value},
        headers=signed_in,
    )

    assert response.status_code == HTTPStatus.OK, response.text
    changed = response.json()
    assert changed["cadence"] == {"kind": "daily", "timesPerWeek": None, "approxDays": None}
    assert changed["missPolicy"] == MissPolicy.DEBT.value
    assert changed["title"] == "Gym"
    assert changed["minDurationMinutes"] == 90
    # The cap follows the cadence, because a period is a day now rather than a week.
    assert changed["debt"]["cap"] == 2


def test_a_patch_cannot_move_a_habit_between_areas(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    """Declared once: the hours already attributed to the Area were attributed to that Area."""
    created = declare(http, signed_in, body(area_id))

    response = http.patch(
        f"{HABITS}/{created['id']}", json={"areaId": str(uuid4())}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status, response.text


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "cadence",
        "minDurationMinutes",
        "missPolicy",
        "bindingSource",
        "variants",
        "debtCapPeriods",
    ],
)
def test_an_explicit_null_is_refused_on_every_patchable_field(
    http: TestClient, signed_in: dict[str, str], area_id: str, field: str
) -> None:
    """Nothing on a habit is nullable, so null is a stated 422 rather than "no change"."""
    created = declare(http, signed_in, body(area_id))

    response = http.patch(f"{HABITS}/{created['id']}", json={field: None}, headers=signed_in)

    assert response.status_code == ValidationFailed.status, response.text


def test_switching_a_rotation_off_states_the_source_and_the_empty_list_together(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    created = declare(
        http,
        signed_in,
        body(area_id, bindingSource=BindingSource.ROTATION.value, variants=GYM_SPLIT),
    )

    refused = http.patch(
        f"{HABITS}/{created['id']}",
        json={"bindingSource": BindingSource.FIXED.value},
        headers=signed_in,
    )
    accepted = http.patch(
        f"{HABITS}/{created['id']}",
        json={"bindingSource": BindingSource.FIXED.value, "variants": []},
        headers=signed_in,
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert accepted.status_code == HTTPStatus.OK, accepted.text
    assert accepted.json()["cursor"] is None


def test_removing_a_habit_answers_no_content_and_deletes_the_row(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    area_id: str,
) -> None:
    created = declare(http, signed_in, body(area_id))

    response = http.delete(f"{HABITS}/{created['id']}", headers=signed_in)

    assert response.status_code == HTTPStatus.NO_CONTENT, response.text
    assert response.content == b""
    assert habit_rows(live_database_url, owner.tenant_id) == []


def test_reading_a_habit_that_does_not_exist_is_a_problem_document(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(f"{HABITS}/{uuid4()}", headers=signed_in)

    assert response.status_code == NotFound.status
    assert response.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)


def test_another_tenant_s_habit_is_a_404_rather_than_an_edit(
    http: TestClient, signed_in: dict[str, str], live_database_url: str, area_id: str
) -> None:
    stranger = provision_owner(live_database_url)
    try:
        theirs = _sign_in(http, stranger.email)
        their_area = http.post(AREAS, json={"name": "Theirs"}, headers=theirs).json()["area"]["id"]
        their_habit = declare(http, theirs, body(their_area, title="Theirs"))

        read = http.get(f"{HABITS}/{their_habit['id']}", headers=signed_in)
        patched = http.patch(
            f"{HABITS}/{their_habit['id']}", json={"title": "Mine now"}, headers=signed_in
        )
        removed = http.delete(f"{HABITS}/{their_habit['id']}", headers=signed_in)

        assert read.status_code == NotFound.status
        assert patched.status_code == NotFound.status
        assert removed.status_code == NotFound.status
        assert habit_rows(live_database_url, stranger.tenant_id)[0].title == "Theirs"
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


# --------------------------------------------------------------------------------
# Idempotency, on all three unsafe methods
# --------------------------------------------------------------------------------


def test_a_repeated_declaration_under_one_key_creates_one_habit(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    area_id: str,
) -> None:
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}
    payload = body(area_id)

    first = http.post(HABITS, json=payload, headers=keyed)
    replayed = http.post(HABITS, json=payload, headers=keyed)

    assert first.status_code == HTTPStatus.CREATED, first.text
    assert replayed.status_code == HTTPStatus.CREATED, replayed.text
    assert replayed.json() == first.json()
    assert len(habit_rows(live_database_url, owner.tenant_id)) == 1


def test_a_repeated_patch_under_one_key_replays_rather_than_applying_twice(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    created = declare(http, signed_in, body(area_id))
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}

    first = http.patch(f"{HABITS}/{created['id']}", json={"title": "Gym, early"}, headers=keyed)
    replayed = http.patch(f"{HABITS}/{created['id']}", json={"title": "Gym, early"}, headers=keyed)

    assert first.status_code == HTTPStatus.OK, first.text
    assert replayed.json() == first.json()


def test_a_repeated_removal_under_one_key_answers_no_content_rather_than_404(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    """The reason the removal has a response model: without one, a retry would report a failure."""
    created = declare(http, signed_in, body(area_id))
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}

    first = http.delete(f"{HABITS}/{created['id']}", headers=keyed)
    replayed = http.delete(f"{HABITS}/{created['id']}", headers=keyed)

    assert first.status_code == HTTPStatus.NO_CONTENT, first.text
    assert replayed.status_code == HTTPStatus.NO_CONTENT, replayed.text
    assert replayed.content == b""


def test_a_removal_without_a_key_is_a_404_the_second_time(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    """The control for the test above: the guarantee comes from the key, not from the route."""
    created = declare(http, signed_in, body(area_id))

    assert http.delete(f"{HABITS}/{created['id']}", headers=signed_in).status_code == (
        HTTPStatus.NO_CONTENT
    )
    assert http.delete(f"{HABITS}/{created['id']}", headers=signed_in).status_code == (
        NotFound.status
    )


def test_one_key_reused_for_a_different_body_is_refused(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: uuid4().hex}

    first = http.post(HABITS, json=body(area_id, title="Gym"), headers=keyed)
    reused = http.post(HABITS, json=body(area_id, title="Anki"), headers=keyed)

    assert first.status_code == HTTPStatus.CREATED, first.text
    assert reused.status_code == ValidationFailed.status, reused.text


# --------------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------------


def test_a_list_can_be_narrowed_to_one_area(
    http: TestClient, signed_in: dict[str, str], area_id: str
) -> None:
    elsewhere = http.post(AREAS, json={"name": "Learning"}, headers=signed_in).json()["area"]["id"]
    declare(http, signed_in, body(area_id, title="Gym"))
    declare(http, signed_in, body(elsewhere, title="Anki"))

    everything = http.get(HABITS, headers=signed_in).json()["habits"]
    narrowed = http.get(HABITS, params={"areaId": elsewhere}, headers=signed_in).json()["habits"]

    assert [habit["title"] for habit in everything] == ["Gym", "Anki"]
    assert [habit["title"] for habit in narrowed] == ["Anki"]


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
