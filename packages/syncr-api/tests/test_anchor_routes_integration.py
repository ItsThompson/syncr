"""The seven anchor and anchor-type routes end to end, against a real Postgres and a real request.

The unit suites prove the boundary rules and the matching. The integration suite proves the schema
and reconciliation. This proves what only a real request and a real database can:

- that a rejected anchor-type edit reaches the wire as a 422 naming the member to change, so the
  notice appears while the user is editing the type rather than at solve time;
- that the rendered `Lecture`, which has transit and no prep, is ACCEPTED over HTTP;
- that reordering re-evaluates existing commitments, in one request;
- that a retype persists on the series and answers with how many occurrences moved;
- that an override is distinguishable from a rule match in the response;
- that an anchor's payload names its source and states that it is read-only, and carries no
  location;
- that every anchor-type mutation bumps the week input version, because it regenerates shadows;
- and that another tenant's identifier is a 404 rather than a change.

Anchors are seeded through the reconciler rather than through a route, because there is no route
that creates one: that is the invariant, not a gap in the fixtures.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
`Secure`, and a client that honors that attribute will not send it back over `http://testserver`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.anchors.config import (
    ANCHOR_TYPES_PREFIX,
    ANCHORS_PREFIX,
    FORBIDS_AREAS,
    FORBIDS_EVERYTHING,
    FORBIDS_NOTHING,
    LEAD_MINUTES_MAX,
    RULE_MATCH,
    UNMATCHED,
    USER_OVERRIDE,
)
from syncr_api.anchors.reconcile import AnchorReconciler
from syncr_api.anchors.repository import AnchorRepository
from syncr_api.anchors.type_repository import AnchorTypeRepository
from syncr_api.calendars.config import CALENDAR_SOURCES_PREFIX, ICS
from syncr_api.calendars.events import FetchOutcome, RawEvent
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import Conflict, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_domain.intervals import Interval
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
ANCHORS = ANCHORS_PREFIX
TYPES = ANCHOR_TYPES_PREFIX
SOURCES = CALENDAR_SOURCES_PREFIX

ANOTHER_ID = "11111111-2222-3333-4444-555555555555"

TIMETABLE = "https://example.ac.uk/timetable.ics"
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

# The rendered types as request bodies, so the HTTP contract is exercised with the same figures the
# settled records show.
INTERVIEW_BODY: dict[str, Any] = {
    "name": "Interview",
    "matchTitleContains": "Interview",
    "prepLeadMinutes": 360,
    "prepDurationMinutes": 30,
    "transitLeadMinutes": 60,
    "transitDurationMinutes": 30,
    "returnTransitMinutes": 0,
    "postBufferMinutes": 75,
    "postScope": FORBIDS_NOTHING,
}
# `Pre 0m` with `Transit 30m` and a return leg. THE case the prep-collision rule must accept.
LECTURE_BODY: dict[str, Any] = {
    "name": "Lecture",
    "matchTitleContains": "Lecture",
    "prepDurationMinutes": 0,
    "transitDurationMinutes": 30,
    "returnTransitMinutes": 30,
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
    response = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": owner.email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    cookie = response.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def add_source(http: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = http.post(
        SOURCES,
        json={"provider": ICS, "displayName": "University timetable", "externalId": TIMETABLE},
        headers=headers,
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


def declare(http: TestClient, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    response = http.post(TYPES, json=body, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.text
    created: dict[str, Any] = response.json()
    return created


def an_event(
    uid: str,
    *,
    title: str,
    series_uid: str | None = None,
    start: datetime = NOW,
    minutes: int = 120,
) -> RawEvent:
    return RawEvent(
        uid=uid,
        series_uid=series_uid,
        title=title,
        interval=Interval(start, start + timedelta(minutes=minutes)),
        location="Lecture Theatre 3",
        sequence=0,
        all_day=False,
    )


def seed_anchors(
    database_url: str, tenant_id: TenantId, source_id: Any, events: Sequence[RawEvent]
) -> None:
    """Put commitments in the table the way a sync would, on a loop of this test's own.

    Through the reconciler rather than through a route, because there is no route that creates an
    anchor. That absence is invariant A1 rather than a gap in the fixtures.
    """

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                reconciler = AnchorReconciler(
                    AnchorRepository(session, tenant_id), AnchorTypeRepository(session, tenant_id)
                )
                await reconciler.reconcile(
                    _a_source(source_id, tenant_id),
                    FetchOutcome(events=tuple(events), events_read=len(events), reparsed=True),
                )
        finally:
            await database.engine.dispose()

    run(seed())


def _a_source(source_id: Any, tenant_id: TenantId) -> Any:
    from syncr_api.calendars.config import ANCHOR_SOURCE
    from syncr_api.calendars.records import (
        CalendarSourceRecord,
    )

    return CalendarSourceRecord(
        id=source_id,
        tenant_id=tenant_id,
        provider=ICS,
        role=ANCHOR_SOURCE,
        display_name="University timetable",
        external_id=TIMETABLE,
        included=True,
        horizon_days=None,
    )


def track_this_week(database_url: str, tenant_id: TenantId) -> int:
    """Create the current week's input-version row and answer its value.

    A week nobody has touched has NO row, and the counter deliberately skips an untracked week: it
    has no plan and no running solve to invalidate. So a test that asserts a bump has to give the
    week something to bump.
    """

    async def create() -> int:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                versions = WeekInputVersionRepository(session, tenant_id)
                return await versions.bump(IsoWeek.containing(datetime.now(UTC).date()), at=NOW)
        finally:
            await database.engine.dispose()

    return run(create())


def week_version(database_url: str, tenant_id: TenantId) -> int | None:
    async def read() -> int | None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                versions = WeekInputVersionRepository(session, tenant_id)
                return await versions.current(IsoWeek.containing(datetime.now(UTC).date()))
        finally:
            await database.engine.dispose()

    return run(read())


# --------------------------------------------------------------------------------
# Declaring a type, and the boundary rules on the wire
# --------------------------------------------------------------------------------


def test_the_rendered_lecture_with_transit_and_no_prep_is_accepted(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The guard on a non-zero prep duration, over HTTP. Without it this request is a 422 and the
    # type `screens.html` renders cannot be declared at all.
    created = declare(http, signed_in, LECTURE_BODY)

    assert created["prepDurationMinutes"] == 0
    assert created["transitDurationMinutes"] == 30
    assert created["casts"] == {
        "prep": False,
        "outboundTransit": True,
        "returnTransit": True,
        "recovery": False,
    }


def test_a_transit_lead_shorter_than_its_journey_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.post(
        TYPES,
        json={"name": "Late", "transitLeadMinutes": 20, "transitDurationMinutes": 30},
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status
    body = response.json()
    assert [error["field"] for error in body["errors"]] == ["transitLeadMinutes"]
    assert "still be travelling" in body["detail"]


def test_a_prep_lead_colliding_with_transit_is_a_422_naming_the_member(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The notice the error matrix calls for: inline on the anchor type, in amber, naming which
    # member to change. On the wire that is a field-level 422 rather than a solve-time surprise.
    response = http.post(
        TYPES,
        json={
            "name": "Colliding",
            "prepLeadMinutes": 60,
            "prepDurationMinutes": 30,
            "transitLeadMinutes": 60,
            "transitDurationMinutes": 30,
        },
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status
    body = response.json()
    assert [error["field"] for error in body["errors"]] == ["prepLeadMinutes"]
    assert "90" in body["detail"]


def test_the_scope_and_its_areas_have_to_agree_on_the_wire(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    empty = http.post(
        TYPES,
        json={"name": "Empty areas", "postBufferMinutes": 75, "postScope": FORBIDS_AREAS},
        headers=signed_in,
    )
    populated = http.post(
        TYPES,
        json={
            "name": "Populated everything",
            "postBufferMinutes": 75,
            "postScope": FORBIDS_EVERYTHING,
            "forbiddenAreaIds": [ANOTHER_ID],
        },
        headers=signed_in,
    )

    for response in (empty, populated):
        assert response.status_code == ValidationFailed.status, response.text
        assert [error["field"] for error in response.json()["errors"]] == ["forbiddenAreaIds"]


def test_a_scope_that_forbids_everything_needs_no_areas_at_all(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The member this spec introduced. `areas` cannot express genuine unavailability without
    # listing every Area, which stops being correct the moment a new one is declared.
    created = declare(
        http,
        signed_in,
        {"name": "General anaesthetic", "postBufferMinutes": 240, "postScope": FORBIDS_EVERYTHING},
    )

    assert created["postScope"] == FORBIDS_EVERYTHING
    assert created["forbiddenAreaIds"] == []
    assert created["casts"]["recovery"] is True


def test_a_forbidden_area_this_tenant_has_not_declared_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.post(
        TYPES,
        json={
            "name": "Unknown area",
            "postBufferMinutes": 75,
            "postScope": FORBIDS_AREAS,
            "forbiddenAreaIds": [ANOTHER_ID],
        },
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status
    assert [error["field"] for error in response.json()["errors"]] == ["forbiddenAreaIds"]


def test_a_match_rule_naming_an_unknown_source_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.post(
        TYPES, json={"name": "Scoped", "matchSourceId": ANOTHER_ID}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status
    assert [error["field"] for error in response.json()["errors"]] == ["matchSourceId"]


def test_a_match_rule_naming_a_source_this_tenant_has_is_accepted(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    source = add_source(http, signed_in)

    created = declare(http, signed_in, {**LECTURE_BODY, "matchSourceId": source["id"]})

    assert created["matchSourceId"] == source["id"]


def test_a_name_another_type_holds_is_a_stated_409(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    declare(http, signed_in, LECTURE_BODY)

    response = http.post(TYPES, json=LECTURE_BODY, headers=signed_in)

    assert response.status_code == Conflict.status
    assert "name" in response.json()["detail"]


def test_a_lead_past_the_bound_is_refused_by_the_schema(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # A week is the ceiling, because the week assembler expands its anchor read backwards by the
    # largest lead any type declares.
    response = http.post(
        TYPES,
        json={"name": "Absurd", "prepLeadMinutes": LEAD_MINUTES_MAX + 1, "prepDurationMinutes": 5},
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status


def test_an_unknown_field_on_a_type_is_refused(http: TestClient, signed_in: dict[str, str]) -> None:
    # `ruleOrder` is not a member of either request shape: position is appended on create and
    # rewritten wholly by the reorder route.
    response = http.post(TYPES, json={**LECTURE_BODY, "ruleOrder": 0}, headers=signed_in)

    assert response.status_code == ValidationFailed.status


# --------------------------------------------------------------------------------
# Editing, ordering, and removing
# --------------------------------------------------------------------------------


def test_a_type_is_appended_to_the_end_of_the_evaluation_order(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # A new rule must not silently outrank rules the user already ordered.
    first = declare(http, signed_in, LECTURE_BODY)
    second = declare(http, signed_in, INTERVIEW_BODY)

    listed = http.get(TYPES, headers=signed_in).json()["anchorTypes"]

    assert [row["id"] for row in listed] == [first["id"], second["id"]]
    assert [row["ruleOrder"] for row in listed] == [0, 1]


def test_a_patch_that_would_collide_is_refused_and_changes_nothing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The merged specification is what the rules see, so lowering a stored prep lead is caught as
    # the same collision as declaring one.
    created = declare(http, signed_in, INTERVIEW_BODY)

    response = http.patch(
        f"{TYPES}/{created['id']}", json={"prepLeadMinutes": 30}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status
    assert [error["field"] for error in response.json()["errors"]] == ["prepLeadMinutes"]
    unchanged = http.get(f"{TYPES}/{created['id']}", headers=signed_in).json()
    assert unchanged["prepLeadMinutes"] == INTERVIEW_BODY["prepLeadMinutes"]


def test_a_null_transit_lead_restores_the_abutting_default(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The reason the patch shape keeps null and absent apart. Null here means "leave exactly late
    # enough to arrive on time", and omitting the field keeps whatever lead is stored.
    created = declare(http, signed_in, LECTURE_BODY | {"transitLeadMinutes": 90})
    assert created["transitLeadMinutes"] == 90

    cleared = http.patch(
        f"{TYPES}/{created['id']}", json={"transitLeadMinutes": None}, headers=signed_in
    )

    assert cleared.status_code == HTTPStatus.OK, cleared.text
    assert cleared.json()["transitLeadMinutes"] is None


def test_a_null_on_a_field_with_nothing_to_clear_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = declare(http, signed_in, LECTURE_BODY)

    response = http.patch(f"{TYPES}/{created['id']}", json={"name": None}, headers=signed_in)

    assert response.status_code == ValidationFailed.status


def test_reordering_rewrites_the_whole_order(http: TestClient, signed_in: dict[str, str]) -> None:
    first = declare(http, signed_in, LECTURE_BODY)
    second = declare(http, signed_in, INTERVIEW_BODY)

    response = http.put(
        f"{TYPES}/order",
        json={"anchorTypeIds": [second["id"], first["id"]]},
        headers=signed_in,
    )

    assert response.status_code == HTTPStatus.OK, response.text
    assert [row["id"] for row in response.json()["anchorTypes"]] == [second["id"], first["id"]]
    assert [row["ruleOrder"] for row in response.json()["anchorTypes"]] == [0, 1]


def test_a_partial_order_is_refused_and_changes_nothing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    first = declare(http, signed_in, LECTURE_BODY)
    declare(http, signed_in, INTERVIEW_BODY)

    response = http.put(f"{TYPES}/order", json={"anchorTypeIds": [first["id"]]}, headers=signed_in)

    assert response.status_code == ValidationFailed.status
    assert [error["field"] for error in response.json()["errors"]] == ["anchorTypeIds"]
    listed = http.get(TYPES, headers=signed_in).json()["anchorTypes"]
    assert [row["ruleOrder"] for row in listed] == [0, 1]


def test_the_order_route_is_not_read_as_an_identifier(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # `/order` is declared before `/{anchor_type_id}`, and the framework matches in declaration
    # order. Reversed, the reorder route would answer 422 on the path parameter.
    declare(http, signed_in, LECTURE_BODY)

    response = http.put(f"{TYPES}/order", json={"anchorTypeIds": []}, headers=signed_in)

    assert response.status_code == ValidationFailed.status
    assert [error["field"] for error in response.json()["errors"]] == ["anchorTypeIds"]


def test_removing_a_type_is_a_204_and_it_is_then_gone(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    created = declare(http, signed_in, LECTURE_BODY)

    removed = http.delete(f"{TYPES}/{created['id']}", headers=signed_in)

    assert removed.status_code == HTTPStatus.NO_CONTENT
    assert removed.content == b""
    assert http.get(f"{TYPES}/{created['id']}", headers=signed_in).status_code == NotFound.status


def test_another_tenants_type_identifier_is_a_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    for response in (
        http.get(f"{TYPES}/{ANOTHER_ID}", headers=signed_in),
        http.patch(f"{TYPES}/{ANOTHER_ID}", json={"name": "Mine"}, headers=signed_in),
        http.delete(f"{TYPES}/{ANOTHER_ID}", headers=signed_in),
    ):
        assert response.status_code == NotFound.status, response.text


# --------------------------------------------------------------------------------
# Reading commitments, and retyping one
# --------------------------------------------------------------------------------


def test_a_commitments_payload_names_its_source_and_states_it_is_read_only(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    source = add_source(http, signed_in)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [an_event("l@example.ac.uk", title="Systems Lecture")],
    )

    listed = http.get(
        ANCHORS,
        params={"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()},
        headers=signed_in,
    )

    assert listed.status_code == HTTPStatus.OK, listed.text
    [anchor] = listed.json()["anchors"]
    assert anchor["readOnly"] is True
    assert anchor["sourceName"] == "University timetable"
    assert "University timetable" in anchor["readOnlyStatement"]
    assert "read-only" in anchor["readOnlyStatement"]
    assert "location" not in anchor
    assert "Lecture Theatre 3" not in listed.text


def test_an_untyped_commitment_casts_no_shadow_of_any_kind(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    source = add_source(http, signed_in)
    declare(http, signed_in, LECTURE_BODY)
    seed_anchors(
        live_database_url, owner.tenant_id, source["id"], [an_event("d@example", title="Dentist")]
    )

    [anchor] = http.get(
        ANCHORS,
        params={"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()},
        headers=signed_in,
    ).json()["anchors"]

    assert anchor["anchorTypeId"] is None
    assert anchor["typeSource"] == UNMATCHED
    assert anchor["casts"] == {
        "prep": False,
        "outboundTransit": False,
        "returnTransit": False,
        "recovery": False,
    }


def test_the_matched_type_is_shown_on_the_commitment(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    source = add_source(http, signed_in)
    lecture = declare(http, signed_in, LECTURE_BODY)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [an_event("l@example", title="Systems Lecture")],
    )

    [anchor] = http.get(
        ANCHORS,
        params={"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()},
        headers=signed_in,
    ).json()["anchors"]

    assert anchor["anchorTypeId"] == lecture["id"]
    assert anchor["anchorTypeName"] == "Lecture"
    assert anchor["typeSource"] == RULE_MATCH
    assert anchor["casts"]["outboundTransit"] is True


def test_a_retype_persists_on_the_series_and_reports_how_many_moved(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    source = add_source(http, signed_in)
    interview = declare(http, signed_in, INTERVIEW_BODY)
    occurrences = [
        an_event(
            f"standup@example#{day}",
            title="Daily standup",
            series_uid="standup@example",
            start=NOW + timedelta(days=day),
            minutes=15,
        )
        for day in range(5)
    ]
    seed_anchors(live_database_url, owner.tenant_id, source["id"], occurrences)
    listed = http.get(
        ANCHORS,
        params={"from": NOW.isoformat(), "to": (NOW + timedelta(days=7)).isoformat()},
        headers=signed_in,
    ).json()["anchors"]

    retyped = http.put(
        f"{ANCHORS}/{listed[0]['id']}/type",
        json={"anchorTypeId": interview["id"]},
        headers=signed_in,
    )

    assert retyped.status_code == HTTPStatus.OK, retyped.text
    body = retyped.json()
    assert body["occurrencesRetyped"] == len(occurrences)
    assert body["anchor"]["typeSource"] == USER_OVERRIDE
    after = http.get(
        ANCHORS,
        params={"from": NOW.isoformat(), "to": (NOW + timedelta(days=7)).isoformat()},
        headers=signed_in,
    ).json()["anchors"]
    assert {anchor["anchorTypeId"] for anchor in after} == {interview["id"]}
    assert {anchor["typeSource"] for anchor in after} == {USER_OVERRIDE}


def test_an_override_is_distinguishable_from_a_rule_match(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    source = add_source(http, signed_in)
    lecture = declare(http, signed_in, LECTURE_BODY)
    interview = declare(http, signed_in, INTERVIEW_BODY)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [
            an_event("matched@example", title="Systems Lecture"),
            an_event("overridden@example", title="Maths Lecture", start=NOW + timedelta(hours=4)),
        ],
    )
    span = {"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()}
    listed = http.get(ANCHORS, params=span, headers=signed_in).json()["anchors"]
    overridden = next(row for row in listed if row["title"] == "Maths Lecture")

    http.put(
        f"{ANCHORS}/{overridden['id']}/type",
        json={"anchorTypeId": interview["id"]},
        headers=signed_in,
    )

    listed_after = http.get(ANCHORS, params=span, headers=signed_in).json()["anchors"]
    after = {row["title"]: row for row in listed_after}
    assert after["Systems Lecture"]["typeSource"] == RULE_MATCH
    assert after["Systems Lecture"]["anchorTypeId"] == lecture["id"]
    assert after["Maths Lecture"]["typeSource"] == USER_OVERRIDE
    assert after["Maths Lecture"]["anchorTypeId"] == interview["id"]


def test_a_retype_to_no_type_at_all_is_still_an_override(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # "This is not a lecture" is a decision, and a later rule match must not undo it.
    source = add_source(http, signed_in)
    declare(http, signed_in, LECTURE_BODY)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [an_event("l@example", title="Systems Lecture")],
    )
    span = {"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()}
    [anchor] = http.get(ANCHORS, params=span, headers=signed_in).json()["anchors"]

    cleared = http.put(
        f"{ANCHORS}/{anchor['id']}/type", json={"anchorTypeId": None}, headers=signed_in
    )

    assert cleared.status_code == HTTPStatus.OK, cleared.text
    assert cleared.json()["anchor"]["anchorTypeId"] is None
    assert cleared.json()["anchor"]["typeSource"] == USER_OVERRIDE


def test_retyping_to_a_type_this_tenant_does_not_have_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    source = add_source(http, signed_in)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [an_event("l@example", title="Systems Lecture")],
    )
    span = {"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()}
    [anchor] = http.get(ANCHORS, params=span, headers=signed_in).json()["anchors"]

    response = http.put(
        f"{ANCHORS}/{anchor['id']}/type", json={"anchorTypeId": ANOTHER_ID}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status
    assert [error["field"] for error in response.json()["errors"]] == ["anchorTypeId"]


def test_reordering_re_evaluates_existing_commitments_in_one_request(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    source = add_source(http, signed_in)
    broad = declare(http, signed_in, {"name": "Anything"})
    narrow = declare(http, signed_in, LECTURE_BODY)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [an_event("l@example", title="Systems Lecture")],
    )
    span = {"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()}
    [before] = http.get(ANCHORS, params=span, headers=signed_in).json()["anchors"]
    assert before["anchorTypeId"] == broad["id"]

    http.put(
        f"{TYPES}/order", json={"anchorTypeIds": [narrow["id"], broad["id"]]}, headers=signed_in
    )

    [after] = http.get(ANCHORS, params=span, headers=signed_in).json()["anchors"]
    assert after["anchorTypeId"] == narrow["id"]
    assert after["anchorTypeName"] == "Lecture"


def test_another_tenants_anchor_identifier_is_a_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    for response in (
        http.get(f"{ANCHORS}/{ANOTHER_ID}", headers=signed_in),
        http.put(f"{ANCHORS}/{ANOTHER_ID}/type", json={"anchorTypeId": None}, headers=signed_in),
    ):
        assert response.status_code == NotFound.status, response.text


# --------------------------------------------------------------------------------
# The span, the page, and the input-version bump
# --------------------------------------------------------------------------------


def test_a_span_that_covers_nothing_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(
        ANCHORS, params={"from": NOW.isoformat(), "to": NOW.isoformat()}, headers=signed_in
    )

    assert response.status_code == ValidationFailed.status
    assert [error["field"] for error in response.json()["errors"]] == ["to"]


def test_a_span_with_no_bounds_at_all_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Both bounds are required. A read of "every commitment ever" is not a question the interface
    # asks, and answering it would make one request's cost a function of how many years of
    # timetable a publisher chose to feed.
    response = http.get(ANCHORS, headers=signed_in)

    assert response.status_code == ValidationFailed.status


def test_a_page_hands_back_a_cursor_that_reaches_the_rest(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    source = add_source(http, signed_in)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [
            an_event(f"a{index}@example", title="Lecture", start=NOW + timedelta(hours=index))
            for index in range(5)
        ],
    )
    span = {"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()}

    first = http.get(ANCHORS, params={**span, "limit": 2}, headers=signed_in).json()
    second = http.get(
        ANCHORS, params={**span, "limit": 2, "cursor": first["nextCursor"]}, headers=signed_in
    ).json()
    third = http.get(
        ANCHORS, params={**span, "limit": 2, "cursor": second["nextCursor"]}, headers=signed_in
    ).json()

    walked = [row["id"] for page in (first, second, third) for row in page["anchors"]]
    assert len(walked) == 5
    assert len(set(walked)) == 5
    assert third["nextCursor"] is None


def test_a_cursor_this_api_did_not_produce_is_a_stated_422(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    response = http.get(
        ANCHORS,
        params={
            "from": NOW.isoformat(),
            "to": (NOW + timedelta(days=1)).isoformat(),
            "cursor": "not-a-cursor",
        },
        headers=signed_in,
    )

    assert response.status_code == ValidationFailed.status
    assert [error["field"] for error in response.json()["errors"]] == ["cursor"]


@pytest.mark.parametrize(
    "mutation",
    ["declare", "patch", "reorder", "remove", "retype"],
)
def test_every_anchor_type_mutation_bumps_the_week_input_version(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    mutation: str,
) -> None:
    # A type declares the prep, transit, and recovery every commitment of it casts, so any change
    # to the rule set regenerates shadows, which are solve inputs. A retype does the same, because
    # it changes which type a commitment carries.
    source = add_source(http, signed_in)
    created = declare(http, signed_in, LECTURE_BODY)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [an_event("l@example", title="Systems Lecture")],
    )
    before = track_this_week(live_database_url, owner.tenant_id)

    if mutation == "declare":
        declare(http, signed_in, INTERVIEW_BODY)
    elif mutation == "patch":
        http.patch(f"{TYPES}/{created['id']}", json={"postBufferMinutes": 30}, headers=signed_in)
    elif mutation == "reorder":
        http.put(f"{TYPES}/order", json={"anchorTypeIds": [created["id"]]}, headers=signed_in)
    elif mutation == "remove":
        http.delete(f"{TYPES}/{created['id']}", headers=signed_in)
    else:
        span = {"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()}
        [anchor] = http.get(ANCHORS, params=span, headers=signed_in).json()["anchors"]
        http.put(f"{ANCHORS}/{anchor['id']}/type", json={"anchorTypeId": None}, headers=signed_in)

    assert week_version(live_database_url, owner.tenant_id) == before + 1


def test_reading_commitments_and_types_bumps_nothing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The control for the bump above. Without it, "every mutation bumps" passes on an
    # implementation that bumps on every request, and the solver would be superseded by a read.
    source = add_source(http, signed_in)
    declare(http, signed_in, LECTURE_BODY)
    seed_anchors(
        live_database_url,
        owner.tenant_id,
        source["id"],
        [an_event("l@example", title="Systems Lecture")],
    )
    before = track_this_week(live_database_url, owner.tenant_id)

    http.get(TYPES, headers=signed_in)
    http.get(
        ANCHORS,
        params={"from": NOW.isoformat(), "to": (NOW + timedelta(days=1)).isoformat()},
        headers=signed_in,
    )

    assert week_version(live_database_url, owner.tenant_id) == before
