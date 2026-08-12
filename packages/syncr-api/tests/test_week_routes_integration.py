"""The four week routes end to end, against a real Postgres and a real request.

The composition suite proves the arithmetic and the mapping over values. This proves what only a
real request and a real database can.

*The composed read is one request.* A week with a plan answers with the document, the span, the
zone per day, the off-plan spans, the input version, and the eight readings, and a client needs no
second call to render the screen.

*``live`` is nullable and the reason is carried.* A week before any setup names the input that is
missing. A week past the projection horizon states the horizon and the date it reaches. A week
inside the horizon whose plan has not been produced says exactly that rather than claiming to be
beyond a horizon that holds it.

*The strip cannot disagree with the review.* ``unallocatedMinutes`` from this endpoint is asserted
equal to the same figure from ``GET /api/v1/budget`` for the same week, and so are the three figures
beside it, because both come from one arithmetic over one occupancy read.

*A read is not a mutation.* Every parameterized GET under the week prefix is driven and the row
count of every tenant-scoped table this application declares is compared before and after,
``verdict_events`` among them. Two identical reads answer with identical bytes.

*Requesting a solve is idempotent without a key*, and it is refused on a tenant that has not
declared what a plan needs, naming the missing input.

The boundaries this suite drives are the ones an endpoint has: a week with no plan, a week before
any setup, a year boundary, week 53, a tenant far east and one far west, a week whose own day
boundary falls in a daylight-saving gap, no credential, another tenant's week, and a read that must
not write.

**Note 4 from ``reviews/spec-review-5.md``** is recorded in ``test_week_view_composition.py``,
beside the traceability the note is about.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from statistics import quantiles
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME

# Runtime imports: the substituted dependency below is a real FastAPI dependency, so its annotations
# are resolved when the app resolves it.
from syncr_api.accounts.injection import PrincipalDep, TransactionDep  # noqa: TC001
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.budgets.config import BUDGET_PREFIX, PERIOD_PARAMETER
from syncr_api.concessions.config import ISO_WEEK_FIELD, WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.errors import Conflict, ValidationFailed
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.learned.repository import WeightSetRepository
from syncr_api.offplan.config import OFF_PLAN_PREFIX
from syncr_api.outcomes.config import DAYS_PREFIX
from syncr_api.plans.assembler import AssemblyCaller
from syncr_api.plans.config import APPLIED, PLAN_REVISIONS_TABLE, VERDICT_EVENTS_TABLE
from syncr_api.plans.currency import CURRENT, SOLVING, STALE
from syncr_api.plans.emptiness import AWAITING_MAINTAINER, OUTSIDE_HORIZON, SETUP_INCOMPLETE
from syncr_api.plans.injection import build_week_assembler, build_week_service, get_week_service
from syncr_api.plans.production import WeekProducer
from syncr_api.plans.readiness import MissingInput
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.plans.week_config import HISTORY_PAGE, IMMEDIATE_PARAMETER
from syncr_api.routines.config import ROUTINES_PREFIX
from syncr_api.solving.config import SOLVE
from syncr_api.solving.lifecycle import OperationLifecycle
from syncr_api.solving.outcomes import Failed
from syncr_api.solving.repository import OperationRepository
from syncr_api.templates.config import DAY_TYPES_PREFIX, WEEK_PATTERN_PREFIX
from syncr_domain.plan import RevisionReason
from syncr_domain.weeks import IsoWeek, Weekday
from tests.boundaries import week_addressed_reads
from tests.live_tenants import (
    PASSWORD,
    provision_owner,
    remove_tenant,
    row_counts,
    run,
)
from tests.plan_documents import a_block, a_document, a_zone_map, between

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_api.plans.service import WeekService
    from syncr_domain.identifiers import TenantId

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

LONDON = "Europe/London"
# Thirteen hours east and eleven west, so a tenant's local date and the UTC date disagree in both
# directions at some hour of every day.
AUCKLAND = "Pacific/Auckland"
MIDWAY = "Pacific/Midway"
# Havana's spring-forward transition is at local midnight, so one date of 2026-W10 has no 00:00 at
# all and is 23 hours long.
HAVANA = "America/Havana"
HAVANA_TRANSITION_WEEK = "2026-W10"

# The default horizon, which is what a tenant with no write target gets.
HORIZON_DAYS = 14

# Weeks with a fixed identity, for the assertions that are about the calendar rather than about the
# horizon. All four are far enough from now that they are outside any default horizon.
SPRING_FORWARD_WEEK = "2026-W13"
SPRING_FORWARD_HOURS = 167
FALL_BACK_WEEK = "2026-W43"
FALL_BACK_HOURS = 169
LAST_WEEK_OF_2026 = "2026-W53"
A_YEAR_WITH_NO_WEEK_53 = "2025-W53"

MINUTES_PER_HOUR = 60

# Roughly the block count section 19's latency budget is stated over.
BLOCKS_IN_A_FULL_WEEK = 210
# How many reads the p95 is taken over, and the ceiling this suite fails at. The budget is p95 under
# 300 ms; the ceiling here is deliberately looser, because a developer's machine and a CI runner are
# not the deployment, and a suite that failed on a slow runner would be answered by deleting it. The
# measured figure is reported rather than asserted.
LATENCY_SAMPLES = 30
CATASTROPHIC_MILLISECONDS = 1000


def this_week() -> IsoWeek:
    """The ISO week a request reads as current, which is the one inside every horizon."""
    return IsoWeek.containing(datetime.now(UTC).date())


def a_week_past_the_horizon() -> IsoWeek:
    """A week no default horizon reaches, whenever this suite runs."""
    return IsoWeek.containing(datetime.now(UTC).date() + timedelta(days=60))


def week_path(iso_week: object, suffix: str = "") -> str:
    return f"{WEEKS_PREFIX}/{iso_week}{suffix}"


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
    """The headers a signed-in browser sends. The cookie is replayed rather than jarred.

    The cookie is ``Secure`` and a client honoring that attribute will not send it back over
    ``http://testserver``.
    """
    answered = http.post(
        f"{AUTH_PREFIX}/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": BROWSER_ORIGIN},
    )
    assert answered.status_code == HTTPStatus.OK, answered.text
    cookie = answered.headers["set-cookie"]
    token = cookie.split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "Origin": BROWSER_ORIGIN}


def set_home_zone(http: TestClient, headers: dict[str, str], zone: str) -> None:
    """The span is resolved in the tenant's own zone, so every test states which."""
    answered = http.patch(f"{WEEKS_PREFIX[:-6]}/settings", json={"homeZone": zone}, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text


@pytest.fixture
def signed_in(http: TestClient, owner: UserRecord) -> dict[str, str]:
    """A signed-in tenant in London that has declared nothing at all."""
    headers = sign_in(http, owner.email)
    set_home_zone(http, headers, LONDON)
    return headers


def declare_an_area(http: TestClient, headers: dict[str, str], **body: object) -> str:
    answered = http.post(AREAS_PREFIX, json={"name": "Career", **body}, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return str(answered.json()["area"]["id"])


def declare_a_day_shape(http: TestClient, headers: dict[str, str]) -> None:
    """A day type on all seven weekdays, which is what makes a week pattern a pattern."""
    day_type = http.post(DAY_TYPES_PREFIX, json={"name": "Weekday"}, headers=headers)
    assert day_type.status_code == HTTPStatus.CREATED, day_type.text
    identifier = day_type.json()["id"]
    pattern = http.put(
        WEEK_PATTERN_PREFIX,
        json={weekday.value: identifier for weekday in Weekday},
        headers=headers,
    )
    assert pattern.status_code == HTTPStatus.OK, pattern.text


def declare_a_sleep_routine(http: TestClient, headers: dict[str, str]) -> None:
    """The circadian frame, which is what gives a materialized week any block at all.

    The minimum a plan can EXIST from is an Area and a day shape, and a week materialized from
    exactly that holds no block: nothing has been declared to happen. So a suite asserting what a
    block carries declares the frame, which is the first thing a real tenant declares too.
    """
    declared = http.post(
        ROUTINES_PREFIX,
        json={"title": "Sleep", "targetTime": "23:00", "durationMinutes": 480},
        headers=headers,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text


def seed_a_weight_set(database_url: str, tenant_id: TenantId) -> None:
    """The active weight set a produced revision records. No route creates one."""

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await WeightSetRepository(session, tenant_id).seed_hand_tuned(at=datetime.now(UTC))
        finally:
            await database.engine.dispose()

    run(seed())


@pytest.fixture
def configured(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> dict[str, str]:
    """A tenant that has declared the minimum a plan needs, and nothing more."""
    declare_an_area(http, signed_in)
    declare_a_day_shape(http, signed_in)
    seed_a_weight_set(live_database_url, owner.tenant_id)
    return signed_in


def produce_a_plan(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> None:
    """A real plan for the week, through the producer the horizon maintainer uses.

    Not through a route, because no route produces a plan: that is the whole point of the horizon
    maintainer, and a read that produced one would be the mutation this suite asserts it is not.
    """

    async def produce() -> None:
        now = datetime.now(UTC)
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                operations = OperationRepository(session, tenant_id)
                await WeekProducer(
                    assembler=build_week_assembler(
                        session, tenant_id, caller=AssemblyCaller.MAINTAINER
                    ),
                    revisions=PlanRepository(session, tenant_id),
                    versions=WeekInputVersionRepository(session, tenant_id),
                    weights=WeightSetRepository(session, tenant_id),
                    operations=OperationLifecycle(operations, lambda: now),
                ).advance_into(iso_week, now=now)
        finally:
            await database.engine.dispose()

    run(produce())


def append_a_document(
    database_url: str, tenant_id: TenantId, iso_week: IsoWeek, *, blocks: int
) -> None:
    """A revision holding ``blocks`` blocks, written through the real append-only repository.

    Materializing a week this full would need a week of declarations, and what the latency
    measurement is about is the cost of reading and serializing a document that size.
    """
    append_revisions(database_url, tenant_id, iso_week, count=1, blocks=blocks)


def append_revisions(
    database_url: str, tenant_id: TenantId, iso_week: IsoWeek, *, count: int, blocks: int = 1
) -> None:
    """``count`` revisions of one week, each holding ``blocks`` blocks, newest last."""

    async def append() -> None:
        now = datetime.now(UTC)
        document = a_document(
            week=iso_week,
            zone_by_date=a_zone_map(iso_week),
            blocks=tuple(
                a_block(
                    week=iso_week,
                    interval=between(
                        (index % 40) * 0.25 + 6,
                        (index % 40) * 0.25 + 6.5,
                        day=index % 7,
                        week=iso_week,
                    ),
                    binding=a_block(week=iso_week).binding,
                    title=f"block {index}",
                )
                for index in range(blocks)
            ),
        )
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                plans = PlanRepository(session, tenant_id)
                for appended in range(count):
                    await plans.append(
                        document=stored_document(document),
                        objective_breakdown={},
                        status=APPLIED,
                        reason=RevisionReason.HORIZON_ADVANCED.value,
                        weight_set_version=1,
                        input_version=1,
                        # Distinct instants, so "newest first" is an order the rows really have:
                        # the history's tie-break on the id would otherwise decide it.
                        created_at=now + timedelta(seconds=appended),
                    )
        finally:
            await database.engine.dispose()

    run(append())


def fail_a_solve(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> None:
    """One solve for the week, run out of attempts, so the week's last plan operation failed."""

    async def fail() -> None:
        now = datetime.now(UTC)
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                operations = OperationRepository(session, tenant_id)
                lifecycle = OperationLifecycle(operations, lambda: now, max_attempts=1)
                created = await lifecycle.enqueue(kind=SOLVE, iso_week=iso_week)
                await lifecycle.claim(created.id)
                await lifecycle.finish(
                    created.id, Failed(code="solver_raised", message="the solver raised")
                )
        finally:
            await database.engine.dispose()

    run(fail())


def enqueue_a_solve(database_url: str, tenant_id: TenantId, iso_week: IsoWeek) -> None:
    """One pending solve for the week, as a mutation would leave behind."""

    async def enqueue() -> None:
        now = datetime.now(UTC)
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                await OperationLifecycle(
                    OperationRepository(session, tenant_id), lambda: now
                ).enqueue(kind=SOLVE, iso_week=iso_week)
        finally:
            await database.engine.dispose()

    run(enqueue())


def week_view(http: TestClient, headers: dict[str, str], iso_week: object) -> dict[str, Any]:
    answered = http.get(week_path(iso_week), headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    payload: dict[str, Any] = answered.json()
    return payload


def budget(http: TestClient, headers: dict[str, str], iso_week: object) -> dict[str, Any]:
    answered = http.get(BUDGET_PREFIX, params={PERIOD_PARAMETER: str(iso_week)}, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    payload: dict[str, Any] = answered.json()
    return payload


def hours(span: dict[str, str]) -> float:
    return (
        datetime.fromisoformat(span["end"]) - datetime.fromisoformat(span["start"])
    ).total_seconds() / 3600


# --------------------------------------------------------------------------------
# The credential, and another tenant's week
# --------------------------------------------------------------------------------


def every_week_read(settings: ServiceSettings) -> list[str]:
    """Every parameterized GET under the week prefix, read off the app's own route table.

    The set is ``tests.boundaries.week_addressed_reads``, published there as this suite's
    contribution to the census in ``test_parameterized_read_census.py`` rather than filtered here.
    A filter reports what it matches and nothing about what it leaves out, so the reads no guard
    drives stayed invisible while this one looked complete. Still bounded by the routes rather than
    by a list, so a week read added later is driven by the guards below with no list to extend.
    """
    return week_addressed_reads(create_app(settings))


def test_every_week_read_needs_a_credential(http: TestClient, settings: ServiceSettings) -> None:
    """Driven over the app's own route table, so a week read added later is covered here."""
    paths = every_week_read(settings)
    assert paths, "no week read was found, so this asserted nothing"

    for path in paths:
        answered = http.get(path.replace("{iso_week}", str(this_week())))

        assert answered.status_code == HTTPStatus.UNAUTHORIZED, path


def test_the_reads_driven_above_include_the_four_this_module_owns(
    settings: ServiceSettings,
) -> None:
    """Named so the arrival of a fifth week route is a diff, and so the walk is not empty."""
    assert set(every_week_read(settings)) >= {
        week_path("{iso_week}", suffix) for suffix in ("", "/proposal", "/revisions", "/verdict")
    }


def test_requesting_a_solve_needs_a_credential(http: TestClient) -> None:
    answered = http.post(week_path(this_week(), "/solve"), headers={"Origin": BROWSER_ORIGIN})

    assert answered.status_code == HTTPStatus.UNAUTHORIZED


def test_requesting_a_solve_needs_a_trusted_origin(
    http: TestClient, configured: dict[str, str]
) -> None:
    """The half of CSRF protection ``SameSite=Lax`` does not cover, on the one route that writes."""
    without_the_header = {key: value for key, value in configured.items() if key != "Origin"}

    answered = http.post(week_path(this_week(), "/solve"), headers=without_the_header)

    assert answered.status_code == HTTPStatus.FORBIDDEN, answered.text


def test_one_tenants_plan_is_not_another_tenants_week(
    http: TestClient,
    owner: UserRecord,
    other_owner: UserRecord,
    live_database_url: str,
) -> None:
    """The same identifier addresses two different weeks, and neither can see the other's plan."""
    mine = sign_in(http, owner.email)
    set_home_zone(http, mine, LONDON)
    declare_an_area(http, mine)
    declare_a_day_shape(http, mine)
    seed_a_weight_set(live_database_url, owner.tenant_id)
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)

    theirs = sign_in(http, other_owner.email)

    assert week_view(http, mine, week)["live"] is not None
    assert week_view(http, theirs, week)["live"] is None


# --------------------------------------------------------------------------------
# A week that holds a plan
# --------------------------------------------------------------------------------


@pytest.fixture
def a_planned_week(
    http: TestClient, owner: UserRecord, configured: dict[str, str], live_database_url: str
) -> tuple[dict[str, str], IsoWeek]:
    """A configured tenant whose current week has a real materialized plan."""
    week = this_week()
    produce_a_plan(live_database_url, owner.tenant_id, week)
    return configured, week


def test_the_composed_read_answers_with_the_plan_and_everything_beside_it(
    http: TestClient, a_planned_week: tuple[dict[str, str], IsoWeek]
) -> None:
    headers, week = a_planned_week

    view = week_view(http, headers, week)

    assert view["isoWeek"] == str(week)
    assert hours(view["span"]) in {167.0, 168.0, 169.0}
    assert sorted(view["zoneByDate"]) == [day.isoformat() for day in week.dates()]
    assert set(view["zoneByDate"].values()) == {LONDON}
    assert view["emptyReason"] is None
    assert view["emptyWeek"] is None
    assert view["live"]["isoWeek"] == str(week)
    assert view["readings"] is not None
    assert view["inputVersion"] >= 1


def test_the_fields_a_materialized_week_has_nothing_to_put_in_are_present_and_empty(
    http: TestClient, a_planned_week: tuple[dict[str, str], IsoWeek]
) -> None:
    """A week the maintainer materialized has no proposal, no concession, no pin and no conflict.

    Present rather than omitted, which is what lets a client narrow ``null`` alone. The verdict is
    the one of the six that is NOT empty here: a week with a plan always has one, and this week's
    reports what capacity arithmetic could prove about it.
    """
    headers, week = a_planned_week

    view = week_view(http, headers, week)

    assert view["proposal"] is None
    assert view["candidateAdjustment"] is None
    assert view["adjustments"] == []
    assert view["pins"] == []
    assert view["conflicts"] == []
    assert view["verdict"] is not None
    assert view["verdict"]["provenance"] == "probe"


def test_the_wire_document_does_not_carry_the_three_figures_the_readings_carry_live(
    http: TestClient, a_planned_week: tuple[dict[str, str], IsoWeek]
) -> None:
    """One payload spells one figure once, so it cannot disagree with itself."""
    headers, week = a_planned_week

    document = week_view(http, headers, week)["live"]

    assert "discretionaryMinutes" not in document
    assert "unallocatedMinutes" not in document
    assert "oversubscriptionMinutes" not in document


def test_a_block_arrives_with_the_reason_that_explains_it(
    http: TestClient, owner: UserRecord, configured: dict[str, str], live_database_url: str
) -> None:
    """A materialized block carries exactly one clause, the bound clause naming its determinant."""
    week = this_week()
    declare_a_sleep_routine(http, configured)
    produce_a_plan(live_database_url, owner.tenant_id, week)
    declared = week_view(http, configured, week)["live"]["blocks"]
    assert declared, "the materialized week held no block, so this asserted nothing"

    for block in declared:
        assert block["reason"]["clauses"], block
        assert {clause["kind"] for clause in block["reason"]["clauses"]} == {"bound"}
        assert block["id"]
        assert block["origin"] == "frame"
        assert block["areaId"] is None, (
            "the frame defines how much time exists rather than using it"
        )


def test_an_off_plan_span_reaching_into_the_week_is_carried(
    http: TestClient, a_planned_week: tuple[dict[str, str], IsoWeek]
) -> None:
    headers, week = a_planned_week
    monday = datetime.combine(week.monday(), datetime.min.time(), tzinfo=UTC)
    declared = http.post(
        OFF_PLAN_PREFIX,
        json={
            "start": (monday + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            "end": (monday + timedelta(days=3)).isoformat().replace("+00:00", "Z"),
            "label": "a day off",
        },
        headers=headers,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text

    view = week_view(http, headers, week)

    assert [period["label"] for period in view["offPlan"]] == ["a day off"]
    assert view["readings"]["offPlanMinutes"] == 24 * MINUTES_PER_HOUR


# --------------------------------------------------------------------------------
# A week that holds no plan, and why
# --------------------------------------------------------------------------------


def test_a_tenant_that_has_declared_nothing_is_told_which_inputs_are_missing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    view = week_view(http, signed_in, this_week())

    assert view["live"] is None
    assert view["readings"] is None
    assert view["emptyReason"] == SETUP_INCOMPLETE
    assert view["emptyWeek"]["missingInputs"] == [
        MissingInput.AREAS.value,
        MissingInput.DAY_SHAPE.value,
    ]
    assert "at least one Area" in view["emptyWeek"]["statement"]
    assert "day shape for each weekday" in view["emptyWeek"]["statement"]


def test_declaring_an_area_leaves_the_day_shape_as_the_one_input_still_missing(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    declare_an_area(http, signed_in)

    view = week_view(http, signed_in, this_week())

    assert view["emptyWeek"]["missingInputs"] == [MissingInput.DAY_SHAPE.value]
    assert "at least one Area" not in view["emptyWeek"]["statement"]


def test_a_week_past_the_horizon_states_the_horizon_and_offers_the_two_actions(
    http: TestClient, configured: dict[str, str]
) -> None:
    """The response carries what both actions need: the horizon's length and the week itself."""
    view = week_view(http, configured, a_week_past_the_horizon())

    assert view["live"] is None
    assert view["emptyReason"] == OUTSIDE_HORIZON
    assert view["emptyWeek"]["missingInputs"] == []
    assert view["emptyWeek"]["horizonDays"] == HORIZON_DAYS
    assert view["emptyWeek"]["coversThisWeek"] is False
    assert view["emptyWeek"]["horizonThrough"] in view["emptyWeek"]["statement"]
    assert "solve this week now" in view["emptyWeek"]["statement"]


def test_a_week_inside_the_horizon_with_no_plan_yet_says_it_is_awaiting_the_maintainer(
    http: TestClient, configured: dict[str, str]
) -> None:
    """The transient between completing setup and the maintainer's next tick.

    The word, the flag and the sentence are asserted together: this is the state where a word
    borrowed from the week beyond the horizon would contradict the other two.
    """
    view = week_view(http, configured, this_week())

    assert view["live"] is None
    assert view["emptyReason"] == AWAITING_MAINTAINER
    assert view["emptyWeek"]["coversThisWeek"] is True
    assert "inside your" in view["emptyWeek"]["statement"]
    assert "has not been produced yet" in view["emptyWeek"]["statement"]


def test_a_missing_input_outranks_the_horizon(http: TestClient, signed_in: dict[str, str]) -> None:
    """Naming the horizon here would offer two actions that both fail without an Area."""
    view = week_view(http, signed_in, a_week_past_the_horizon())

    assert view["emptyReason"] == SETUP_INCOMPLETE
    assert view["emptyWeek"]["coversThisWeek"] is False


@pytest.mark.parametrize(
    "named", ["this", "planned", "past the horizon", SPRING_FORWARD_WEEK, LAST_WEEK_OF_2026]
)
def test_the_reason_and_the_readings_are_present_exactly_when_the_plan_is_absent(
    http: TestClient,
    owner: UserRecord,
    configured: dict[str, str],
    live_database_url: str,
    named: str,
) -> None:
    """``emptyReason`` is null exactly when ``live`` is populated, and so are the other four.

    Driven over five weeks in three states rather than asserted once, because the invariant is a
    biconditional and a suite that only ever read one state would hold half of it.

    The verdict is one of the four, and it is the one whose null side is a claim rather than an
    absence: a week the maintainer has not reached has had nothing computed about it, so a verdict
    beside it would be a statement about a plan that does not exist.
    """
    if named == "planned":
        produce_a_plan(live_database_url, owner.tenant_id, this_week())
    week = {
        "this": this_week(),
        "planned": this_week(),
        "past the horizon": (a_week_past_the_horizon()),
    }.get(named, named)

    view = week_view(http, configured, week)

    absent = view["live"] is None
    assert (view["readings"] is None) is absent
    assert (view["verdict"] is None) is absent
    assert (view["emptyReason"] is not None) is absent
    assert (view["emptyWeek"] is not None) is absent


def test_a_week_nothing_has_referenced_reports_no_input_version_and_creates_no_row(
    http: TestClient, owner: UserRecord, configured: dict[str, str], live_database_url: str
) -> None:
    """Versions start at one, so zero reads as untracked rather than as a version.

    Reading such a week must not create the row either: the conditional write's own guard DOES
    create one, deliberately, and a read that borrowed that guard would make navigating a mutation.
    """
    week = a_week_past_the_horizon()

    assert week_view(http, configured, week)["inputVersion"] == 0
    assert week_view(http, configured, week)["inputVersion"] == 0

    assert tracked_weeks(live_database_url, owner.tenant_id) == ()


def tracked_weeks(database_url: str, tenant_id: TenantId) -> tuple[IsoWeek, ...]:
    """Every week this tenant has a version row for."""

    async def read() -> tuple[IsoWeek, ...]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await WeekInputVersionRepository(session, tenant_id).tracked_weeks(
                    IsoWeek(2020, 1)
                )
        finally:
            await database.engine.dispose()

    return run(read())


# --------------------------------------------------------------------------------
# The identifier, and the calendar's own boundaries
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("named", ["not-a-week", "2026-W00", A_YEAR_WITH_NO_WEEK_53, "2026W07"])
def test_an_identifier_that_is_not_an_iso_week_is_refused_naming_the_parameter_sent(
    http: TestClient, signed_in: dict[str, str], named: str
) -> None:
    answered = http.get(week_path(named), headers=signed_in)

    assert answered.status_code == ValidationFailed.status, answered.text
    problem = answered.json()
    assert [error["field"] for error in problem["errors"]] == [ISO_WEEK_FIELD]


def test_the_last_week_of_a_year_that_has_fifty_three_is_a_week(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    """2026 holds 53 ISO weeks, and the last of them holds three dates in 2027."""
    view = week_view(http, signed_in, LAST_WEEK_OF_2026)

    assert view["isoWeek"] == LAST_WEEK_OF_2026
    assert view["span"]["start"].startswith("2026-12-28")
    assert view["span"]["end"].startswith("2027-01-04")
    assert sorted(view["zoneByDate"])[-1] == "2027-01-03"


@pytest.mark.parametrize(
    ("named", "expected"),
    [(SPRING_FORWARD_WEEK, SPRING_FORWARD_HOURS), (FALL_BACK_WEEK, FALL_BACK_HOURS)],
)
def test_a_transition_week_is_as_long_as_it_really_was(
    http: TestClient, signed_in: dict[str, str], named: str, expected: int
) -> None:
    view = week_view(http, signed_in, named)

    assert hours(view["span"]) == expected


@pytest.mark.parametrize(
    ("zone", "days_from_the_utc_monday"),
    [(AUCKLAND, -1), (MIDWAY, 0)],
)
def test_a_tenant_whose_local_date_disagrees_with_the_utc_date_reads_its_own_week(
    http: TestClient, owner: UserRecord, zone: str, days_from_the_utc_monday: int
) -> None:
    """The span is bounded by the LOCAL Mondays, thirteen hours east and eleven west.

    Auckland's Monday begins on the Sunday in UTC and Midway's begins late on the Monday itself, so
    a span resolved in UTC would name the same two instants for both.
    """
    headers = sign_in(http, owner.email)
    set_home_zone(http, headers, zone)
    monday = IsoWeek.parse(SPRING_FORWARD_WEEK).monday()

    view = week_view(http, headers, SPRING_FORWARD_WEEK)

    began = datetime.fromisoformat(view["span"]["start"])
    assert began.date() == monday + timedelta(days=days_from_the_utc_monday)
    assert began.time() != datetime.min.time()
    assert set(view["zoneByDate"].values()) == {zone}
    assert len(view["zoneByDate"]) == 7


def test_the_horizon_is_resolved_in_the_tenants_own_zone_rather_than_in_utc(
    http: TestClient, owner: UserRecord, live_database_url: str, settings: ServiceSettings
) -> None:
    """An hour where the local date and the UTC date disagree, driven at a fixed instant.

    23:30 UTC is already tomorrow in Auckland, so a horizon computed from the UTC date would report
    a last covered date a day short of the one this tenant's own calendar is on. The clock is
    substituted rather than waited for, because the disagreement lasts thirteen hours a day and a
    suite that only had bite during them would pass for the wrong reason the rest of the time.
    """
    at_night = datetime.now(UTC).replace(hour=23, minute=30, second=0, microsecond=0)
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    app.dependency_overrides[get_week_service] = _week_service_at(at_night)
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = sign_in(client, owner.email)
        set_home_zone(client, headers, AUCKLAND)
        declare_an_area(client, headers)
        declare_a_day_shape(client, headers)

        empty = week_view(client, headers, a_week_past_the_horizon())["emptyWeek"]

    local_today = at_night.astimezone(ZoneInfo(AUCKLAND)).date()
    assert local_today == at_night.date() + timedelta(days=1), "the fixture instant agrees in UTC"
    assert empty["horizonThrough"] == (local_today + timedelta(days=HORIZON_DAYS - 1)).isoformat()


def _week_service_at(now: datetime) -> Callable[..., WeekService]:
    """The week service this request would build, with one instant instead of the clock."""

    def build(principal: PrincipalDep, transaction: TransactionDep) -> WeekService:
        return build_week_service(transaction, principal.tenant_id, clock=lambda: now)

    return build


def test_a_week_holding_a_day_whose_own_midnight_does_not_exist_still_holds_seven_days(
    http: TestClient, owner: UserRecord
) -> None:
    """Havana's spring-forward transition is at local midnight, so one date is 23 hours long."""
    headers = sign_in(http, owner.email)
    set_home_zone(http, headers, HAVANA)

    view = week_view(http, headers, HAVANA_TRANSITION_WEEK)

    assert len(view["zoneByDate"]) == 7
    assert hours(view["span"]) == SPRING_FORWARD_HOURS


# --------------------------------------------------------------------------------
# The readings, against the review that divides the same denominator
# --------------------------------------------------------------------------------


def test_the_strip_figures_are_the_budget_reports_own(
    http: TestClient, a_planned_week: tuple[dict[str, str], IsoWeek]
) -> None:
    """The criterion: a figure on the strip cannot disagree with the same figure in the review."""
    headers, week = a_planned_week

    readings = week_view(http, headers, week)["readings"]
    report = budget(http, headers, week)

    assert readings["unallocatedMinutes"] == report["unallocatedMinutes"]
    assert readings["discretionaryMinutes"] == report["discretionaryMinutes"]
    assert readings["oversubscriptionMinutes"] == report["oversubscriptionMinutes"]
    assert readings["offPlanMinutes"] == report["offPlanMinutes"]


def test_the_two_figures_still_agree_once_the_week_has_an_area_and_time_off(
    http: TestClient, owner: UserRecord, configured: dict[str, str], live_database_url: str
) -> None:
    """A control on the agreement above, which two zeros would satisfy for the wrong reason."""
    week = this_week()
    monday = datetime.combine(week.monday(), datetime.min.time(), tzinfo=UTC)
    declared = http.post(
        OFF_PLAN_PREFIX,
        json={
            "start": (monday + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "end": (monday + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        },
        headers=configured,
    )
    assert declared.status_code == HTTPStatus.CREATED, declared.text
    declare_an_area(http, configured, name="Fitness", budgetPercent=40, floorHours=6)
    produce_a_plan(live_database_url, owner.tenant_id, week)

    readings = week_view(http, configured, week)["readings"]
    report = budget(http, configured, week)

    assert readings["unallocatedMinutes"] == report["unallocatedMinutes"] > 0
    assert readings["offPlanMinutes"] == report["offPlanMinutes"] == 24 * MINUTES_PER_HOUR
    assert readings["discretionaryMinutes"] == report["discretionaryMinutes"]


def test_the_block_count_and_the_scheduled_figure_are_the_documents_own(
    http: TestClient, a_planned_week: tuple[dict[str, str], IsoWeek]
) -> None:
    headers, week = a_planned_week

    view = week_view(http, headers, week)

    assert view["readings"]["blockCount"] == len(view["live"]["blocks"])
    assert view["readings"]["unconfirmedDays"] >= 0


def test_a_past_week_holding_a_block_on_every_day_owes_seven_confirmations(
    http: TestClient, owner: UserRecord, configured: dict[str, str], live_database_url: str
) -> None:
    """Every day of a week that is over has ended, so every one of them can be confirmed.

    A past week rather than the current one, because how many of this week's days have ended depends
    on the day the suite runs and a figure asserted against that would be a figure asserted against
    the calendar.
    """
    week = IsoWeek.containing(datetime.now(UTC).date() - timedelta(days=30))
    append_a_document(live_database_url, owner.tenant_id, week, blocks=7)

    readings = week_view(http, configured, week)["readings"]

    assert readings["blockCount"] == 7
    assert readings["unconfirmedDays"] == 7
    assert readings["scheduledMinutes"] == 7 * 30


def test_confirming_a_day_takes_it_out_of_the_count(
    http: TestClient, owner: UserRecord, configured: dict[str, str], live_database_url: str
) -> None:
    """The count is the outcome log's own rule, so the two surfaces cannot disagree about a week.

    Driven through the confirmation route rather than by seeding a row, because what this asserts is
    that the week view reads the same confirmations the Today surface writes.
    """
    week = IsoWeek.containing(datetime.now(UTC).date() - timedelta(days=30))
    append_a_document(live_database_url, owner.tenant_id, week, blocks=7)
    monday = week.monday()

    confirmed = http.post(f"{DAYS_PREFIX}/{monday}/confirm", headers=configured)

    assert confirmed.status_code in {HTTPStatus.OK, HTTPStatus.NO_CONTENT}, confirmed.text
    assert week_view(http, configured, week)["readings"]["unconfirmedDays"] == 6


def test_a_week_nothing_is_working_on_reads_as_current(
    http: TestClient, a_planned_week: tuple[dict[str, str], IsoWeek]
) -> None:
    headers, week = a_planned_week

    assert week_view(http, headers, week)["readings"]["planCurrency"] == CURRENT


def test_a_week_with_a_solve_in_flight_reads_as_solving(
    http: TestClient,
    owner: UserRecord,
    a_planned_week: tuple[dict[str, str], IsoWeek],
    live_database_url: str,
) -> None:
    headers, week = a_planned_week
    enqueue_a_solve(live_database_url, owner.tenant_id, week)

    view = week_view(http, headers, week)

    assert view["readings"]["planCurrency"] == SOLVING
    assert view["operation"]["target"]["isoWeek"] == str(week)
    assert view["operation"]["kind"] == SOLVE


def test_a_week_whose_last_solve_failed_terminally_reads_as_stale(
    http: TestClient,
    owner: UserRecord,
    a_planned_week: tuple[dict[str, str], IsoWeek],
    live_database_url: str,
) -> None:
    headers, week = a_planned_week
    fail_a_solve(live_database_url, owner.tenant_id, week)

    view = week_view(http, headers, week)

    assert view["readings"]["planCurrency"] == STALE
    assert view["operation"] is None


# --------------------------------------------------------------------------------
# The revision history
# --------------------------------------------------------------------------------


def test_the_history_lists_each_revision_with_its_timestamp_status_and_reason(
    http: TestClient, a_planned_week: tuple[dict[str, str], IsoWeek]
) -> None:
    headers, week = a_planned_week

    answered = http.get(week_path(week, "/revisions"), headers=headers)

    assert answered.status_code == HTTPStatus.OK, answered.text
    revisions = answered.json()["revisions"]
    assert len(revisions) == 1
    assert revisions[0]["reason"] == RevisionReason.HORIZON_ADVANCED.value
    assert revisions[0]["status"] == APPLIED
    assert revisions[0]["createdAt"]
    assert revisions[0]["approvedAt"] is None
    # The revision names the inputs it was produced FROM, and appending it changed the live plan,
    # which is itself a solve input: so the week now reads one version further on.
    assert revisions[0]["inputVersion"] < week_view(http, headers, week)["inputVersion"]
    assert answered.json()["truncated"] is False


def test_a_history_longer_than_one_page_says_so_rather_than_truncating_in_silence(
    http: TestClient, owner: UserRecord, configured: dict[str, str], live_database_url: str
) -> None:
    """A page as long as its own bound is indistinguishable from a whole history without the flag.

    Driven at exactly the bound and one past it, because the off-by-one is the whole question: a
    check that compared the page's length to the bound would call the first of these truncated.
    """
    week = IsoWeek.containing(datetime.now(UTC).date() - timedelta(days=60))
    append_revisions(live_database_url, owner.tenant_id, week, count=HISTORY_PAGE)

    exactly_one_page = revisions_of(http, configured, week)

    assert len(exactly_one_page["revisions"]) == HISTORY_PAGE
    assert exactly_one_page["truncated"] is False

    append_revisions(live_database_url, owner.tenant_id, week, count=1)
    one_too_many = revisions_of(http, configured, week)

    assert len(one_too_many["revisions"]) == HISTORY_PAGE
    assert one_too_many["truncated"] is True


def revisions_of(http: TestClient, headers: dict[str, str], iso_week: object) -> dict[str, Any]:
    answered = http.get(week_path(iso_week, "/revisions"), headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    payload: dict[str, Any] = answered.json()
    return payload


def test_a_week_with_no_revision_has_an_empty_history(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    answered = http.get(week_path(this_week(), "/revisions"), headers=signed_in)

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert answered.json() == {"revisions": [], "truncated": False}


def test_no_route_offers_a_method_that_could_change_a_revision(
    settings: ServiceSettings,
) -> None:
    """The history is read-only, asserted over the app's own route table.

    Bounded by every route whose path names the revisions collection rather than by the ones this
    ticket added, so a later ticket cannot open a write path to it without this reddening.
    """
    revision_routes = {
        (method, path)
        for route in _api_routes(settings)
        for method, path in route
        if "revisions" in path
    }

    assert revision_routes == {("GET", week_path("{iso_week}", "/revisions"))}


def _api_routes(settings: ServiceSettings) -> list[set[tuple[str, str]]]:
    from tests.boundaries import api_routes, route_identity

    return [route_identity(route) for route in api_routes(create_app(settings))]


def test_driving_every_week_route_leaves_the_stored_revision_untouched(
    http: TestClient,
    owner: UserRecord,
    a_planned_week: tuple[dict[str, str], IsoWeek],
    live_database_url: str,
    settings: ServiceSettings,
) -> None:
    """Including the one route that writes: requesting a solve appends no revision either.

    The reads are the app's own route table rather than a list of suffixes, so a week read added
    later is driven here. A 404 is an answer: the proposal read answers one on a week whose slot is
    empty, and what is under test is the revision rows rather than the status.
    """
    headers, week = a_planned_week
    before = stored_revisions(live_database_url, owner.tenant_id)
    paths = every_week_read(settings)
    assert paths, "no week read was found, so this asserted nothing"

    for path in paths:
        answered = http.get(path.replace("{iso_week}", str(week)), headers=headers)
        assert answered.status_code in {HTTPStatus.OK, HTTPStatus.NOT_FOUND}, (
            path,
            answered.text,
        )
    assert http.post(week_path(week, "/solve"), headers=headers).status_code == HTTPStatus.ACCEPTED

    assert stored_revisions(live_database_url, owner.tenant_id) == before


def stored_revisions(database_url: str, tenant_id: TenantId) -> list[tuple[Any, ...]]:
    """Every revision row of this tenant, reduced to the values a mutation would change."""

    async def read() -> list[tuple[Any, ...]]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await PlanRepository(session, tenant_id).history(this_week())
                return [
                    (
                        record.id,
                        record.status,
                        record.reason,
                        record.created_at,
                        record.approved_at,
                        record.input_version,
                        record.document,
                    )
                    for record in found
                ]
        finally:
            await database.engine.dispose()

    return run(read())


# --------------------------------------------------------------------------------
# A read is not a mutation
# --------------------------------------------------------------------------------


def test_no_parameterized_week_read_brings_a_row_into_existence(
    http: TestClient,
    owner: UserRecord,
    a_planned_week: tuple[dict[str, str], IsoWeek],
    live_database_url: str,
    settings: ServiceSettings,
    source_root: Path,
) -> None:
    """The criterion ticket 28's guard could not reach, because every week route is parameterized.

    Every scoped table the application declares is counted before and after, ``verdict_events``
    among them, so a read that appended a transition would redden this without the table being
    named. Three of the four reads compute a verdict now, so the counting has something to catch.
    """
    headers, week = a_planned_week
    paths = every_week_read(settings)
    assert paths, "no parameterized week read was found, so this asserted nothing"
    before = row_counts(live_database_url, owner.tenant_id, source_root)
    assert before[VERDICT_EVENTS_TABLE] == 0
    assert before[PLAN_REVISIONS_TABLE] == 1

    for path in paths:
        answered = http.get(path.replace("{iso_week}", str(week)), headers=headers)
        assert answered.status_code != HTTPStatus.INTERNAL_SERVER_ERROR, (path, answered.text)

    assert row_counts(live_database_url, owner.tenant_id, source_root) == before
    assert week_view(http, headers, week)["verdict"] is not None, (
        "no read computed a verdict, so the verdict_events count above asserted nothing"
    )


def test_counting_rows_would_have_caught_a_write(
    http: TestClient,
    owner: UserRecord,
    a_planned_week: tuple[dict[str, str], IsoWeek],
    live_database_url: str,
    source_root: Path,
) -> None:
    """The control: the same counts DO move when the one route that writes is driven."""
    headers, week = a_planned_week
    before = row_counts(live_database_url, owner.tenant_id, source_root)

    assert http.post(week_path(week, "/solve"), headers=headers).status_code == (
        HTTPStatus.ACCEPTED
    )

    assert row_counts(live_database_url, owner.tenant_id, source_root) != before


def test_two_identical_reads_at_one_instant_answer_with_identical_bytes(
    owner: UserRecord, live_database_url: str, settings: ServiceSettings
) -> None:
    """Reproducible at a stated instant, which is what a reproducible read means here.

    The clock is substituted rather than trusted. The verdict is a fact about an assembly stamped at
    ``now``, so a read carries the instant it was computed at and capacity is clipped to it: two
    reads a moment apart differ in that instant, and a deadline that passed between them can differ
    in more than that. The invariant is that the answer is a function of the stored state and the
    instant, which is the same discipline the assembler states about its own argument.
    """
    at_a_stated_instant = datetime.now(UTC).replace(microsecond=0)
    database = create_database(live_database_url)
    app = create_app(settings, lifespan=create_db_lifespan(database.engine))
    app.state.db = database
    app.dependency_overrides[get_week_service] = _week_service_at(at_a_stated_instant)
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = sign_in(client, owner.email)
        set_home_zone(client, headers, LONDON)
        declare_an_area(client, headers)
        declare_a_day_shape(client, headers)
        seed_a_weight_set(live_database_url, owner.tenant_id)
        produce_a_plan(live_database_url, owner.tenant_id, this_week())

        first = client.get(week_path(this_week()), headers=headers)
        second = client.get(week_path(this_week()), headers=headers)

    assert first.status_code == second.status_code == HTTPStatus.OK, first.text
    assert first.json()["verdict"] is not None, "no verdict was computed, so this asserted less"
    assert first.content == second.content


def test_reading_the_verdict_answers_the_weeks_verdict_and_appends_nothing(
    http: TestClient,
    owner: UserRecord,
    a_planned_week: tuple[dict[str, str], IsoWeek],
    live_database_url: str,
    source_root: Path,
) -> None:
    """The cheap refresh answers the same verdict the composed read does, and writes no row.

    Asserted against the composed read rather than against a literal, because what the two must not
    do is disagree: one rule serves both, so a week reporting a packing failure on one and a
    capacity check on the other would be two rules.
    """
    headers, week = a_planned_week
    before = row_counts(live_database_url, owner.tenant_id, source_root)

    answered = http.get(week_path(week, "/verdict"), headers=headers)

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert answered.json()["verdict"] is not None
    assert (
        answered.json()["verdict"]["provenance"]
        == week_view(http, headers, week)["verdict"]["provenance"]
    )
    assert row_counts(live_database_url, owner.tenant_id, source_root) == before


def test_reading_the_verdict_of_a_week_with_no_plan_answers_null(
    http: TestClient, configured: dict[str, str]
) -> None:
    """Null exactly when ``live`` is null, which is the biconditional the composed read states."""
    beyond = a_week_past_the_horizon()

    answered = http.get(week_path(beyond, "/verdict"), headers=configured)

    assert answered.status_code == HTTPStatus.OK, answered.text
    assert answered.json() == {"verdict": None}
    assert week_view(http, configured, beyond)["live"] is None


def test_the_verdict_route_refuses_an_identifier_that_is_not_a_week(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    """A null for a week that does not exist would read as "this week has no verdict"."""
    answered = http.get(week_path("2026-W99", "/verdict"), headers=signed_in)

    assert answered.status_code == ValidationFailed.status, answered.text


# --------------------------------------------------------------------------------
# Requesting a solve
# --------------------------------------------------------------------------------


def test_requesting_a_solve_answers_with_the_operation_to_follow(
    http: TestClient, configured: dict[str, str]
) -> None:
    week = this_week()

    answered = http.post(week_path(week, "/solve"), headers=configured)

    assert answered.status_code == HTTPStatus.ACCEPTED, answered.text
    operation = answered.json()
    assert operation["kind"] == SOLVE
    assert operation["target"]["isoWeek"] == str(week)
    assert operation["status"] == "pending"


def test_requesting_a_solve_twice_is_one_solve_and_needs_no_key(
    http: TestClient, owner: UserRecord, configured: dict[str, str], live_database_url: str
) -> None:
    """Idempotent per week by the coordinator's own invariant: one non-terminal solve per week."""
    week = this_week()

    first = http.post(week_path(week, "/solve"), headers=configured)
    second = http.post(week_path(week, "/solve"), headers=configured)

    assert first.status_code == second.status_code == HTTPStatus.ACCEPTED, second.text
    assert first.json()["id"] == second.json()["id"]
    assert len(week_operations(live_database_url, owner.tenant_id, week)) == 1


def test_asking_for_it_immediately_is_also_one_solve(
    http: TestClient, configured: dict[str, str]
) -> None:
    """The action an empty week offers. It bypasses a window the coordinator does not own yet."""
    week = a_week_past_the_horizon()

    answered = http.post(
        week_path(week, "/solve"), params={IMMEDIATE_PARAMETER: "true"}, headers=configured
    )

    assert answered.status_code == HTTPStatus.ACCEPTED, answered.text
    assert answered.json()["target"]["isoWeek"] == str(week)


def test_a_solve_is_refused_naming_the_missing_input_rather_than_planning_an_empty_week(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    answered = http.post(week_path(this_week(), "/solve"), headers=signed_in)

    assert answered.status_code == Conflict.status, answered.text
    assert "at least one Area" in answered.json()["detail"]
    assert week_operations(live_database_url, owner.tenant_id, this_week()) == []


def week_operations(
    database_url: str, tenant_id: TenantId, iso_week: IsoWeek
) -> list[tuple[str, str]]:
    """Every operation naming this week, as ``(kind, status)`` pairs."""

    async def read() -> list[tuple[str, str]]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await OperationRepository(session, tenant_id).page(limit=50)
                return [
                    (record.kind, record.status) for record in found if record.iso_week == iso_week
                ]
        finally:
            await database.engine.dispose()

    return run(read())


# --------------------------------------------------------------------------------
# The latency budget, measured
# --------------------------------------------------------------------------------


def test_the_week_view_is_read_in_well_under_the_budget_on_a_full_week(
    http: TestClient,
    owner: UserRecord,
    configured: dict[str, str],
    live_database_url: str,
) -> None:
    """Section 19 budgets this read at p95 under 300 ms on a week of roughly 210 blocks.

    Measured rather than asserted: the figure below is reported and the assertion is an order of
    magnitude looser, because a developer's machine and a CI runner are not the deployment. A
    ceiling tight enough to be the budget would be answered by deleting the test.

    **The client is in-process**, so the figure excludes the ASGI server, the socket and TLS. It is
    a lower bound on deployed latency rather than an estimate of it, which is what makes the
    four-fold headroom the conclusion rather than the number itself.
    """
    week = this_week()
    append_a_document(live_database_url, owner.tenant_id, week, blocks=BLOCKS_IN_A_FULL_WEEK)
    view = week_view(http, configured, week)
    assert view["readings"]["blockCount"] == BLOCKS_IN_A_FULL_WEEK

    measured = []
    for _sample in range(LATENCY_SAMPLES):
        started = time.perf_counter()
        answered = http.get(week_path(week), headers=configured)
        measured.append((time.perf_counter() - started) * 1000)
        assert answered.status_code == HTTPStatus.OK

    ordered = sorted(measured)
    p95 = quantiles(ordered, n=20)[-1]
    report = (
        f"{BLOCKS_IN_A_FULL_WEEK} blocks over {LATENCY_SAMPLES} reads: "
        f"p50 {ordered[len(ordered) // 2]:.1f} ms, p95 {p95:.1f} ms, max {ordered[-1]:.1f} ms"
    )
    print(f"\nweek view latency: {report}")

    assert p95 < CATASTROPHIC_MILLISECONDS, report
