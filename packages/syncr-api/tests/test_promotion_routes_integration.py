"""The accept and the decline end to end, against a real Postgres and a real request.

The absorption suite proves the rule over hand-built values. This proves what only a real request
and the production wiring can:

- **the identifier the two routes take is the one the weekly session emits**, so the pair cannot be
  proved against a shape production never produces. Every accept below is driven with the ``id``
  read out of the session's own payload rather than composed here
- an accept MOVES the day-shape entry the pattern names, and moves nothing else about it
- an accept bumps the input version of future weeks, because a day shape is a solve input with no
  end date, and leaves a past week alone
- **nothing reaches the template without an accept**: the session's read and a decline both leave
  every entry where it was
- a decline silences the pattern for a stated interval, and the same pattern is raised again once
  the interval has lapsed
- a pattern the template cannot absorb is refused with the reason, and refused without writing
- another tenant's decline silences nothing of this one's

A pin is seeded through ``PinRepository`` because a pin route needs a rendered block to drag, and a
plan of record is seeded through ``PlanRepository`` because materialization is deliberately not a
user-facing act.
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
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.plans.declarations import PinToHold
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.versions import WeekInputVersionRepository
from syncr_api.promotions.config import (
    DECLINE_SUPPRESSION_WEEKS,
    PROMOTION_ID_FIELD,
    PROMOTION_ID_MAX_LENGTH,
    PROMOTIONS_PREFIX,
)
from syncr_api.promotions.models import PromotionDecline
from syncr_api.promotions.repository import PromotionDeclineRepository
from syncr_api.reviews.config import REVIEWS_PREFIX
from syncr_api.templates.config import DAY_TYPES_PREFIX, TEMPLATES_PREFIX, WEEK_PATTERN_PREFIX
from syncr_api.templates.models import TemplateEntryRow
from syncr_domain.identity import BindingRef, block_id
from syncr_domain.intervals import Interval
from syncr_domain.templates import Weekday
from syncr_domain.weeks import IsoWeek
from tests.live_tenants import PASSWORD, provision_owner, remove_tenant, run

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from syncr_api.accounts.records import UserRecord
    from syncr_api.core.settings import ServiceSettings
    from syncr_domain.identifiers import TenantId
    from syncr_domain.zones import Date

pytestmark = pytest.mark.integration

BROWSER_ORIGIN = DEV_ALLOWED_ORIGINS[0]

# Yesterday, so the reviewed week is behind `now` and the window the pins are read over holds it.
YESTERDAY = (utc_now() - timedelta(days=1)).date()
REVIEWED = IsoWeek.containing(YESTERDAY)
PLANNED = REVIEWED.following()
PINNED_WEEKS = (REVIEWED.preceding().preceding(), REVIEWED.preceding(), REVIEWED)

# The week an accept's invalidation is measured on, resolved against the production clock: the
# re-solve floor is the week holding today's local date, and a week seeded against a fixed instant
# would be in the past by the time the route ran.
TRACKED_WEEK = IsoWeek.containing(datetime.now(UTC).date())
A_PAST_WEEK = IsoWeek.containing(datetime.now(UTC).date() - timedelta(days=28))

# The entry every pattern below is about: declared at 07:00, pinned to 13:00 three weeks running.
DECLARED_AT = "07:00"
PINNED_HOUR = 13


def accept_path(promotion_id: str) -> str:
    return f"{PROMOTIONS_PREFIX}/{promotion_id}/accept"


def decline_path(promotion_id: str) -> str:
    return f"{PROMOTIONS_PREFIX}/{promotion_id}/decline"


def session_path(iso_week: object) -> str:
    return f"{REVIEWS_PREFIX}/week/{iso_week}"


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
    return _sign_in(http, owner.email)


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


# --------------------------------------------------------------------------------
# What a tenant has to hold for a pattern to exist at all
# --------------------------------------------------------------------------------


def declare_an_area(http: TestClient, headers: dict[str, str]) -> UUID:
    answered = http.post(
        AREAS_PREFIX,
        json={"name": "Fitness", "budgetPercent": str(Decimal(50)), "floorHours": "2"},
        headers=headers,
    )
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return UUID(answered.json()["area"]["id"])


def declare_a_day_shape(http: TestClient, headers: dict[str, str], *, mapped: bool = True) -> str:
    """A day type, its shape, and the pattern that maps every weekday to it.

    ``mapped`` False leaves the pattern undeclared, which is a tenant who has shaped a day and not
    yet said which days use it: an edit to that shape reaches no week.
    """
    day_type = http.post(DAY_TYPES_PREFIX, json={"name": "Weekday"}, headers=headers)
    assert day_type.status_code == HTTPStatus.CREATED, day_type.text
    day_type_id = day_type.json()["id"]
    shape = http.post(
        TEMPLATES_PREFIX,
        json={"dayTypeId": day_type_id, "name": "Weekday"},
        headers=headers,
    )
    assert shape.status_code == HTTPStatus.CREATED, shape.text
    if mapped:
        pattern = http.put(
            WEEK_PATTERN_PREFIX,
            json={weekday.value: day_type_id for weekday in Weekday},
            headers=headers,
        )
        assert pattern.status_code == HTTPStatus.OK, pattern.text
    identifier: str = shape.json()["id"]
    return identifier


def declare_an_entry(
    http: TestClient, headers: dict[str, str], template_id: str, *, area_id: UUID
) -> str:
    """One concrete entry of the shape, bound to a habit, at the declared time."""
    answered = http.post(
        f"{TEMPLATES_PREFIX}/{template_id}/entries",
        json={
            "kind": "concrete",
            "targetTime": f"{DECLARED_AT}:00",
            "durationMinutes": 60,
            "flexBandMinutes": 15,
            "bindingTarget": "habit",
            "bindingRef": str(uuid4()),
            "areaId": str(area_id),
        },
        headers=headers,
    )
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    identifier: str = answered.json()["id"]
    return identifier


def an_instant(on: Date, hour: int) -> datetime:
    return datetime.combine(on, time(hour), tzinfo=UTC)


def seed_pins(
    database_url: str,
    tenant_id: TenantId,
    weeks: Sequence[IsoWeek],
    *,
    binding_of: Callable[[Date, int], BindingRef],
    hour: int = PINNED_HOUR,
) -> None:
    """One pin of the same content at the same local time in each of ``weeks``.

    ``binding_of`` takes the week's Monday and the week's position in the run, because the two kinds
    of binding a pattern can be about are keyed differently: an entry by the date it materialized
    for, and a habit occurrence by its index in that week's expansion.
    """

    async def hold() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                pins = PinRepository(session, tenant_id)
                for offset, week in enumerate(weeks):
                    monday = week.monday()
                    binding = binding_of(monday, offset)
                    await pins.hold(
                        PinToHold(
                            iso_week=week,
                            block_id=block_id(week, binding),
                            binding=binding,
                            interval=Interval(
                                an_instant(monday, hour), an_instant(monday, hour + 1)
                            ),
                            superseded_placement=Interval(
                                an_instant(monday, 7), an_instant(monday, 8)
                            ),
                            weight_set_version=1,
                            created_at=utc_now(),
                        )
                    )
        finally:
            await database.engine.dispose()

    run(hold())


def seed_an_entry_pattern(
    http: TestClient, headers: dict[str, str], database_url: str, tenant_id: TenantId
) -> str:
    """A shape with one entry, pinned to 13:00 for three consecutive weeks. Answers the entry id."""
    area_id = declare_an_area(http, headers)
    template_id = declare_a_day_shape(http, headers)
    entry_id = declare_an_entry(http, headers, template_id, area_id=area_id)
    seed_pins(
        database_url,
        tenant_id,
        PINNED_WEEKS,
        binding_of=lambda monday, _offset: BindingRef.for_template_entry(UUID(entry_id), on=monday),
    )
    return entry_id


def seed_a_habit_pattern(
    http: TestClient, headers: dict[str, str], database_url: str, tenant_id: TenantId
) -> None:
    """A habit pinned to 13:00 for three consecutive weeks, which no day-shape entry holds.

    The occurrence index differs per week, as a real expansion's does, which is the half of the
    grouping that has to be dropped for the pattern to be found at all.
    """
    declare_an_area(http, headers)
    habit_id = uuid4()
    seed_pins(
        database_url,
        tenant_id,
        PINNED_WEEKS,
        binding_of=lambda _monday, offset: BindingRef.for_habit(habit_id, index=offset),
    )


def seed_tracked_weeks(database_url: str, tenant_id: TenantId) -> None:
    """One future week and one past week the invalidation is measured against."""

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                versions = WeekInputVersionRepository(session, tenant_id)
                await versions.bump(TRACKED_WEEK, at=utc_now())
                await versions.bump(A_PAST_WEEK, at=utc_now())
        finally:
            await database.engine.dispose()

    run(seed())


def version_of(database_url: str, tenant_id: TenantId, week: IsoWeek) -> int | None:
    async def read() -> int | None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                return await WeekInputVersionRepository(session, tenant_id).current(week)
        finally:
            await database.engine.dispose()

    return run(read())


def entry_rows(database_url: str, tenant_id: TenantId) -> list[TemplateEntryRow]:
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


def decline_rows(database_url: str, tenant_id: TenantId) -> list[PromotionDecline]:
    async def read() -> list[PromotionDecline]:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session:
                found = await session.scalars(
                    select(PromotionDecline).where(PromotionDecline.tenant_id == tenant_id)
                )
                return list(found)
        finally:
            await database.engine.dispose()

    return run(read())


def seed_a_lapsed_decline(database_url: str, tenant_id: TenantId, promotion_id: str) -> None:
    """A decline whose suppression has already run out, which is the far edge of the read.

    Written through the repository the route writes through, with instants in the past: waiting a
    quarter is not a test, and reproducing the write by hand would be a second spelling of the row.
    """

    async def seed() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                now = utc_now()
                await PromotionDeclineRepository(session, tenant_id).decline(
                    promotion_id,
                    at=now - timedelta(weeks=DECLINE_SUPPRESSION_WEEKS + 1),
                    until=now - timedelta(minutes=1),
                )
        finally:
            await database.engine.dispose()

    run(seed())


def promotions_in(http: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    answered = http.get(session_path(PLANNED), headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    raised: list[dict[str, Any]] = answered.json()["promotions"]
    return raised


def the_one_promotion(http: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    (candidate,) = promotions_in(http, headers)
    return candidate


# --------------------------------------------------------------------------------
# The paths, and the identifier that crosses them
# --------------------------------------------------------------------------------


class TestTheTwoPathsAreTheOnesTheCriterionNames:
    def test_the_app_registers_both(self, settings: ServiceSettings) -> None:
        document = create_app(settings).openapi()

        assert f"{PROMOTIONS_PREFIX}/{{promotion_id}}/accept" in document["paths"]
        assert f"{PROMOTIONS_PREFIX}/{{promotion_id}}/decline" in document["paths"]
        assert {"PromotionAcceptedResponse", "PromotionDeclinedResponse"} <= set(
            document["components"]["schemas"]
        )

    def test_the_identifier_the_session_emits_is_the_one_the_routes_take(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        """The crossing that makes every other case here about production rather than a fixture.

        Nothing stores a candidate, so the identifier is derived at both ends: the session renders
        it from the group the rule found, and the route parses it back. Composing one in this file
        would prove the routes against a shape the payload might not produce.
        """
        entry_id = seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)

        candidate = the_one_promotion(http, signed_in)

        assert candidate["id"] == f"template_entry:{entry_id}:1:{PINNED_HOUR * 60}"
        assert candidate["localTime"] == f"{PINNED_HOUR}:00"
        assert candidate["consecutiveWeeks"] == len(PINNED_WEEKS)
        assert candidate["acceptRefusal"] is None
        assert http.post(accept_path(candidate["id"]), headers=signed_in).status_code == (
            HTTPStatus.OK
        )


# --------------------------------------------------------------------------------
# The accept
# --------------------------------------------------------------------------------


class TestTheAcceptMovesTheEntryThePatternNames:
    def test_it_moves_the_entry_and_changes_nothing_else_about_it(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        entry_id = seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        answered = http.post(accept_path(candidate["id"]), headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, answered.text
        body = answered.json()
        assert body["promotionId"] == candidate["id"]
        assert body["entry"]["id"] == entry_id
        assert body["entry"]["targetTime"] == f"{PINNED_HOUR}:00:00"
        # A promotion moves an entry and never resizes one.
        assert body["entry"]["durationMinutes"] == 60
        assert body["entry"]["flexBandMinutes"] == 15
        assert DECLARED_AT in body["statement"]
        assert "Weekday" in body["statement"]

    def test_the_row_itself_moved(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        http.post(accept_path(candidate["id"]), headers=signed_in)

        (row,) = entry_rows(live_database_url, owner.tenant_id)
        assert row.target_time == time(PINNED_HOUR, 0)

    def test_it_invalidates_future_weeks_and_leaves_a_past_week_alone(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        """A day shape is a solve input with no end date, so an accept is a bump from this week on.

        The same rule every day-shape mutation takes, which is why the accept delegates rather than
        writing: a past week's approved revision keeps the inputs it was computed with.
        """
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        seed_tracked_weeks(live_database_url, owner.tenant_id)
        before = version_of(live_database_url, owner.tenant_id, TRACKED_WEEK)
        past_before = version_of(live_database_url, owner.tenant_id, A_PAST_WEEK)
        candidate = the_one_promotion(http, signed_in)

        http.post(accept_path(candidate["id"]), headers=signed_in)

        assert before is not None
        assert version_of(live_database_url, owner.tenant_id, TRACKED_WEEK) == before + 1
        assert version_of(live_database_url, owner.tenant_id, A_PAST_WEEK) == past_before

    def test_a_second_accept_of_one_pattern_is_the_same_state(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        """Which is why neither route takes the idempotency guard: the value is stated, not
        applied."""
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        first = http.post(accept_path(candidate["id"]), headers=signed_in)
        second = http.post(accept_path(candidate["id"]), headers=signed_in)

        assert first.status_code == HTTPStatus.OK, first.text
        assert second.status_code == HTTPStatus.OK, second.text
        assert first.json()["entry"] == second.json()["entry"]


class TestWhatTheAcceptRefuses:
    def test_a_pattern_no_day_shape_entry_holds_is_refused_with_the_reason(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        """A habit the solver places is a real pattern with nothing to move.

        The raise carries the same sentence the refusal does, so the screen draws no accept control
        for it: this drives the route a caller reaches anyway.
        """
        seed_a_habit_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        assert candidate["acceptRefusal"] is not None
        assert "no entry to move" in candidate["acceptRefusal"]

        answered = http.post(accept_path(candidate["id"]), headers=signed_in)

        assert answered.status_code == HTTPStatus.CONFLICT, answered.text
        assert "no entry to move" in answered.json()["detail"]

    def test_an_entry_removed_since_the_pattern_was_found_is_a_conflict(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        template_id = declare_a_day_shape(http, signed_in)
        entry_id = declare_an_entry(
            http, signed_in, template_id, area_id=declare_an_area(http, signed_in)
        )
        seed_pins(
            live_database_url,
            owner.tenant_id,
            PINNED_WEEKS,
            binding_of=lambda monday, _offset: BindingRef.for_template_entry(
                UUID(entry_id), on=monday
            ),
        )
        candidate = the_one_promotion(http, signed_in)
        removed = http.delete(
            f"{TEMPLATES_PREFIX}/{template_id}/entries/{entry_id}", headers=signed_in
        )
        assert removed.status_code == HTTPStatus.NO_CONTENT, removed.text

        answered = http.post(accept_path(candidate["id"]), headers=signed_in)

        assert answered.status_code == HTTPStatus.CONFLICT, answered.text
        assert "no longer declared" in answered.json()["detail"]

    @pytest.mark.parametrize(
        "malformed", ["nonsense", "habit:not-a-uuid:2:780", f"habit:{uuid4()}:9:780"]
    )
    def test_an_identifier_this_product_did_not_produce_is_a_422_naming_the_field(
        self, http: TestClient, signed_in: dict[str, str], malformed: str
    ) -> None:
        answered = http.post(accept_path(malformed), headers=signed_in)

        assert answered.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, answered.text
        body = answered.json()
        assert body["errors"][0]["field"] == PROMOTION_ID_FIELD
        assert "Nothing was changed." in body["detail"]

    def test_a_value_longer_than_any_identifier_is_refused_by_the_route_s_own_bound(
        self, http: TestClient, signed_in: dict[str, str]
    ) -> None:
        """The framework's bound rather than a second one in this package.

        ``Path(max_length=...)`` is the mechanism FastAPI already has for this, and it answers
        before the parse: a megabyte-long segment costs one comparison and never reaches a
        statement. Its 422 names the parameter the way the framework spells a path parameter, which
        is what every other bounded path parameter in this api answers with.
        """
        answered = http.post(accept_path("x" * (PROMOTION_ID_MAX_LENGTH + 1)), headers=signed_in)

        assert answered.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, answered.text
        assert answered.json()["errors"][0]["field"] == "path.promotion_id"

    def test_a_time_off_the_snap_grid_is_a_conflict_rather_than_a_moved_entry(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        """No pin can produce one, and a forged identifier must not write an unplaceable entry.

        A pin lands on the grid, so this shape is unreachable from a real pattern; what makes it
        worth a case is that the value arrives in a PATH rather than in a body, so the span's own
        422 has no field to name.
        """
        template_id = declare_a_day_shape(http, signed_in)
        entry_id = declare_an_entry(
            http, signed_in, template_id, area_id=declare_an_area(http, signed_in)
        )

        answered = http.post(accept_path(f"template_entry:{entry_id}:1:787"), headers=signed_in)

        assert answered.status_code == HTTPStatus.CONFLICT, answered.text
        assert "quarter hour" in answered.json()["detail"]
        (row,) = entry_rows(live_database_url, owner.tenant_id)
        assert row.target_time == time(7, 0)

    def test_another_tenant_s_entry_is_not_reachable(
        self,
        http: TestClient,
        owner: UserRecord,
        other_owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        mine = seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        theirs = _sign_in(http, other_owner.email)

        answered = http.post(accept_path(f"template_entry:{mine}:1:780"), headers=theirs)

        assert answered.status_code == HTTPStatus.CONFLICT, answered.text
        (row,) = entry_rows(live_database_url, owner.tenant_id)
        assert row.target_time == time(7, 0)


# --------------------------------------------------------------------------------
# The decline, and the interval it suppresses for
# --------------------------------------------------------------------------------


class TestTheDeclineSuppressesTheCandidate:
    def test_declining_and_re_reading_does_not_raise_it_again(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        """`US-TPL-05`: declining does not re-raise for a stated interval.

        Detection is re-run on every read of the payload, so this is the criterion's own words: the
        pins are untouched, the pattern is still found, and the question is not asked.
        """
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        answered = http.post(decline_path(candidate["id"]), headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, answered.text
        assert promotions_in(http, signed_in) == []

    def test_nothing_reached_the_template(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        http.post(decline_path(candidate["id"]), headers=signed_in)

        (row,) = entry_rows(live_database_url, owner.tenant_id)
        assert row.target_time == time(7, 0)

    def test_it_states_the_interval_and_the_instant_it_lapses(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        body = http.post(decline_path(candidate["id"]), headers=signed_in).json()

        assert body["suppressionWeeks"] == DECLINE_SUPPRESSION_WEEKS
        lapses = datetime.fromisoformat(body["suppressedUntil"])
        answered = datetime.fromisoformat(body["declinedAt"])
        assert lapses - answered == timedelta(weeks=DECLINE_SUPPRESSION_WEEKS)
        assert lapses.date().isoformat() in body["statement"]
        assert "Nothing was changed" in body["statement"]

    def test_the_same_pattern_is_raised_again_once_the_suppression_has_lapsed(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        """The other side of the interval, which is what makes it an interval rather than a mute."""
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)
        seed_a_lapsed_decline(live_database_url, owner.tenant_id, candidate["id"])

        assert the_one_promotion(http, signed_in)["id"] == candidate["id"]

    def test_declining_twice_is_one_answer_given_twice(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        first = http.post(decline_path(candidate["id"]), headers=signed_in).json()
        second = http.post(decline_path(candidate["id"]), headers=signed_in).json()

        rows = decline_rows(live_database_url, owner.tenant_id)
        assert len(rows) == 1
        assert rows[0].suppressed_until == datetime.fromisoformat(second["suppressedUntil"])
        assert first["suppressedUntil"] <= second["suppressedUntil"]

    def test_another_tenant_s_decline_silences_nothing_of_this_one_s(
        self,
        http: TestClient,
        owner: UserRecord,
        other_owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        seed_an_entry_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)
        theirs = _sign_in(http, other_owner.email)
        declared = http.post(decline_path(candidate["id"]), headers=theirs)
        assert declared.status_code == HTTPStatus.OK, declared.text

        assert the_one_promotion(http, signed_in)["id"] == candidate["id"]

    def test_a_pattern_the_template_cannot_absorb_can_still_be_declined(
        self,
        http: TestClient,
        owner: UserRecord,
        signed_in: dict[str, str],
        live_database_url: str,
    ) -> None:
        """Which is the reason the decline takes no absorption check: the answer is about the
        ASKING.

        A habit pinned three weeks running is a pattern the reader may not want to be asked about
        again, and refusing the decline because the accept would refuse would leave it nagging.
        """
        seed_a_habit_pattern(http, signed_in, live_database_url, owner.tenant_id)
        candidate = the_one_promotion(http, signed_in)

        answered = http.post(decline_path(candidate["id"]), headers=signed_in)

        assert answered.status_code == HTTPStatus.OK, answered.text
        assert promotions_in(http, signed_in) == []
