"""The two pie-review routes end to end, against a real Postgres and a real request.

The readings suite proves the arithmetic and the classification over hand-built weeks. This proves
what only a real request and a real database can:

- the wire shape is camelCase, and the vacancy reaches it as a row with a null ``areaId``
- **the denominator is the plan of record's own stored figure**, not a recomputation. Asserted
  against ``/api/v1/budget``'s figure for the same week, which is the week's whole span: the two
  disagree by the frame, the difference is ticket 1310's, and this route is on the side of it that
  reads the figure the week was solved against
- only a confirmed day contributes, driven through the confirm route rather than by seeding a
  confirmation, so the path a user takes is the path measured
- the read writes nothing at all: no revision, no outcome, and no week input version
- applying a revision writes the shares it names, bumps the week input version, and refuses a body
  naming an Area this tenant does not hold without applying any of it
- another tenant's Area is refused rather than declared

A plan of record is seeded through ``PlanRepository`` because materialization is deliberately not a
user-facing act: there is no route that creates a plan, and there is not meant to be one.

**The dates are derived from the real clock**, because the confirm route refuses a day that has not
begun. A fixed date would pass until it went past.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from syncr_api.accounts.config import AUTH_PREFIX, SESSION_COOKIE_NAME
from syncr_api.areas.config import AREAS_PREFIX
from syncr_api.budgets.config import BUDGET_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.offplan.config import OFF_PLAN_PREFIX
from syncr_api.outcomes.config import DAYS_PREFIX
from syncr_api.plans.config import APPLIED
from syncr_api.plans.facts import BlockOutcome
from syncr_api.plans.models import PlanRevision, WeekInputVersion
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.reviews.config import PERIOD_PARAMETER, REVIEWS_PREFIX
from syncr_api.user_settings.config import SETTINGS_PREFIX
from syncr_domain.budget_review import QUARTER_WEEKS, ProposalBasis
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

# Yesterday, so every block this suite plans is behind `now` and the day it confirms has begun.
YESTERDAY = (utc_now() - timedelta(days=1)).date()
WEEK = IsoWeek.containing(YESTERDAY)

# A week that sleeps for 56 of its 168 hours: 112 hours of discretionary time. The figure the
# assembler stores, and the one the review divides.
DISCRETIONARY_MINUTES = 6720
WHOLE_SPAN_MINUTES = 10080
MINUTES_PER_HOUR = 60

BUDGET_REVIEW = f"{REVIEWS_PREFIX}/budget"
BUDGET_APPLY = f"{REVIEWS_PREFIX}/budget/apply"


def an_instant(on: Date, hour: int) -> datetime:
    return datetime.combine(on, time(hour), tzinfo=UTC)


def a_gym_block(*, on: Date, hour: int, index: int, area_id: AreaId, hours: int = 1) -> Block:
    return Block(
        iso_week=IsoWeek.containing(on),
        interval=Interval(an_instant(on, hour), an_instant(on, hour + hours)),
        binding=BindingRef.for_habit(uuid4(), index=index),
        title="Gym",
        reason=A_REASON,
        area_id=area_id,
    )


def a_week(
    blocks: Sequence[Block],
    *,
    iso_week: IsoWeek = WEEK,
    discretionary_minutes: int = DISCRETIONARY_MINUTES,
) -> PlanDocument:
    return PlanDocument(
        iso_week=iso_week,
        zone_by_date=active_zone_by_date(iso_week, ZoneProfile(UTC_ZONE)),
        discretionary_minutes=discretionary_minutes,
        unallocated_minutes=discretionary_minutes,
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
    headers = sign_in(http, owner.email)
    answered = http.patch(SETTINGS_PREFIX, json={"homeZone": UTC_ZONE}, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    return headers


def declare_area(
    http: TestClient,
    headers: dict[str, str],
    name: str = "Fitness",
    **budget: object,
) -> AreaId:
    answered = http.post(AREAS_PREFIX, json={"name": name, **budget}, headers=headers)
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return UUID(answered.json()["area"]["id"])


def seed_plan(database_url: str, tenant_id: TenantId, document: PlanDocument) -> None:
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


def rows_of(
    database_url: str, tenant_id: TenantId, model: type[PlanRevision] | type[BlockOutcome]
) -> int:
    async def count() -> int:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(select(model).where(model.tenant_id == tenant_id))
                return len(list(found))
        finally:
            await database.engine.dispose()

    return run(count())


def seed_versions(database_url: str, tenant_id: TenantId, weeks: Sequence[IsoWeek]) -> None:
    """A version row per week, as the first reference to a week creates one.

    The open-ended bump raises the weeks it TRACKS, and a week nothing has referenced is not one of
    them: a counter for a week no solve has read would be a row with no reader. So the assertion
    that an apply invalidates a solve needs a tracked week to invalidate, which is what this seeds.
    """

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


def read_review(
    http: TestClient, headers: dict[str, str], period: IsoWeek = WEEK
) -> dict[str, Any]:
    answered = http.get(BUDGET_REVIEW, params={PERIOD_PARAMETER: str(period)}, headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    body: dict[str, Any] = answered.json()
    return body


def apply_shares(
    http: TestClient, headers: dict[str, str], percentages: list[dict[str, object]]
) -> tuple[int, dict[str, Any]]:
    answered = http.post(BUDGET_APPLY, json={"percentages": percentages}, headers=headers)
    return answered.status_code, answered.json()


def confirm(http: TestClient, headers: dict[str, str], on: Date) -> None:
    answered = http.post(f"{DAYS_PREFIX}/{on.isoformat()}/confirm", headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text


def vacancy_of(body: dict[str, Any]) -> dict[str, Any]:
    """The one category row carrying no Area, which is the vacancy."""
    found: list[dict[str, Any]] = [row for row in body["categories"] if row["areaId"] is None]
    assert len(found) == 1, body["categories"]
    return found[0]


def area_row(body: dict[str, Any], area_id: AreaId) -> dict[str, Any]:
    found: list[dict[str, Any]] = [
        row for row in body["categories"] if row["areaId"] == str(area_id)
    ]
    assert len(found) == 1, body["categories"]
    return found[0]


@pytest.fixture
def planned(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> AreaId:
    """One Area declaring a 30% share, with two hours of it planned yesterday."""
    area_id = declare_area(http, signed_in, budget_percent=30)
    seed_plan(
        live_database_url,
        owner.tenant_id,
        a_week(
            [
                a_gym_block(on=YESTERDAY, hour=9, index=0, area_id=area_id),
                a_gym_block(on=YESTERDAY, hour=11, index=1, area_id=area_id),
            ]
        ),
    )
    return area_id


# --------------------------------------------------------------------------------
# The read
# --------------------------------------------------------------------------------


def test_the_denominator_is_the_plan_of_records_own_figure_and_not_the_weeks_span(
    http: TestClient, signed_in: dict[str, str], planned: AreaId
) -> None:
    """The decision this module rests on, pinned against the figure it deliberately does not use.

    ``/api/v1/budget`` recomputes the denominator through an occupancy reader that fills one of four
    subtrahends, so it reports the week's whole span. This route reads the figure the week was
    actually solved against. The two disagree by the circadian frame, which is ticket 1310, and the
    assertion below is what stops this screen quietly inheriting it.
    """
    review = read_review(http, signed_in)
    budget = http.get(BUDGET_PREFIX, params={PERIOD_PARAMETER: str(WEEK)}, headers=signed_in)

    assert review["discretionaryMinutes"] == DISCRETIONARY_MINUTES
    assert budget.json()["discretionaryMinutes"] == WHOLE_SPAN_MINUTES
    assert review["statement"] is None


def test_a_week_with_no_plan_of_record_reports_no_denominator_and_says_why(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    declare_area(http, signed_in, budget_percent=30)

    body = read_review(http, signed_in)

    assert body["discretionaryMinutes"] is None
    assert body["unallocatedMinutes"] is None
    assert body["oversubscriptionMinutes"] is None
    assert "holds no plan" in body["statement"]


def test_only_a_confirmed_day_contributes_to_the_actual_figure(
    http: TestClient, signed_in: dict[str, str], planned: AreaId
) -> None:
    before = read_review(http, signed_in)
    assert area_row(before, planned)["actualMinutes"] == 0
    assert before["days"] == {
        "confirmed": 0,
        "unconfirmed": 1,
        "offPlan": 0,
        "statement": before["days"]["statement"],
    }
    assert "No day of this week" in before["days"]["statement"]

    confirm(http, signed_in, YESTERDAY)

    after = read_review(http, signed_in)
    assert area_row(after, planned)["actualMinutes"] == 2 * MINUTES_PER_HOUR
    assert after["days"]["confirmed"] == 1
    assert after["days"]["unconfirmed"] == 0
    assert after["days"]["statement"] is None


def test_the_vacancy_is_a_row_carrying_no_area_and_holds_what_no_block_covered(
    http: TestClient, signed_in: dict[str, str], planned: AreaId
) -> None:
    confirm(http, signed_in, YESTERDAY)

    body = read_review(http, signed_in)

    assert vacancy_of(body)["actualMinutes"] == DISCRETIONARY_MINUTES - 2 * MINUTES_PER_HOUR
    assert body["unallocatedMinutes"] == DISCRETIONARY_MINUTES - 2 * MINUTES_PER_HOUR
    assert body["categories"][-1]["areaId"] is None


def test_shares_summing_to_a_hundred_leave_the_vacancy_non_zero(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    """US-AREA-03: a budget summing to exactly 100 does not make the residual zero."""
    first = declare_area(http, signed_in, "Career", budget_percent=60)
    declare_area(http, signed_in, "Study", budget_percent=40)
    seed_plan(
        live_database_url,
        owner.tenant_id,
        a_week([a_gym_block(on=YESTERDAY, hour=9, index=0, area_id=first)]),
    )
    confirm(http, signed_in, YESTERDAY)

    body = read_review(http, signed_in)

    assert body["unallocatedMinutes"] == DISCRETIONARY_MINUTES - MINUTES_PER_HOUR
    assert body["oversubscriptionMinutes"] == 0


def test_shares_summing_past_a_hundred_keep_the_vacancy_non_negative_and_report_the_excess(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    first = declare_area(http, signed_in, "Career", budget_percent=100)
    declare_area(http, signed_in, "Study", budget_percent=30)
    seed_plan(live_database_url, owner.tenant_id, a_week([]))

    body = read_review(http, signed_in)

    assert body["unallocatedMinutes"] == DISCRETIONARY_MINUTES
    assert body["oversubscriptionMinutes"] == 2016
    assert area_row(body, first)["targetMinutes"] == DISCRETIONARY_MINUTES


def test_an_off_plan_day_is_reported_separately_from_an_unconfirmed_one(
    http: TestClient, signed_in: dict[str, str], planned: AreaId
) -> None:
    answered = http.post(
        OFF_PLAN_PREFIX,
        json={
            "start": an_instant(YESTERDAY, 0).isoformat(),
            "end": an_instant(YESTERDAY + timedelta(days=1), 0).isoformat(),
            "label": "away",
        },
        headers=signed_in,
    )
    assert answered.status_code == HTTPStatus.CREATED, answered.text

    body = read_review(http, signed_in)

    assert body["days"]["offPlan"] == 1
    assert body["days"]["unconfirmed"] == 0
    assert body["offPlanMinutes"] == 24 * MINUTES_PER_HOUR


def test_the_trend_is_the_quarter_by_week_ending_with_the_named_one(
    http: TestClient, signed_in: dict[str, str], planned: AreaId
) -> None:
    body = read_review(http, signed_in)

    assert len(body["trend"]) == QUARTER_WEEKS
    assert body["trend"][-1]["period"] == str(WEEK)
    assert body["trend"][0]["period"] == str(_weeks_back(WEEK, QUARTER_WEEKS - 1))
    assert body["quarterDays"]["unconfirmed"] == 1


def test_below_a_quarter_of_confirmed_weeks_there_is_no_proposal_and_the_review_says_why(
    http: TestClient, signed_in: dict[str, str], planned: AreaId
) -> None:
    confirm(http, signed_in, YESTERDAY)

    body = read_review(http, signed_in)

    assert body["proposal"]["shares"] == []
    assert body["proposal"]["confirmedWeeks"] == 1
    assert body["proposal"]["requiredWeeks"] == QUARTER_WEEKS
    assert "gap between actual and target only" in body["proposal"]["statement"]
    assert "1 exists" in body["proposal"]["statement"]


def test_a_quarter_of_confirmed_weeks_proposes_a_share_for_every_category(
    http: TestClient, signed_in: dict[str, str], owner: UserRecord, live_database_url: str
) -> None:
    """Thirteen weeks each holding one confirmed hour, which is the gate's own boundary."""
    area_id = declare_area(http, signed_in, budget_percent=30)
    for back in range(QUARTER_WEEKS):
        on = YESTERDAY - timedelta(weeks=back)
        week = IsoWeek.containing(on)
        seed_plan(
            live_database_url,
            owner.tenant_id,
            a_week(
                [a_gym_block(on=on, hour=9, index=0, area_id=area_id)],
                iso_week=week,
                discretionary_minutes=600,
            ),
        )
        confirm(http, signed_in, on)

    body = read_review(http, signed_in)

    assert body["proposal"]["confirmedWeeks"] == QUARTER_WEEKS
    assert [row["areaId"] for row in body["proposal"]["shares"]] == [str(area_id), None]
    proposed = body["proposal"]["shares"][0]
    assert proposed["observedPercent"] == 10.0
    assert proposed["declaredPercent"] == 30.0
    assert proposed["proposedPercent"] == 20.0
    assert proposed["basis"] == ProposalBasis.NEVER_MET.value
    assert "not met in any" in proposed["statement"]
    assert "never re-cuts the budget on its own" in body["proposal"]["statement"]


