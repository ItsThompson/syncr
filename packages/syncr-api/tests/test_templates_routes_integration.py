"""The twelve day-shape routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a real
database can: that the pairing rule is refused at the wire in both directions, that a cadence
cannot reach any of these bodies, that a week pattern is replaced rather than patched, that a
materialized shape creates no ``Pin`` row, and that a pattern edit reaches every future week's
input version while leaving an approved past week's revision exactly as it was.

Three tests are worth reading. ``test_a_pattern_edit_leaves_an_approved_past_week_untouched`` is
the immutability half of the invalidation rule, asserted on the stored document rather than on the
absence of an error. ``test_neither_kind_of_entry_can_carry_a_cadence`` is the invariant that keeps
recurrence on habits, and it is asserted for both kinds because a union rejects an unknown field
per member. ``test_a_declared_shape_creates_no_pin_row`` is the distinction ticket 39 depends on:
an entry is fixed by derivation, which is not the same thing as pinned.

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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import Conflict, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.plans.config import APPROVED
from syncr_api.plans.facts import Pin
from syncr_api.plans.models import PlanRevision, WeekInputVersion
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.templates.config import (
    DAY_TYPES_PREFIX,
    TEMPLATES_PREFIX,
    WEEK_PATTERN_PREFIX,
)
from syncr_api.templates.models import (
    DayTypeRow,
    TemplateEntryRow,
    TemplateRow,
    WeekPatternRow,
)
from syncr_domain.templates import BindingTarget, TemplateEntryKind
from syncr_domain.weeks import IsoWeek, Weekday
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
DAY_TYPES = DAY_TYPES_PREFIX
TEMPLATES = TEMPLATES_PREFIX
WEEK_PATTERN = WEEK_PATTERN_PREFIX

NOW = datetime.now(UTC)
# Two weeks either side of the current one, so neither is near a week boundary the local date
# could fall on the other side of.
PAST_WEEK = IsoWeek.containing(NOW.date() - timedelta(days=14))
FUTURE_WEEK = IsoWeek.containing(NOW.date() + timedelta(days=14))

A_CONCRETE_ENTRY: dict[str, Any] = {
    "kind": "concrete",
    "targetTime": "07:00:00",
    "durationMinutes": 15,
    "flexBandMinutes": 15,
    "bindingTarget": "routine",
    "bindingRef": str(uuid4()),
}


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


def entry_rows(database_url: str, tenant_id: TenantId) -> list[TemplateEntryRow]:
    """The tenant's entry rows, read on a connection of this test's own."""

    async def read() -> list[TemplateEntryRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(TemplateEntryRow).where(TemplateEntryRow.tenant_id == tenant_id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def pattern_rows(database_url: str, tenant_id: TenantId) -> list[WeekPatternRow]:
    async def read() -> list[WeekPatternRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(WeekPatternRow).where(WeekPatternRow.tenant_id == tenant_id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def pin_count(database_url: str, tenant_id: TenantId) -> int:
    async def read() -> int:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(select(Pin).where(Pin.tenant_id == tenant_id))
                return len(list(found))
        finally:
            await database.engine.dispose()

    return run(read())


def track_weeks(database_url: str, tenant_id: TenantId, *weeks: IsoWeek) -> dict[str, int]:
    """Create a version row for each week, and answer with the versions they start at."""

    async def write() -> dict[str, int]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                versions = WeekInputVersionRepository(session, tenant_id)
                return {str(week): await versions.bump(week, at=NOW) for week in weeks}
        finally:
            await database.engine.dispose()

    return run(write())


def week_versions(database_url: str, tenant_id: TenantId) -> dict[str, int]:
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


def approve_a_revision(database_url: str, tenant_id: TenantId, week: IsoWeek) -> dict[str, Any]:
    """Append an approved revision for ``week`` and answer with its stored document."""
    document = {"iso_week": str(week), "blocks": [{"id": "block-1"}], "discretionary_minutes": 4320}

    async def write() -> dict[str, Any]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                appended = await PlanRepository(session, tenant_id).append(
                    document=document,
                    objective_breakdown={"budget_deviation": 1.5},
                    status=APPROVED,
                    reason="user_approved",
                    weight_set_version=1,
                    input_version=1,
                    created_at=NOW,
                    approved_at=NOW,
                )
                return {"id": str(appended.id), "document": dict(appended.document)}
        finally:
            await database.engine.dispose()

    return run(write())


def stored_revisions(database_url: str, tenant_id: TenantId) -> list[dict[str, Any]]:
    async def read() -> list[dict[str, Any]]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(PlanRevision).where(PlanRevision.tenant_id == tenant_id)
                )
                return [
                    {
                        "id": str(row.id),
                        "document": dict(row.document),
                        "status": row.status,
                        "input_version": row.input_version,
                    }
                    for row in found
                ]
        finally:
            await database.engine.dispose()

    return run(read())


def declare_day_type(http: TestClient, headers: dict[str, str], name: str) -> str:
    response = http.post(DAY_TYPES, json={"name": name}, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    identifier: str = response.json()["id"]
    return identifier


def declare_shape(http: TestClient, headers: dict[str, str], day_type_id: str, name: str) -> str:
    response = http.post(TEMPLATES, json={"dayTypeId": day_type_id, "name": name}, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    identifier: str = response.json()["id"]
    return identifier


def declare_area(http: TestClient, headers: dict[str, str], name: str) -> str:
    response = http.post(AREAS_PREFIX, json={"name": name}, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    identifier: str = response.json()["area"]["id"]
    return identifier


def a_mapping(day_type_id: str, **overrides: str) -> dict[str, str]:
    """All seven weekdays on one day type, with any weekday overridden by name."""
    return {weekday.value: day_type_id for weekday in Weekday} | overrides


def declare_pattern(
    http: TestClient, headers: dict[str, str], mapping: dict[str, str]
) -> dict[str, Any]:
    response = http.put(WEEK_PATTERN, json=mapping, headers=headers)
    assert response.status_code == HTTPStatus.OK, response.text
    body: dict[str, Any] = response.json()
    return body


# --------------------------------------------------------------------------------
# Day types
# --------------------------------------------------------------------------------


def test_the_day_types_route_needs_a_credential(http: TestClient) -> None:
    assert http.get(DAY_TYPES).status_code == HTTPStatus.UNAUTHORIZED


def test_a_declared_day_type_reads_back_in_declaration_order(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    declare_day_type(http, signed_in, "Weekday")
    declare_day_type(http, signed_in, "Weekend")

    listed = http.get(DAY_TYPES, headers=signed_in)

    assert [row["name"] for row in listed.json()["dayTypes"]] == ["Weekday", "Weekend"]


def test_a_duplicate_day_type_name_answers_409_and_stores_nothing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    declare_day_type(http, signed_in, "Weekday")

    duplicate = http.post(DAY_TYPES, json={"name": "Weekday"}, headers=signed_in)

    assert duplicate.status_code == Conflict.status, duplicate.text
    assert len(http.get(DAY_TYPES, headers=signed_in).json()["dayTypes"]) == 1


# --------------------------------------------------------------------------------
# Shapes and their entries
# --------------------------------------------------------------------------------


def test_the_template_list_states_each_shapes_entry_count(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    for minute in ("07:00:00", "07:30:00"):
        added = http.post(
            f"{TEMPLATES}/{shape}/entries",
            json={**A_CONCRETE_ENTRY, "targetTime": minute, "bindingRef": str(uuid4())},
            headers=signed_in,
        )
        assert added.status_code == HTTPStatus.CREATED, added.text

    listed = http.get(TEMPLATES, headers=signed_in).json()["templates"]

    assert [(row["name"], row["entryCount"]) for row in listed] == [("Weekday shape", 2)]
    # The list states the count rather than the entries, so the shape read is what returns them.
    assert "entries" not in listed[0]


def test_entries_read_back_in_the_order_the_day_runs(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    for at_time in ("21:00:00", "06:15:00", "12:30:00"):
        http.post(
            f"{TEMPLATES}/{shape}/entries",
            json={**A_CONCRETE_ENTRY, "targetTime": at_time, "bindingRef": str(uuid4())},
            headers=signed_in,
        )

    read = http.get(f"{TEMPLATES}/{shape}", headers=signed_in)

    assert [entry["targetTime"] for entry in read.json()["entries"]] == [
        "06:15:00",
        "12:30:00",
        "21:00:00",
    ]


def test_a_second_shape_for_one_day_type_answers_409(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    declare_shape(http, signed_in, day_type, "Weekday shape")

    second = http.post(
        TEMPLATES, json={"dayTypeId": day_type, "name": "Another"}, headers=signed_in
    )

    assert second.status_code == Conflict.status, second.text
    assert "Weekday shape" in second.json()["detail"]


def test_a_slot_names_an_area_and_carries_no_binding(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    area = declare_area(http, signed_in, "Learning")
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")

    added = http.post(
        f"{TEMPLATES}/{shape}/entries",
        json={
            "kind": "slot",
            "targetTime": "18:00:00",
            "durationMinutes": 60,
            "areaId": area,
        },
        headers=signed_in,
    )

    assert added.status_code == HTTPStatus.CREATED, added.text
    entry = added.json()
    assert entry["areaId"] == area
    assert entry["bindingRef"] is None
    assert entry["bindingTarget"] is None
    # The band defaults to no give rather than to some, so a shape says what it means.
    assert entry["flexBandMinutes"] == 0


def test_a_slot_naming_another_tenants_area_answers_422_and_stores_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    stranger = provision_owner(live_database_url)
    try:
        foreign_area = declare_area(http, _sign_in(http, stranger.email), "Their learning")
        day_type = declare_day_type(http, signed_in, "Weekday")
        shape = declare_shape(http, signed_in, day_type, "Weekday shape")

        refused = http.post(
            f"{TEMPLATES}/{shape}/entries",
            json={
                "kind": "slot",
                "targetTime": "18:00:00",
                "durationMinutes": 60,
                "areaId": foreign_area,
            },
            headers=signed_in,
        )

        assert refused.status_code == ValidationFailed.status, refused.text
        assert [error["field"] for error in refused.json()["errors"]] == ["areaId"]
        assert entry_rows(live_database_url, owner.tenant_id) == []
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            {
                "kind": "concrete",
                "targetTime": "07:00:00",
                "durationMinutes": 15,
                "bindingTarget": "routine",
            },
            "a concrete entry with no binding names no content at all",
        ),
        (
            {
                "kind": "concrete",
                "targetTime": "07:00:00",
                "durationMinutes": 15,
                "areaId": str(uuid4()),
            },
            "an Area is not content, so it cannot stand in for a binding",
        ),
        (
            {
                "kind": "slot",
                "targetTime": "07:00:00",
                "durationMinutes": 15,
                "areaId": str(uuid4()),
                "bindingRef": str(uuid4()),
                "bindingTarget": "habit",
            },
            "a slot carrying a binding would be a concrete entry claiming to bind late",
        ),
        (
            {"kind": "slot", "targetTime": "07:00:00", "durationMinutes": 15},
            "a slot with no Area reserves time for nothing",
        ),
    ],
    ids=[
        "a concrete entry without its binding",
        "a concrete entry offering an Area instead",
        "a slot carrying a binding",
        "a slot without its Area",
    ],
)
def test_the_pairing_rule_is_refused_in_both_directions(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    body: dict[str, Any],
    reason: str,
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")

    refused = http.post(f"{TEMPLATES}/{shape}/entries", json=body, headers=signed_in)

    assert refused.status_code == ValidationFailed.status, reason
    assert refused.json()["errors"], reason
    assert entry_rows(live_database_url, owner.tenant_id) == []


@pytest.mark.parametrize(
    "cadence_field",
    ["cadence", "timesPerWeek", "frequency", "repeat"],
)
@pytest.mark.parametrize("kind", ["concrete", "slot"])
def test_neither_kind_of_entry_can_carry_a_cadence(
    http: TestClient, signed_in: dict[str, str], kind: str, cadence_field: str
) -> None:
    # Cadence lives on a habit. A template says what a day looks like, and a period on an entry
    # would be the fourth concept the three this package ships exist to avoid.
    area = declare_area(http, signed_in, "Learning")
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    body: dict[str, Any] = (
        {**A_CONCRETE_ENTRY}
        if kind == "concrete"
        else {"kind": "slot", "targetTime": "07:00:00", "durationMinutes": 15, "areaId": area}
    )

    refused = http.post(
        f"{TEMPLATES}/{shape}/entries", json={**body, cadence_field: 4}, headers=signed_in
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert http.get(f"{TEMPLATES}/{shape}", headers=signed_in).json()["entries"] == []


def test_a_patch_cannot_rebind_an_entry(http: TestClient, signed_in: dict[str, str]) -> None:
    # An entry's content is declared once: a materialized entry's identity is the entry keyed by
    # the local date, so rebinding one in place would re-point stored outcomes and pins.
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    entry = http.post(
        f"{TEMPLATES}/{shape}/entries", json=A_CONCRETE_ENTRY, headers=signed_in
    ).json()

    for body in ({"bindingRef": str(uuid4())}, {"kind": "slot"}, {"areaId": str(uuid4())}):
        refused = http.patch(
            f"{TEMPLATES}/{shape}/entries/{entry['id']}", json=body, headers=signed_in
        )
        assert refused.status_code == ValidationFailed.status, refused.text


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"targetTime": "07:05:00", "durationMinutes": 15}, "targetTime"),
        ({"targetTime": "07:00:00", "durationMinutes": 50}, "durationMinutes"),
    ],
    ids=["a target time between two quarter hours", "a duration that is not whole steps"],
)
def test_a_span_off_the_grid_is_refused_and_names_its_field(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    body: dict[str, Any],
    field: str,
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")

    refused = http.post(
        f"{TEMPLATES}/{shape}/entries",
        json={**A_CONCRETE_ENTRY, **body},
        headers=signed_in,
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert [error["field"] for error in refused.json()["errors"]] == [field]
    assert entry_rows(live_database_url, owner.tenant_id) == []


def test_an_entry_moves_and_keeps_what_it_holds(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    entry = http.post(
        f"{TEMPLATES}/{shape}/entries", json=A_CONCRETE_ENTRY, headers=signed_in
    ).json()

    moved = http.patch(
        f"{TEMPLATES}/{shape}/entries/{entry['id']}",
        json={"targetTime": "06:45:00"},
        headers=signed_in,
    )

    assert moved.status_code == HTTPStatus.OK, moved.text
    assert moved.json()["targetTime"] == "06:45:00"
    assert moved.json()["bindingRef"] == A_CONCRETE_ENTRY["bindingRef"]
    assert moved.json()["durationMinutes"] == A_CONCRETE_ENTRY["durationMinutes"]


@pytest.mark.parametrize("field", ["targetTime", "durationMinutes", "flexBandMinutes"])
def test_an_explicit_null_on_an_entry_patch_is_refused_rather_than_read_as_no_change(
    http: TestClient, signed_in: dict[str, str], field: str
) -> None:
    # Nothing in a span is nullable, so null and an omitted field would otherwise be the same
    # request: a caller who meant to clear something has to be told it cannot be cleared.
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    entry = http.post(
        f"{TEMPLATES}/{shape}/entries", json=A_CONCRETE_ENTRY, headers=signed_in
    ).json()

    refused = http.patch(
        f"{TEMPLATES}/{shape}/entries/{entry['id']}", json={field: None}, headers=signed_in
    )

    assert refused.status_code == ValidationFailed.status, refused.text
    assert "cannot be cleared" in refused.text
    stored = http.get(f"{TEMPLATES}/{shape}", headers=signed_in).json()["entries"][0]
    assert stored["targetTime"] == A_CONCRETE_ENTRY["targetTime"]


def test_a_null_shape_name_is_refused_rather_than_read_as_no_change(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")

    refused = http.patch(f"{TEMPLATES}/{shape}", json={"name": None}, headers=signed_in)

    assert refused.status_code == ValidationFailed.status, refused.text
    assert "cannot be cleared" in refused.text
    assert http.get(f"{TEMPLATES}/{shape}", headers=signed_in).json()["name"] == "Weekday shape"


def test_removing_a_shape_removes_its_entries(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    http.post(f"{TEMPLATES}/{shape}/entries", json=A_CONCRETE_ENTRY, headers=signed_in)

    removed = http.delete(f"{TEMPLATES}/{shape}", headers=signed_in)

    assert removed.status_code == HTTPStatus.NO_CONTENT
    assert removed.content == b""
    assert entry_rows(live_database_url, owner.tenant_id) == []
    assert http.get(f"{TEMPLATES}/{shape}", headers=signed_in).status_code == NotFound.status


def test_a_declared_shape_creates_no_pin_row(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # A template entry is fixed by DERIVATION rather than pinned. Both are hard constraints on
    # the solver and they differ in everything else: a pin is a user act with a superseded
    # placement and a training label, and an entry is a structural fact.
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    added = http.post(f"{TEMPLATES}/{shape}/entries", json=A_CONCRETE_ENTRY, headers=signed_in)

    assert added.status_code == HTTPStatus.CREATED, added.text
    assert pin_count(live_database_url, owner.tenant_id) == 0
    # And no shape here says anything about a pin, so no client can render a glyph from one.
    assert not [field for field in added.json() if "pin" in field.lower()]


def test_another_tenants_shape_is_a_404_rather_than_an_edit(
    http: TestClient, signed_in: dict[str, str], live_database_url: str
) -> None:
    stranger = provision_owner(live_database_url)
    try:
        stranger_headers = _sign_in(http, stranger.email)
        foreign_day_type = declare_day_type(http, stranger_headers, "Their weekday")
        foreign_shape = declare_shape(http, stranger_headers, foreign_day_type, "Theirs")

        read = http.get(f"{TEMPLATES}/{foreign_shape}", headers=signed_in)
        renamed = http.patch(
            f"{TEMPLATES}/{foreign_shape}", json={"name": "Mine"}, headers=signed_in
        )
        removed = http.delete(f"{TEMPLATES}/{foreign_shape}", headers=signed_in)

        assert read.status_code == NotFound.status
        assert renamed.status_code == NotFound.status
        assert removed.status_code == NotFound.status
        # And the row is untouched: a 404 that renamed it would be worse than a 403.
        listed = http.get(TEMPLATES, headers=stranger_headers).json()["templates"]
        assert [row["name"] for row in listed] == ["Theirs"]
    finally:
        remove_tenant(live_database_url, stranger.tenant_id)


# --------------------------------------------------------------------------------
# The week pattern
# --------------------------------------------------------------------------------


def test_reading_a_pattern_before_one_is_declared_is_a_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(WEEK_PATTERN, headers=signed_in)

    assert response.status_code == NotFound.status
    assert "seven weekdays" in response.json()["detail"]


def test_a_declared_pattern_maps_all_seven_weekdays(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    weekday = declare_day_type(http, signed_in, "Weekday")
    weekend = declare_day_type(http, signed_in, "Weekend")

    declared = declare_pattern(
        http, signed_in, a_mapping(weekday, saturday=weekend, sunday=weekend)
    )

    assert declared["monday"] == weekday
    assert declared["sunday"] == weekend
    assert sorted(declared) == sorted(weekday.value for weekday in Weekday)
    assert len(pattern_rows(live_database_url, owner.tenant_id)) == 7
    assert http.get(WEEK_PATTERN, headers=signed_in).json() == declared


@pytest.mark.parametrize(
    "left_out", ["monday", "thursday", "sunday"], ids=["the first", "one inside", "the last"]
)
def test_a_partial_mapping_is_refused_and_names_the_weekday(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    left_out: str,
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    mapping = a_mapping(day_type)
    del mapping[left_out]

    refused = http.put(WEEK_PATTERN, json=mapping, headers=signed_in)

    assert refused.status_code == ValidationFailed.status, refused.text
    assert any(left_out in error["field"] for error in refused.json()["errors"])
    assert pattern_rows(live_database_url, owner.tenant_id) == []


def test_a_pattern_is_replaced_rather_than_patched(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    weekday = declare_day_type(http, signed_in, "Weekday")
    weekend = declare_day_type(http, signed_in, "Weekend")
    declare_pattern(http, signed_in, a_mapping(weekday, saturday=weekend, sunday=weekend))

    replaced = declare_pattern(http, signed_in, a_mapping(weekend))

    # Every weekday moved, and no row from the first mapping survived to be merged with.
    assert set(replaced.values()) == {weekend}
    stored = pattern_rows(live_database_url, owner.tenant_id)
    assert len(stored) == 7
    assert {str(row.day_type_id) for row in stored} == {weekend}


def test_a_pattern_naming_a_day_type_this_tenant_does_not_have_is_refused(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    refused = http.put(WEEK_PATTERN, json=a_mapping(str(uuid4())), headers=signed_in)

    assert refused.status_code == ValidationFailed.status, refused.text
    assert [error["field"] for error in refused.json()["errors"]] == ["dayTypeId"]
    assert pattern_rows(live_database_url, owner.tenant_id) == []


def test_a_pattern_body_cannot_carry_a_cadence_either(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")

    refused = http.put(
        WEEK_PATTERN, json={**a_mapping(day_type), "cadence": "weekly"}, headers=signed_in
    )

    assert refused.status_code == ValidationFailed.status, refused.text


# --------------------------------------------------------------------------------
# What a mutation invalidates, and what it leaves alone
# --------------------------------------------------------------------------------


def test_a_pattern_edit_bumps_every_future_week_and_no_past_one(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    before = track_weeks(live_database_url, owner.tenant_id, PAST_WEEK, FUTURE_WEEK)

    declare_pattern(http, signed_in, a_mapping(day_type))

    after = week_versions(live_database_url, owner.tenant_id)
    assert after[str(FUTURE_WEEK)] == before[str(FUTURE_WEEK)] + 1
    # A past week's approved revision keeps the inputs it was computed with, so re-deriving it
    # would rewrite history rather than the plan.
    assert after[str(PAST_WEEK)] == before[str(PAST_WEEK)]


def test_a_pattern_edit_leaves_an_approved_past_week_untouched(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    approved = approve_a_revision(live_database_url, owner.tenant_id, PAST_WEEK)

    declare_pattern(http, signed_in, a_mapping(day_type))

    stored = stored_revisions(live_database_url, owner.tenant_id)
    # One revision, the same document, still approved: a pattern edit governs weeks the user has
    # not lived yet and rewrites nothing that was already agreed.
    assert stored == [
        {
            "id": approved["id"],
            "document": approved["document"],
            "status": APPROVED,
            "input_version": 1,
        }
    ]


def test_an_entry_added_to_a_mapped_shape_bumps_the_future_week(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    day_type = declare_day_type(http, signed_in, "Weekday")
    shape = declare_shape(http, signed_in, day_type, "Weekday shape")
    declare_pattern(http, signed_in, a_mapping(day_type))
    before = track_weeks(live_database_url, owner.tenant_id, FUTURE_WEEK)

    http.post(f"{TEMPLATES}/{shape}/entries", json=A_CONCRETE_ENTRY, headers=signed_in)

    after = week_versions(live_database_url, owner.tenant_id)
    assert after[str(FUTURE_WEEK)] == before[str(FUTURE_WEEK)] + 1


def test_a_shape_no_weekday_maps_bumps_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The control. A shape whose day type the pattern does not use changes no week, so a solve
    # running against that week's inputs is still reading current ones.
    mapped = declare_day_type(http, signed_in, "Weekday")
    unmapped = declare_day_type(http, signed_in, "Holiday")
    declare_pattern(http, signed_in, a_mapping(mapped))
    shape = declare_shape(http, signed_in, unmapped, "Holiday shape")
    before = track_weeks(live_database_url, owner.tenant_id, FUTURE_WEEK)

    http.post(f"{TEMPLATES}/{shape}/entries", json=A_CONCRETE_ENTRY, headers=signed_in)

    assert week_versions(live_database_url, owner.tenant_id) == before


def test_declaring_a_day_type_bumps_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    before = track_weeks(live_database_url, owner.tenant_id, FUTURE_WEEK)

    declare_day_type(http, signed_in, "Weekday")

    assert week_versions(live_database_url, owner.tenant_id) == before


# --------------------------------------------------------------------------------
# What the database refuses on its own
#
# Every rule above is stated at the boundary, and a value reaching these tables from a later
# migration or a psql session is not type-checked at all. These inserts bypass the boundary
# entirely, so what answers for them is the schema.
#
# The prerequisites are COMMITTED first and the offending row is added on its own, so the
# constraint under test is the only one that can refuse the statement.
# --------------------------------------------------------------------------------


def a_committed_shape(database_url: str, tenant_id: TenantId) -> tuple[UUID, UUID]:
    """A day type and its shape, committed, and their identifiers."""

    async def write() -> tuple[UUID, UUID]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                day_type = DayTypeRow(
                    id=uuid4(), tenant_id=tenant_id, name="Weekday", created_at=NOW
                )
                session.add(day_type)
                await session.flush()
                shape = TemplateRow(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    day_type_id=day_type.id,
                    name="Weekday shape",
                    created_at=NOW,
                )
                session.add(shape)
                return day_type.id, shape.id
        finally:
            await database.engine.dispose()

    return run(write())


def insert_directly(database_url: str, rows: Sequence[object]) -> str | None:
    """Add these rows in one statement batch, and answer with what refused them."""

    async def write() -> str | None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                session.add_all(list(rows))
                try:
                    await session.commit()
                except IntegrityError as refused:
                    return str(refused.orig)
                return None
        finally:
            await database.engine.dispose()

    return run(write())


def an_entry_row(tenant_id: TenantId, template_id: UUID, **overrides: Any) -> TemplateEntryRow:
    values: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "template_id": template_id,
        "kind": TemplateEntryKind.CONCRETE,
        "target_time": time(7, 0),
        "duration_minutes": 15,
        "flex_band_minutes": 0,
        "area_id": None,
        "binding_target": BindingTarget.ROUTINE,
        "binding_ref": uuid4(),
        **overrides,
    }
    return TemplateEntryRow(**values)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        (
            {"binding_ref": None, "binding_target": None},
            "ck_template_entries_kind_states_its_binding",
        ),
        (
            {
                "kind": TemplateEntryKind.SLOT,
                "area_id": None,
                "binding_target": None,
                "binding_ref": None,
            },
            "ck_template_entries_kind_states_its_binding",
        ),
        (
            {"kind": TemplateEntryKind.SLOT, "area_id": None},
            "ck_template_entries_kind_states_its_binding",
        ),
        ({"target_time": time(7, 5)}, "ck_template_entries_target_time_is_on_the_grid"),
        ({"duration_minutes": 50}, "ck_template_entries_duration_is_whole_steps_of_a_day"),
        ({"duration_minutes": 1455}, "ck_template_entries_duration_is_whole_steps_of_a_day"),
        ({"flex_band_minutes": 721}, "ck_template_entries_flex_band_shifts_within_a_day"),
    ],
    ids=[
        "a concrete entry with no binding",
        "a slot with no Area",
        "a slot carrying a binding",
        "a target time off the grid",
        "a duration that is not whole steps",
        "a duration longer than a day",
        "a band past half a day",
    ],
)
def test_the_schema_refuses_an_entry_the_boundary_would_have(
    owner: UserRecord,
    live_database_url: str,
    overrides: dict[str, Any],
    constraint: str,
) -> None:
    _, shape_id = a_committed_shape(live_database_url, owner.tenant_id)

    refused = insert_directly(
        live_database_url, [an_entry_row(owner.tenant_id, shape_id, **overrides)]
    )

    assert refused is not None, "the row was stored, so nothing but the boundary refuses it"
    assert constraint in refused


def test_the_schema_accepts_the_row_those_refusals_are_measured_against(
    owner: UserRecord, live_database_url: str
) -> None:
    # The control. Each rejection above changes one value of THIS row, so without it they could
    # all be passing on a row the schema would refuse for some other reason.
    _, shape_id = a_committed_shape(live_database_url, owner.tenant_id)

    assert insert_directly(live_database_url, [an_entry_row(owner.tenant_id, shape_id)]) is None


def test_the_schema_refuses_a_second_shape_for_one_day_type(
    owner: UserRecord, live_database_url: str
) -> None:
    # The boundary's 409 is a courtesy that states the reason; this index is the guarantee, and
    # it is what makes two callers racing unable to leave a day type with two shapes.
    day_type_id, _ = a_committed_shape(live_database_url, owner.tenant_id)

    refused = insert_directly(
        live_database_url,
        [
            TemplateRow(
                id=uuid4(),
                tenant_id=owner.tenant_id,
                day_type_id=day_type_id,
                name="Another shape",
                created_at=NOW,
            )
        ],
    )

    assert refused is not None
    assert "uq_templates_tenant_id_day_type_id" in refused


def test_the_schema_refuses_a_weekday_mapped_twice(
    owner: UserRecord, live_database_url: str
) -> None:
    # The pattern's primary key. Without it a weekday could hold two day types, and materializing
    # that date would have to choose between them.
    day_type_id, _ = a_committed_shape(live_database_url, owner.tenant_id)
    mapped = WeekPatternRow(
        tenant_id=owner.tenant_id, weekday=Weekday.MONDAY, day_type_id=day_type_id
    )
    assert insert_directly(live_database_url, [mapped]) is None

    refused = insert_directly(
        live_database_url,
        [
            WeekPatternRow(
                tenant_id=owner.tenant_id, weekday=Weekday.MONDAY, day_type_id=day_type_id
            )
        ],
    )

    assert refused is not None
    assert "pk_week_patterns" in refused


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
