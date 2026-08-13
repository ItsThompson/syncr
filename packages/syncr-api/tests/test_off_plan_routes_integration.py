"""The four off-plan routes end to end, against a real Postgres and a real request.

The service suite proves the rules with fakes. This proves what only a real request and a real
database can: that the wire shape is camelCase and half-open, that a refused declaration is not
stored, that a retried unsafe request sent under one key is applied once, that another tenant's
identifier is a 404 rather than an edit, and that the budget report over an off-plan week says so.

The two tests worth reading are ``test_a_span_beginning_where_another_ends_is_accepted``, which is
the half-open reading at the one boundary a user will really hit, and
``test_a_week_declared_off_plan_end_to_end_reports_no_discretionary_time``, which is the whole
point of the entity: a holiday must not read as every Area starving.

The cookie is replayed by setting the header rather than through a cookie jar: the cookie is
``Secure``, and an HTTP client that honors that attribute will not send it back over
``http://testserver``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.budgets.config import BUDGET_PREFIX, PERIOD_PARAMETER
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import PROBLEM_JSON_MEDIA_TYPE, Conflict, NotFound, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.idempotency.config import IDEMPOTENCY_KEY_HEADER
from syncr_api.offplan.config import LABEL_MAX_LENGTH, OFF_PLAN_PREFIX
from syncr_api.offplan.models import OffPlanPeriodRow
from syncr_api.offplan.reading import WHOLE_WEEK_STATEMENT
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.user_settings.config import SETTINGS_PREFIX
from syncr_domain.fixtures.off_plan_week import LONDON, OFF_PLAN_WEEK
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId
    from syncr_domain.weeks import IsoWeek

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]
OFF_PLAN = OFF_PLAN_PREFIX

# The fixture's own span, on the wire: Friday 14:00 to Monday 09:00 over the week the clocks go
# back, which is two ISO weeks and a daylight-saving transition in one declaration.
FRIDAY_TO_MONDAY = {
    "start": OFF_PLAN_WEEK.off_plan.start.isoformat().replace("+00:00", "Z"),
    "end": OFF_PLAN_WEEK.off_plan.end.isoformat().replace("+00:00", "Z"),
}
WEEK = str(OFF_PLAN_WEEK.iso_week)
FOLLOWING_WEEK = str(OFF_PLAN_WEEK.following_week)


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


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    """The headers a signed-in browser sends, for a tenant whose home zone is a real one.

    The zone is set through the settings route rather than assumed, because the default is ``UTC``
    and every figure the off-plan fixture states is a London figure: 2026-W43 is 169 hours there
    and the clocks go back inside the Friday-to-Monday span. Under ``UTC`` the week would be an
    ordinary 168 hours and the transition the fixture exists to exercise would not happen.
    """
    headers = _sign_in(http, owner.email)
    answered = http.patch(SETTINGS_PREFIX, json={"homeZone": LONDON}, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
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


def period_rows(database_url: str, tenant_id: TenantId) -> list[OffPlanPeriodRow]:
    """The tenant's off-plan rows, read on a connection of this test's own."""

    async def read() -> list[OffPlanPeriodRow]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(OffPlanPeriodRow)
                    .where(OffPlanPeriodRow.tenant_id == tenant_id)
                    .order_by(OffPlanPeriodRow.start)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def declare(http: TestClient, headers: dict[str, str], **body: Any) -> tuple[int, dict[str, Any]]:
    answered = http.post(OFF_PLAN, json={**FRIDAY_TO_MONDAY, **body}, headers=headers)
    return answered.status_code, answered.json()


def shifted(days: int, *, hours: int = 0) -> dict[str, str]:
    """The fixture's span moved by whole days, so it stays on the quarter-hour grid."""
    moved = timedelta(days=days, hours=hours)
    return {
        "start": (OFF_PLAN_WEEK.off_plan.start + moved).isoformat().replace("+00:00", "Z"),
        "end": (OFF_PLAN_WEEK.off_plan.end + moved).isoformat().replace("+00:00", "Z"),
    }