def test_the_read_writes_nothing_at_all(
    http: TestClient,
    signed_in: dict[str, str],
    planned: AreaId,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    """A read never triggers work: no revision, no outcome row, and no version bump."""
    seed_versions(live_database_url, owner.tenant_id, [IsoWeek.containing(utc_now().date())])
    before = (
        rows_of(live_database_url, owner.tenant_id, PlanRevision),
        rows_of(live_database_url, owner.tenant_id, BlockOutcome),
        versions_of(live_database_url, owner.tenant_id),
    )

    read_review(http, signed_in)
    read_review(http, signed_in, _weeks_back(WEEK, 4))

    assert (
        rows_of(live_database_url, owner.tenant_id, PlanRevision),
        rows_of(live_database_url, owner.tenant_id, BlockOutcome),
        versions_of(live_database_url, owner.tenant_id),
    ) == before


def test_an_iso_week_the_period_cannot_be_read_as_is_refused_naming_the_parameter(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    answered = http.get(BUDGET_REVIEW, params={PERIOD_PARAMETER: "last-quarter"}, headers=signed_in)

    assert answered.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, answered.text
    assert answered.json()["errors"][0]["field"] == PERIOD_PARAMETER


# --------------------------------------------------------------------------------
# The apply
# --------------------------------------------------------------------------------


def test_applying_a_revision_declares_the_shares_and_bumps_the_week_input_version(
    http: TestClient,
    signed_in: dict[str, str],
    planned: AreaId,
    live_database_url: str,
    owner: UserRecord,
) -> None:
    this_week = IsoWeek.containing(utc_now().date())
    seed_versions(live_database_url, owner.tenant_id, [this_week])
    before = versions_of(live_database_url, owner.tenant_id)

    status, body = apply_shares(http, signed_in, [{"areaId": str(planned), "budgetPercent": 20}])

    assert status == HTTPStatus.OK, body
    assert body["applied"] == 1
    assert body["declared"] == [str(planned)]
    assert body["changedAt"] is not None
    stored = http.get(f"{AREAS_PREFIX}/{planned}", headers=signed_in).json()
    assert Decimal(str(stored["budgetPercent"])) == Decimal(20)
    assert versions_of(live_database_url, owner.tenant_id) != before


def test_an_adjusted_revision_takes_the_same_route_as_a_whole_one(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    """One path, so an adjusted revision cannot take a route a whole one does not."""
    first = declare_area(http, signed_in, "Career", budget_percent=30)
    second = declare_area(http, signed_in, "Study", budget_percent=20)

    status, body = apply_shares(
        http,
        signed_in,
        [
            {"areaId": str(first), "budgetPercent": 29},
            {"areaId": str(second), "budgetPercent": 25},
        ],
    )

    assert status == HTTPStatus.OK, body
    assert body["applied"] == 2
    assert set(body["declared"]) == {str(first), str(second)}


def test_a_fractional_share_is_applied_as_the_caller_sent_it(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    """A share is stored as ``NUMERIC(5, 2)`` and bounded by range alone, so it owes no grid.

    Every other case on this route uses a whole percentage, which left the rule stated in the
    field's own description and asserted nowhere on the apply path. Ticket 47's adjust control
    rests on it: it is a plain figure field rather than a stepper, precisely because a hundredth
    of a point is a legal declaration and a stepper would have written 35 for a typed 33.5.
    """
    area_id = declare_area(http, signed_in, budget_percent=30)

    status, body = apply_shares(http, signed_in, [{"areaId": str(area_id), "budgetPercent": 33.5}])

    assert status == HTTPStatus.OK, body
    assert body["applied"] == 1
    stored = http.get(f"{AREAS_PREFIX}/{area_id}", headers=signed_in).json()
    assert Decimal(str(stored["budgetPercent"])) == Decimal("33.5")


def test_an_area_the_request_does_not_name_is_left_alone(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    first = declare_area(http, signed_in, "Career", budget_percent=30)
    second = declare_area(http, signed_in, "Study", budget_percent=20)

    apply_shares(http, signed_in, [{"areaId": str(first), "budgetPercent": 10}])

    stored = http.get(f"{AREAS_PREFIX}/{second}", headers=signed_in).json()
    assert Decimal(str(stored["budgetPercent"])) == Decimal(20)


def test_a_share_already_holding_the_value_sent_changes_nothing_and_bumps_nothing(
    http: TestClient, signed_in: dict[str, str], live_database_url: str, owner: UserRecord
) -> None:
    area_id = declare_area(http, signed_in, budget_percent=30)
    seed_versions(live_database_url, owner.tenant_id, [IsoWeek.containing(utc_now().date())])
    before = versions_of(live_database_url, owner.tenant_id)

    status, body = apply_shares(http, signed_in, [{"areaId": str(area_id), "budgetPercent": 30}])

    assert status == HTTPStatus.OK, body
    assert body["applied"] == 0
    assert body["declared"] == []
    assert body["changedAt"] is None
    assert "already held the values sent" in body["statement"]
    assert versions_of(live_database_url, owner.tenant_id) == before


def test_a_body_naming_one_area_twice_is_refused_and_applies_none_of_it(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    area_id = declare_area(http, signed_in, budget_percent=30)

    status, body = apply_shares(
        http,
        signed_in,
        [
            {"areaId": str(area_id), "budgetPercent": 10},
            {"areaId": str(area_id), "budgetPercent": 40},
        ],
    )

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY, body
    assert "more than once" in body["detail"]
    stored = http.get(f"{AREAS_PREFIX}/{area_id}", headers=signed_in).json()
    assert Decimal(str(stored["budgetPercent"])) == Decimal(30)


def test_a_body_naming_an_area_this_tenant_does_not_hold_applies_none_of_it(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    """A 422 rather than a 404: the identifier is in the body, and the review exists."""
    area_id = declare_area(http, signed_in, budget_percent=30)

    status, body = apply_shares(
        http,
        signed_in,
        [
            {"areaId": str(area_id), "budgetPercent": 10},
            {"areaId": str(uuid4()), "budgetPercent": 40},
        ],
    )

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY, body
    assert "no share was applied" in body["detail"]
    stored = http.get(f"{AREAS_PREFIX}/{area_id}", headers=signed_in).json()
    assert Decimal(str(stored["budgetPercent"])) == Decimal(30)


def test_another_tenants_area_is_refused_rather_than_declared(
    http: TestClient,
    signed_in: dict[str, str],
    other_owner: UserRecord,
    live_database_url: str,
) -> None:
    theirs = declare_area(http, sign_in(http, other_owner.email), "Theirs", budget_percent=30)
    mine = declare_area(http, signed_in, budget_percent=30)

    status, body = apply_shares(
        http,
        signed_in,
        [
            {"areaId": str(mine), "budgetPercent": 10},
            {"areaId": str(theirs), "budgetPercent": 90},
        ],
    )

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY, body
    stored = http.get(f"{AREAS_PREFIX}/{mine}", headers=signed_in).json()
    assert Decimal(str(stored["budgetPercent"])) == Decimal(30)


def test_an_empty_body_is_refused_rather_than_applied_as_a_no_op(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    status, body = apply_shares(http, signed_in, [])

    assert status == HTTPStatus.UNPROCESSABLE_ENTITY, body


def test_a_share_past_the_whole_is_accepted_and_reported_rather_than_refused(
    http: TestClient, signed_in: dict[str, str], planned: AreaId
) -> None:
    """Percentages summing past 100 are a legitimate declaration, reported as oversubscription."""
    status, body = apply_shares(http, signed_in, [{"areaId": str(planned), "budgetPercent": 100}])
    assert status == HTTPStatus.OK, body

    review = read_review(http, signed_in)

    assert review["oversubscriptionMinutes"] == 0
    assert area_row(review, planned)["targetMinutes"] == DISCRETIONARY_MINUTES


def _weeks_back(week: IsoWeek, count: int) -> IsoWeek:
    found = week
    for _ in range(count):
        found = found.preceding()
    return found