def budget(http: TestClient, headers: dict[str, str], period: str) -> dict[str, Any]:
    answered = http.get(BUDGET_PREFIX, params={PERIOD_PARAMETER: period}, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    body: dict[str, Any] = answered.json()
    return body


def track(database_url: str, tenant_id: TenantId, *weeks: IsoWeek) -> None:
    """Give each week an input-version row, so a bump has something to increment.

    A week with no row is not tracked, because it has no plan and no running solve to invalidate,
    so a test that reads a bump has to put the row there first.
    """

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


# --------------------------------------------------------------------------------
# Declaring, reading, changing, removing
# --------------------------------------------------------------------------------


def test_a_declared_span_reaches_the_wire_as_two_instants(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    status, created = declare(http, signed_in, keepFrame=True, label="Italy")

    assert status == HTTPStatus.CREATED, created
    assert created["start"] == FRIDAY_TO_MONDAY["start"]
    assert created["end"] == FRIDAY_TO_MONDAY["end"]
    assert created["keepFrame"] is True
    assert created["label"] == "Italy"
    # One row, holding the instants the request named.
    stored = period_rows(live_database_url, owner.tenant_id)
    assert [(row.start, row.end, row.keep_frame) for row in stored] == [
        (OFF_PLAN_WEEK.off_plan.start, OFF_PLAN_WEEK.off_plan.end, True)
    ]


def test_the_frame_is_dropped_unless_the_declaration_keeps_it(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    status, created = declare(http, signed_in)

    assert status == HTTPStatus.CREATED
    assert created["keepFrame"] is False
    assert created["label"] is None


def test_the_periods_are_listed_earliest_first(http: TestClient, signed_in: dict[str, str]) -> None:
    declare(http, signed_in, **shifted(14))
    declare(http, signed_in)

    answered = http.get(OFF_PLAN, headers=signed_in)

    assert answered.status_code == HTTPStatus.OK
    assert [period["start"] for period in answered.json()["periods"]] == [
        FRIDAY_TO_MONDAY["start"],
        shifted(14)["start"],
    ]


def test_one_period_is_read_by_its_identifier(http: TestClient, signed_in: dict[str, str]) -> None:
    _, created = declare(http, signed_in, label="Italy")

    answered = http.get(f"{OFF_PLAN}/{created['id']}", headers=signed_in)

    assert answered.status_code == HTTPStatus.OK
    assert answered.json() == created


def test_a_bound_may_be_moved_on_its_own(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    _, created = declare(http, signed_in)
    earlier = (OFF_PLAN_WEEK.off_plan.end - timedelta(days=1)).isoformat().replace("+00:00", "Z")

    answered = http.patch(f"{OFF_PLAN}/{created['id']}", json={"end": earlier}, headers=signed_in)

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert answered.json()["end"] == earlier
    assert answered.json()["start"] == FRIDAY_TO_MONDAY["start"]
    assert [row.end for row in period_rows(live_database_url, owner.tenant_id)] == [
        OFF_PLAN_WEEK.off_plan.end - timedelta(days=1)
    ]


def test_keep_frame_is_editable_after_the_period_is_declared(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    _, created = declare(http, signed_in, keepFrame=False)

    answered = http.patch(
        f"{OFF_PLAN}/{created['id']}", json={"keepFrame": True}, headers=signed_in
    )

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert answered.json()["keepFrame"] is True
    assert [row.keep_frame for row in period_rows(live_database_url, owner.tenant_id)] == [True]


def test_a_label_is_cleared_by_an_explicit_null(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    _, created = declare(http, signed_in, label="Italy")

    answered = http.patch(f"{OFF_PLAN}/{created['id']}", json={"label": None}, headers=signed_in)

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert answered.json()["label"] is None
    assert [row.label for row in period_rows(live_database_url, owner.tenant_id)] == [None]


def test_removing_a_period_leaves_nothing_behind(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    _, created = declare(http, signed_in)

    removed = http.delete(f"{OFF_PLAN}/{created['id']}", headers=signed_in)

    assert removed.status_code == HTTPStatus.NO_CONTENT
    assert removed.content == b""
    assert period_rows(live_database_url, owner.tenant_id) == []
    # And it is gone rather than hidden: the same identifier now answers 404.
    assert (
        http.get(f"{OFF_PLAN}/{created['id']}", headers=signed_in).status_code
        == HTTPStatus.NOT_FOUND
    )


# --------------------------------------------------------------------------------
# The boundaries
# --------------------------------------------------------------------------------


def test_a_span_beginning_where_another_ends_is_accepted(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The half-open reading through HTTP: back on plan at 09:00 on the Monday, and off again from
    # 09:00 the same morning. Both are stored, because they cover no common instant.
    declare(http, signed_in)
    abutting = {
        "start": FRIDAY_TO_MONDAY["end"],
        "end": (OFF_PLAN_WEEK.off_plan.end + timedelta(hours=8)).isoformat().replace("+00:00", "Z"),
    }

    answered = http.post(OFF_PLAN, json=abutting, headers=signed_in)

    assert answered.status_code == HTTPStatus.CREATED, answered.text
    assert len(period_rows(live_database_url, owner.tenant_id)) == 2


def test_a_span_overlapping_one_already_declared_is_a_409_that_says_why(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    declare(http, signed_in)

    answered = http.post(OFF_PLAN, json=shifted(0, hours=1), headers=signed_in)

    assert answered.status_code == Conflict.status
    assert answered.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    problem = answered.json()
    assert problem["type"] == Conflict.type
    assert "overlaps" in problem["detail"]
    assert "adjacency is not overlap" in problem["detail"]
    # The refused declaration was not stored.
    assert len(period_rows(live_database_url, owner.tenant_id)) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"start": "2026-10-23T14:05:00Z"},
        {"end": "2026-10-26T09:07:00Z"},
    ],
    ids=["start_off_the_grid", "end_off_the_grid"],
)
def test_a_bound_off_the_quarter_hour_is_a_422(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    body: dict[str, str],
) -> None:
    status, problem = declare(http, signed_in, **body)

    assert status == ValidationFailed.status
    assert "quarter hour" in problem["detail"]
    assert period_rows(live_database_url, owner.tenant_id) == []


def test_a_span_that_runs_backwards_is_a_422(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    status, problem = declare(
        http, signed_in, start=FRIDAY_TO_MONDAY["end"], end=FRIDAY_TO_MONDAY["start"]
    )

    assert status == ValidationFailed.status
    assert "runs forward" in problem["detail"]
    assert period_rows(live_database_url, owner.tenant_id) == []


def test_an_unknown_field_is_refused_rather_than_dropped(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    status, problem = declare(http, signed_in, keepframe=True)

    assert status == ValidationFailed.status
    assert problem["type"] == ValidationFailed.type


def test_a_bound_sent_as_null_on_a_patch_is_refused(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # An omitted bound means "leave it alone" and there is nothing for a null to clear, so the two
    # intentions are kept apart rather than collapsed.
    _, created = declare(http, signed_in)

    answered = http.patch(f"{OFF_PLAN}/{created['id']}", json={"end": None}, headers=signed_in)

    assert answered.status_code == ValidationFailed.status


def test_a_retried_declaration_replays_rather_than_declaring_a_second_period(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # Without the guard the retry would be refused as an overlap, which is the wrong answer to a
    # request that already succeeded.
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: str(uuid4())}

    first = http.post(OFF_PLAN, json=FRIDAY_TO_MONDAY, headers=keyed)
    second = http.post(OFF_PLAN, json=FRIDAY_TO_MONDAY, headers=keyed)

    assert first.status_code == HTTPStatus.CREATED, first.text
    assert second.status_code == HTTPStatus.CREATED, second.text
    assert second.json() == first.json()
    assert len(period_rows(live_database_url, owner.tenant_id)) == 1


def test_a_retried_patch_replays_rather_than_bumping_the_weeks_again(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # A rename converges: sent twice it leaves the same row either way, so an assertion on the
    # response alone could not tell a replay from a second execution and would be decoration.
    # What separates them is the input version of each week the span touches, which every
    # mutation of a period bumps and which is the figure a running solve's write compares.
    _, created = declare(http, signed_in)
    track(live_database_url, owner.tenant_id, OFF_PLAN_WEEK.iso_week, OFF_PLAN_WEEK.following_week)
    before = [
        input_version(live_database_url, owner.tenant_id, week)
        for week in (OFF_PLAN_WEEK.iso_week, OFF_PLAN_WEEK.following_week)
    ]
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: str(uuid4())}
    renamed = {"label": "Italy"}

    first = http.patch(f"{OFF_PLAN}/{created['id']}", json=renamed, headers=keyed)
    second = http.patch(f"{OFF_PLAN}/{created['id']}", json=renamed, headers=keyed)

    # Both weeks, because the span crosses an ISO week boundary and a second execution would
    # invalidate each of them twice.
    assert [
        input_version(live_database_url, owner.tenant_id, week)
        for week in (OFF_PLAN_WEEK.iso_week, OFF_PLAN_WEEK.following_week)
    ] == [(counted or 0) + 1 for counted in before]
    assert first.status_code == HTTPStatus.OK, first.text
    assert second.status_code == HTTPStatus.OK, second.text
    assert second.json() == first.json()


def test_a_retried_removal_replays_the_stored_answer_rather_than_404ing(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The row is gone once the first removal commits, so re-running the work answers 404: a client
    # that resends a request it never saw the answer to is told the time off it just removed does
    # not exist. The replay answers the stored 204 instead, and carries no body.
    _, created = declare(http, signed_in)
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: str(uuid4())}

    first = http.delete(f"{OFF_PLAN}/{created['id']}", headers=keyed)
    second = http.delete(f"{OFF_PLAN}/{created['id']}", headers=keyed)

    assert second.status_code == HTTPStatus.NO_CONTENT, second.text
    assert second.content == b""
    assert first.status_code == HTTPStatus.NO_CONTENT, first.text
    assert period_rows(live_database_url, owner.tenant_id) == []


def test_a_repeated_removal_without_a_key_still_answers_404(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # The control for the replay above, and the reading that says the 404 is the route's real
    # behavior rather than something the test constructed. It is also the control on the
    # offered-not-demanded rule for this module's two new guards.
    _, created = declare(http, signed_in)

    first = http.delete(f"{OFF_PLAN}/{created['id']}", headers=signed_in)
    second = http.delete(f"{OFF_PLAN}/{created['id']}", headers=signed_in)

    assert first.status_code == HTTPStatus.NO_CONTENT
    assert second.status_code == NotFound.status, second.text


@pytest.mark.parametrize(
    ("span", "named"),
    [
        ({"start": "2026-10-23T13:00:00", "end": "2026-10-26T09:00:00Z"}, {"body.start"}),
        ({"start": "2026-10-23T13:00:00Z", "end": "2026-10-26T09:00:00"}, {"body.end"}),
        ({"start": "2026-10-23", "end": "2026-10-26"}, {"body.start", "body.end"}),
    ],
    ids=["naive_start", "naive_end", "date_only"],
)
def test_a_bound_that_names_no_instant_is_refused(
    http: TestClient,
    signed_in: dict[str, str],
    owner: UserRecord,
    live_database_url: str,
    span: dict[str, str],
    named: set[str],
) -> None:
    # A wall time with no offset names no instant: 14:00 on the Friday the clocks change is two
    # different moments depending on the zone, and a period stored from one would subtract the
    # wrong hour from the denominator. A date with no time is the same case. The refusal NAMES the
    # bound it is about, so a caller is told which value to send again.
    answered = http.post(OFF_PLAN, json=span, headers=signed_in)

    assert answered.status_code == ValidationFailed.status, answered.text
    assert {error["field"] for error in answered.json()["errors"]} == named
    assert period_rows(live_database_url, owner.tenant_id) == []


def test_both_bounds_are_echoed_with_an_offset(http: TestClient, signed_in: dict[str, str]) -> None:
    # The wire carries an offset in both directions. A response instant without one would be read
    # in the reader's own zone, which is the same defect as accepting one without an offset.
    _, created = declare(http, signed_in)

    assert created["start"].endswith("Z")
    assert created["end"].endswith("Z")
    listed = http.get(OFF_PLAN, headers=signed_in).json()["periods"]
    assert [period["start"].endswith("Z") for period in listed] == [True]


def test_one_idempotency_key_is_scoped_to_the_route_that_used_it(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # A key is claimed per tenant, per ROUTE, so the same key on another resource is not a replay
    # of this one: an agent that reuses a key across two calls gets both writes, and only the
    # repeat of THIS route replays. Asserted here because a replay across resources would answer
    # 201 with this period's body while the other resource was never written.
    keyed = {**signed_in, IDEMPOTENCY_KEY_HEADER: str(uuid4())}

    declared = http.post(OFF_PLAN, json=FRIDAY_TO_MONDAY, headers=keyed)
    other_resource = http.post(AREAS_PREFIX, json={"name": "Fitness"}, headers=keyed)
    repeated = http.post(OFF_PLAN, json=FRIDAY_TO_MONDAY, headers=keyed)

    assert declared.status_code == HTTPStatus.CREATED, declared.text
    # The Area was created rather than answered with the period's body.
    assert other_resource.status_code == HTTPStatus.CREATED, other_resource.text
    assert other_resource.json()["area"]["name"] == "Fitness"
    # And the repeat of this route replays this route's own answer.
    assert repeated.json() == declared.json()
    assert len(period_rows(live_database_url, owner.tenant_id)) == 1


def test_a_label_that_names_nothing_is_refused(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # The field is nullable, so `null` already says "this span has no name": an empty string would
    # be a second spelling of it, and every comparable name in the product refuses it.
    status, problem = declare(http, signed_in, label="")

    assert status == ValidationFailed.status, problem
    assert period_rows(live_database_url, owner.tenant_id) == []


def test_a_label_cannot_be_emptied_by_a_patch_either(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # `null` clears it and `""` is refused, so the two intentions stay one apiece on both requests.
    _, created = declare(http, signed_in, label="Italy")

    answered = http.patch(f"{OFF_PLAN}/{created['id']}", json={"label": ""}, headers=signed_in)

    assert answered.status_code == ValidationFailed.status, answered.text
    assert [row.label for row in period_rows(live_database_url, owner.tenant_id)] == ["Italy"]


def test_a_label_at_the_length_bound_is_accepted_and_one_past_it_is_not(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Both ends of the bound, so the refusal above is a bound rather than a rejection of a label.
    at_the_bound = "x" * LABEL_MAX_LENGTH

    accepted, body = declare(http, signed_in, label=at_the_bound)
    refused, _ = declare(http, signed_in, label="x" * (LABEL_MAX_LENGTH + 1))

    assert accepted == HTTPStatus.CREATED
    assert body["label"] == at_the_bound
    assert refused == ValidationFailed.status


@pytest.mark.xfail(
    strict=True,
    reason="a label carrying a control byte reaches the driver, which refuses the byte at flush, "
    "so a caller error answers 500 with no actionable reason and an unexpected-error line lands "
    "in the log. Measured: 500, nothing stored. The fix is the shared user-text type, not a "
    "validator per module. Tracked as ticket 1135, which removes this marker.",
)
def test_a_label_carrying_a_control_byte_is_refused_rather_than_faulting(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    """A NUL byte in a label is a caller error and must read as one.

    Asserts the CORRECT behavior and is expected to fail, rather than pinning the defect as though
    it were the contract. Under ``strict=True`` an xfail that starts passing is itself a failure, so
    the shared fix forces this marker to be deleted rather than leaving a test that quietly agrees
    with whatever the code does.

    Nothing is lost today, because the transaction rolls back, which is why this is the status and
    the log line rather than a data defect.
    """
    status, problem = declare(http, signed_in, label="Italy\x00")

    assert status == ValidationFailed.status, problem
    assert period_rows(live_database_url, owner.tenant_id) == []


# --------------------------------------------------------------------------------
# Tenancy and authentication
# --------------------------------------------------------------------------------


def test_the_routes_need_a_credential(http: TestClient) -> None:
    for answered in (
        http.get(OFF_PLAN, headers={"Origin": BROWSER_ORIGIN}),
        http.post(OFF_PLAN, json=FRIDAY_TO_MONDAY, headers={"Origin": BROWSER_ORIGIN}),
    ):
        assert answered.status_code == HTTPStatus.UNAUTHORIZED


def test_another_tenants_period_is_a_404_rather_than_an_edit(
    http: TestClient,
    signed_in: dict[str, str],
    other_owner: UserRecord,
    live_database_url: str,
) -> None:
    theirs = _sign_in(http, other_owner.email)
    _, created = declare(http, theirs)

    read = http.get(f"{OFF_PLAN}/{created['id']}", headers=signed_in)
    patched = http.patch(f"{OFF_PLAN}/{created['id']}", json={"keepFrame": True}, headers=signed_in)
    removed = http.delete(f"{OFF_PLAN}/{created['id']}", headers=signed_in)

    assert [read.status_code, patched.status_code, removed.status_code] == [NotFound.status] * 3
    # Still theirs, and unchanged.
    assert [row.keep_frame for row in period_rows(live_database_url, other_owner.tenant_id)] == [
        False
    ]


def test_one_tenants_periods_are_absent_from_anothers_list(
    http: TestClient, signed_in: dict[str, str], other_owner: UserRecord
) -> None:
    declare(http, _sign_in(http, other_owner.email))

    answered = http.get(OFF_PLAN, headers=signed_in)

    assert answered.json()["periods"] == []


# --------------------------------------------------------------------------------
# The denominator, through the budget report
# --------------------------------------------------------------------------------


def test_a_week_with_no_time_off_reports_none(http: TestClient, signed_in: dict[str, str]) -> None:
    report = budget(http, signed_in, WEEK)

    assert report["offPlanMinutes"] == 0
    assert report["offPlanStatement"] is None
    assert report["discretionaryMinutes"] == OFF_PLAN_WEEK.week_span_minutes


def test_a_friday_to_monday_span_is_clipped_to_each_of_its_two_weeks(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # One record, two weeks, and each week reports its own part of it. The record itself is
    # unclipped; the clipping is a property of the reading.
    declare(http, signed_in)

    first = budget(http, signed_in, WEEK)
    second = budget(http, signed_in, FOLLOWING_WEEK)

    assert first["offPlanMinutes"] == OFF_PLAN_WEEK.off_plan_minutes_inside_the_week
    assert second["offPlanMinutes"] == OFF_PLAN_WEEK.off_plan_minutes_inside_the_following_week
    assert first["offPlanMinutes"] + second["offPlanMinutes"] == OFF_PLAN_WEEK.off_plan_minutes
    assert first["discretionaryMinutes"] == (
        OFF_PLAN_WEEK.week_span_minutes - OFF_PLAN_WEEK.off_plan_minutes_inside_the_week
    )
    # Neither week is wholly off-plan, so neither claims to be.
    assert first["offPlanStatement"] is None
    assert second["offPlanStatement"] is None


def test_a_week_declared_off_plan_end_to_end_reports_no_discretionary_time(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # Why the entity exists: a holiday must not read as every Area starving, and an empty deviation
    # set must not be the only thing the response says.
    whole_week = {
        "start": OFF_PLAN_WEEK.whole_week.start.isoformat().replace("+00:00", "Z"),
        "end": OFF_PLAN_WEEK.whole_week.end.isoformat().replace("+00:00", "Z"),
    }
    assert http.post(OFF_PLAN, json=whole_week, headers=signed_in).status_code == (
        HTTPStatus.CREATED
    )

    report = budget(http, signed_in, WEEK)

    assert report["discretionaryMinutes"] == 0
    assert report["unallocatedMinutes"] == 0
    assert report["areas"] == []
    assert report["offPlanMinutes"] == OFF_PLAN_WEEK.week_span_minutes
    assert report["offPlanStatement"] == WHOLE_WEEK_STATEMENT


def test_removing_a_period_returns_the_time_to_the_denominator(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    _, created = declare(http, signed_in)
    assert budget(http, signed_in, WEEK)["offPlanMinutes"] > 0

    http.delete(f"{OFF_PLAN}/{created['id']}", headers=signed_in)

    report = budget(http, signed_in, WEEK)
    assert report["offPlanMinutes"] == 0
    assert report["discretionaryMinutes"] == OFF_PLAN_WEEK.week_span_minutes


def test_the_week_the_span_does_not_reach_is_unaffected(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    # A period ending exactly at a week's first instant reaches nothing inside it. The week's own
    # length is what says so: 2026-W44 is an ordinary 168-hour week.
    ending_at_the_boundary = {
        "start": FRIDAY_TO_MONDAY["start"],
        "end": OFF_PLAN_WEEK.week_span.end.isoformat().replace("+00:00", "Z"),
    }
    assert http.post(OFF_PLAN, json=ending_at_the_boundary, headers=signed_in).status_code == (
        HTTPStatus.CREATED
    )

    report = budget(http, signed_in, FOLLOWING_WEEK)

    assert report["offPlanMinutes"] == 0
    assert report["offPlanStatement"] is None
    assert report["discretionaryMinutes"] == report["unallocatedMinutes"] == 168 * 60


def test_a_period_declared_in_another_tenants_week_does_not_reach_this_report(
    http: TestClient, signed_in: dict[str, str], other_owner: UserRecord
) -> None:
    declare(http, _sign_in(http, other_owner.email))

    report = budget(http, signed_in, WEEK)

    assert report["offPlanMinutes"] == 0
    assert report["discretionaryMinutes"] == OFF_PLAN_WEEK.week_span_minutes


def test_two_identical_reads_answer_identically(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    declare(http, signed_in)

    first = budget(http, signed_in, WEEK)
    second = budget(http, signed_in, WEEK)

    assert first == second


def test_the_declared_instants_are_stored_in_utc_whatever_offset_the_request_used(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    # Friday 14:00 in London is 13:00 UTC that week, and a client may send either form. The stored
    # instant is the same one, so a period declared from a phone in another zone is the period the
    # denominator subtracts.
    local_form = {
        "start": "2026-10-23T14:00:00+01:00",
        "end": "2026-10-26T09:00:00+00:00",
    }

    status = http.post(OFF_PLAN, json=local_form, headers=signed_in).status_code

    assert status == HTTPStatus.CREATED
    stored = period_rows(live_database_url, owner.tenant_id)
    assert [(row.start, row.end) for row in stored] == [
        (OFF_PLAN_WEEK.off_plan.start, OFF_PLAN_WEEK.off_plan.end)
    ]
    assert stored[0].start == datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
