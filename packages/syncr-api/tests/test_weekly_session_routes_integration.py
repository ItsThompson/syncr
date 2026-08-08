"""The weekly session's payload end to end, against a real Postgres and a real request.

The rules suite proves the counting over hand-built values. This proves what only a real request and
a real database can:

- the payload is addressed by the week it PLANS, and the retrospective covers the week before it,
  which is what ``US-REV-01``'s "planning and retrospective in one pass" means on the wire
- **it writes nothing at all**: no revision, no outcome, no week input version, and no
  ``VerdictEvent``. Driven twice, because a read that wrote on the first call and not the second
  would pass a one-call guard: the recorder writes only on a TRANSITION
- the verdict it carries is the same one ``/api/v1/weeks/{iso_week}`` serves, byte for byte, which
  is what makes the session and the Week screen one reading rather than two that agree today
- every review states its confirmed and unconfirmed day counts and reports off-plan days separately
- a chronic skip is raised from six weeks of confirmed skips written through the outcome log
- a repeated collision survives the anchor rows a horizon roll deletes
- a repeated pin over three consecutive weeks reaches the payload as a promotion candidate, which
  the nightly learning run finds through the same domain rule
- another tenant's week is not this tenant's session

A plan of record is seeded through ``PlanRepository`` because materialization is deliberately not a
user-facing act: there is no route that creates a plan, and there is not meant to be one.
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
from syncr_api.concessions.config import WEEKS_PREFIX
from syncr_api.core.app_factory import create_app
from syncr_api.core.clock import utc_now
from syncr_api.core.db import create_database, create_db_lifespan
from syncr_api.core.settings import DEV_ALLOWED_ORIGINS
from syncr_api.plans.config import APPLIED
from syncr_api.plans.conflicts import Commitment, PlanConflictRepository
from syncr_api.plans.declarations import PinToHold
from syncr_api.plans.facts import BlockOutcome, VerdictEvent
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.overlaps import DetectedConflict
from syncr_api.plans.pins import PinRepository
from syncr_api.plans.reality import BlockOutcomeRepository, Presumption
from syncr_api.plans.repository import PlanRepository
from syncr_api.plans.stored_documents import stored_document
from syncr_api.reviews.config import REVIEWS_PREFIX, SESSION_LOOKBACK_WEEKS
from syncr_api.reviews.raised import RaisedKind
from syncr_api.user_settings.config import SETTINGS_PREFIX
from syncr_domain.habits import BindingSource
from syncr_domain.identity import BindingRef, block_id
from syncr_domain.intervals import Interval
from syncr_domain.outcomes import OutcomeState, RecordedOutcome
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

# Yesterday, so every block the reviewed week plans is behind `now` and its day can be confirmed.
YESTERDAY = (utc_now() - timedelta(days=1)).date()
REVIEWED = IsoWeek.containing(YESTERDAY)
PLANNED = REVIEWED.following()

# The six consecutive weeks a chronic skip is raised on, ending with the reviewed week.
SKIP_WEEKS = 6
DISCRETIONARY_MINUTES = 6720

# One habit and one task, held as identities so a run over six weeks names one thing.
GYM = uuid4()
LEETCODE = uuid4()


def session_path(iso_week: object) -> str:
    return f"{REVIEWS_PREFIX}/week/{iso_week}"


def an_instant(on: Date, hour: int) -> datetime:
    return datetime.combine(on, time(hour), tzinfo=UTC)


def a_habit_block(
    *, iso_week: IsoWeek, area_id: AreaId, index: int = 0, title: str = "Gym", hour: int = 9
) -> Block:
    """One habit occurrence, on the reviewed week's own Monday so its day has begun."""
    on = iso_week.monday()
    return Block(
        iso_week=iso_week,
        interval=Interval(an_instant(on, hour), an_instant(on, hour + 1)),
        binding=BindingRef.for_habit(GYM, index=index),
        title=title,
        reason=A_REASON,
        area_id=area_id,
    )


def a_task_block(*, iso_week: IsoWeek, area_id: AreaId, title: str = "Leetcode") -> Block:
    """The block a collision lands on, which is where its NAME comes from.

    A conflict row stores the binding it collided with and no title, so the only name the raise can
    give the block is the one a block of the window carries. That is the production shape as well: a
    collision exists because the week planned something for the commitment to land on.
    """
    on = iso_week.monday()
    return Block(
        iso_week=iso_week,
        interval=Interval(an_instant(on, 9), an_instant(on, 10)),
        binding=BindingRef.for_task(LEETCODE),
        title=title,
        reason=A_REASON,
        area_id=area_id,
    )


def a_week(blocks: Sequence[Block], *, iso_week: IsoWeek) -> PlanDocument:
    return PlanDocument(
        iso_week=iso_week,
        zone_by_date=active_zone_by_date(iso_week, ZoneProfile(UTC_ZONE)),
        discretionary_minutes=DISCRETIONARY_MINUTES,
        unallocated_minutes=DISCRETIONARY_MINUTES,
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


def declare_area(http: TestClient, headers: dict[str, str], name: str = "Fitness") -> AreaId:
    answered = http.post(
        AREAS_PREFIX,
        json={"name": name, "budgetPercent": str(Decimal(50)), "floorHours": "2"},
        headers=headers,
    )
    assert answered.status_code == HTTPStatus.CREATED, answered.text
    return UUID(answered.json()["area"]["id"])


def seed_plan(database_url: str, tenant_id: TenantId, document: PlanDocument) -> UUID:
    """One applied revision holding ``document``, and the identifier the outcome log references."""

    async def append() -> UUID:
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
                return revision.id
        finally:
            await database.engine.dispose()

    return run(append())


def seed_skips(
    database_url: str, tenant_id: TenantId, recorded: Sequence[tuple[Block, UUID]]
) -> None:
    """One CONFIRMED skip per block, written through the log's own two writers.

    ``record`` states what happened and ``settle`` stamps the day, which is the pair the Today
    screen drives: a skip is the exception the user recorded and the confirmation is the day they
    answered for. Both are needed here, because an unconfirmed block is presumed and no raise in
    this product counts a presumption -- the narrowing ``syncr_domain.debt`` states and the
    chronic-skip run takes.

    Each block arrives with the revision that planned it, because the log references it: an invented
    identifier is refused by the schema, which is the schema holding the log to plans that exist.
    """

    async def record() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                outcomes = BlockOutcomeRepository(session, tenant_id)
                for block, revision_id in recorded:
                    await outcomes.record(
                        RecordedOutcome(binding=block.binding, state=OutcomeState.SKIPPED),
                        block_id=block.id,
                        revision_id=revision_id,
                        occurred_at=block.interval.start,
                    )
                await outcomes.settle(
                    [
                        Presumption(
                            block_id=block.id,
                            binding=block.binding,
                            revision_id=revision_id,
                            occurred_at=block.interval.start,
                        )
                        for block, revision_id in recorded
                    ],
                    at=utc_now(),
                )
        finally:
            await database.engine.dispose()

    run(record())


def seed_collisions(
    database_url: str, tenant_id: TenantId, weeks: Sequence[IsoWeek], *, series: str | None
) -> None:
    """One resolved conflict per week, each naming a DIFFERENT anchor of one series.

    Different anchors on purpose: a weekly commitment publishes a distinct occurrence per week, and
    the anchor rows are never created at all, which is the state a horizon roll leaves behind.
    """

    async def raise_them() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                conflicts = PlanConflictRepository(session, tenant_id)
                for week in weeks:
                    monday = week.monday()
                    detected = DetectedConflict(
                        anchor_id=uuid4(),
                        iso_week=week,
                        binding=BindingRef.for_task(LEETCODE),
                        overlap=Interval(an_instant(monday, 9), an_instant(monday, 10)),
                    )
                    await conflicts.raise_all(
                        [detected],
                        at=utc_now(),
                        commitments={
                            detected.anchor_id: Commitment(series_uid=series, title="Standup")
                        },
                    )
        finally:
            await database.engine.dispose()

    run(raise_them())


def seed_pins(database_url: str, tenant_id: TenantId, weeks: Sequence[IsoWeek]) -> None:
    """One pin of the same content at the same local time in each of ``weeks``."""

    async def hold() -> None:
        database = create_database(database_url)
        try:
            async with database.sessionmaker() as session, session.begin():
                pins = PinRepository(session, tenant_id)
                for offset, week in enumerate(weeks):
                    monday = week.monday()
                    placed = Interval(an_instant(monday, 13), an_instant(monday, 14))
                    binding = BindingRef.for_habit(GYM, index=offset)
                    await pins.hold(
                        PinToHold(
                            iso_week=week,
                            block_id=block_id(week, binding),
                            binding=binding,
                            interval=placed,
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


def rows_of(
    database_url: str,
    tenant_id: TenantId,
    model: type[PlanRevision] | type[BlockOutcome] | type[VerdictEvent],
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


def read_session(http: TestClient, headers: dict[str, str], iso_week: object) -> dict[str, Any]:
    answered = http.get(session_path(iso_week), headers=headers)
    assert answered.status_code == HTTPStatus.OK, answered.text
    payload: dict[str, Any] = answered.json()
    return payload


def items_of(payload: dict[str, Any], kind: RaisedKind) -> list[dict[str, Any]]:
    return [one for one in payload["raised"] if one["kind"] == kind.value]


# --------------------------------------------------------------------------------
# The two halves, and the week each is about
# --------------------------------------------------------------------------------


def test_the_payload_plans_one_week_and_reviews_the_week_before_it(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    area_id = declare_area(http, signed_in)
    seed_plan(live_database_url, owner.tenant_id, a_week((), iso_week=PLANNED))
    seed_plan(
        live_database_url,
        owner.tenant_id,
        a_week([a_habit_block(iso_week=REVIEWED, area_id=area_id)], iso_week=REVIEWED),
    )

    payload = read_session(http, signed_in, PLANNED)

    assert payload["isoWeek"] == str(PLANNED)
    assert payload["retro"]["period"] == str(REVIEWED)
    assert [row["areaId"] for row in payload["retro"]["categories"]] == [str(area_id), None]


def test_every_review_states_its_confirmed_and_unconfirmed_days(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """``US-REV-04``, over a week holding one unconfirmed block and nothing else."""
    area_id = declare_area(http, signed_in)
    seed_plan(
        live_database_url,
        owner.tenant_id,
        a_week([a_habit_block(iso_week=REVIEWED, area_id=area_id)], iso_week=REVIEWED),
    )

    payload = read_session(http, signed_in, PLANNED)

    assert payload["retro"]["days"] == {
        "confirmed": 0,
        "unconfirmed": 1,
        "offPlan": 0,
        "statement": payload["retro"]["days"]["statement"],
    }
    assert "No day of this period was answered for" in payload["retro"]["statement"]


def test_a_week_with_no_plan_carries_no_verdict(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """The biconditional the week's own read states, over a week the horizon has not reached.

    The payload states no sentence about it, deliberately: the Week screen answers such a week with
    its own empty state, which names the reason and carries the two actions that fix it, and the
    mode is a branch of the READY screen. A second sentence here would be a claim nothing renders.
    """
    declare_area(http, signed_in)

    payload = read_session(http, signed_in, PLANNED)

    assert payload["verdict"] is None
    assert payload["raised"] == []


# --------------------------------------------------------------------------------
# VE6: the payload writes nothing, including no VerdictEvent
# --------------------------------------------------------------------------------


def test_reading_the_session_writes_nothing_however_often_it_is_driven(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """``VE6``, driven twice, over a week that really carries a verdict.

    Twice, because the transition recorder writes only on a CHANGE: a read that recorded would write
    one row and then be quiet, which counting once after one call cannot tell from writing none. The
    assertion that a verdict was computed is beside the counts, because zero rows written by a path
    that computed nothing is not evidence of anything.
    """
    area_id = declare_area(http, signed_in)
    seed_plan(
        live_database_url,
        owner.tenant_id,
        a_week([a_habit_block(iso_week=PLANNED, area_id=area_id)], iso_week=PLANNED),
    )
    before = {
        model: rows_of(live_database_url, owner.tenant_id, model)
        for model in (PlanRevision, BlockOutcome, VerdictEvent)
    }

    first = read_session(http, signed_in, PLANNED)
    read_session(http, signed_in, PLANNED)

    assert first["verdict"] is not None, "the payload carried no verdict, so this guard is armed"
    for model, held in before.items():
        assert rows_of(live_database_url, owner.tenant_id, model) == held, model.__name__


def test_the_verdict_it_carries_is_the_one_the_week_view_serves(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """One computation rather than two that agree today: it is why the session reads that view."""
    area_id = declare_area(http, signed_in)
    seed_plan(
        live_database_url,
        owner.tenant_id,
        a_week([a_habit_block(iso_week=PLANNED, area_id=area_id)], iso_week=PLANNED),
    )

    session = read_session(http, signed_in, PLANNED)
    answered = http.get(f"{WEEKS_PREFIX}/{PLANNED}", headers=signed_in)
    assert answered.status_code == HTTPStatus.OK, answered.text

    week = answered.json()
    assert session["verdict"]["feasible"] == week["verdict"]["feasible"]
    assert session["verdict"]["shortfalls"] == week["verdict"]["shortfalls"]
    assert session["verdict"]["provenance"] == week["verdict"]["provenance"]
    assert session["inputVersion"] == week["inputVersion"]


# --------------------------------------------------------------------------------
# The raised items, each from rows a production path writes
# --------------------------------------------------------------------------------


def test_six_weeks_of_confirmed_skips_are_raised_and_nothing_is_deprioritized(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """``US-REV-02``, written through the outcome log's own writer rather than seeded as rows."""
    area_id = declare_area(http, signed_in)
    weeks = [REVIEWED]
    for _ in range(SKIP_WEEKS - 1):
        weeks.append(weeks[-1].preceding())
    blocks = [
        a_habit_block(iso_week=week, area_id=area_id, index=offset)
        for offset, week in enumerate(reversed(weeks))
    ]
    recorded = [
        (
            block,
            seed_plan(live_database_url, owner.tenant_id, a_week([block], iso_week=block.iso_week)),
        )
        for block in blocks
    ]
    seed_skips(live_database_url, owner.tenant_id, recorded)

    payload = read_session(http, signed_in, PLANNED)

    (raised,) = items_of(payload, RaisedKind.CHRONIC_SKIP)
    assert raised["title"] == "Gym"
    assert f"skipped in {SKIP_WEEKS} weeks running" in raised["statement"]
    assert "has not changed its priority" in raised["statement"]


def test_a_repeated_collision_names_the_commitment_the_block_and_the_count(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """``US-REV-05``, and ticket 1390's own acceptance: NO anchor row exists at all.

    The block's name comes from the blocks of the reviewed window, because the conflict row stores a
    binding and no title. So each week is planned with the block the commitment landed on, which is
    the shape that produced the collision in the first place.
    """
    area_id = declare_area(http, signed_in)
    weeks = [REVIEWED.preceding().preceding(), REVIEWED.preceding(), REVIEWED]
    for week in weeks:
        seed_plan(
            live_database_url,
            owner.tenant_id,
            a_week([a_task_block(iso_week=week, area_id=area_id)], iso_week=week),
        )
    seed_collisions(live_database_url, owner.tenant_id, weeks, series="standup-series")

    payload = read_session(http, signed_in, PLANNED)

    (raised,) = items_of(payload, RaisedKind.REPEATED_COLLISION)
    assert raised["title"] == "Standup over Leetcode"
    assert f"Standup has landed on Leetcode in {len(weeks)} weeks" in raised["statement"]
    assert "Stated rather than acted on" in raised["statement"]


def test_a_collision_outside_the_sessions_window_is_not_raised_at_all(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """A pattern the reader fixed long ago is not raised forever, because the rows are never pruned.

    The chronic-skip run and the repeated-pin run are both bounded to the session's own window, and
    this read is bounded to the same one: a raise about a pattern that outlived its period would be
    the nag every other rule in this module goes out of its way to forbid.
    """
    declare_area(http, signed_in)
    stale = REVIEWED
    for _ in range(SESSION_LOOKBACK_WEEKS):
        stale = stale.preceding()
    weeks = [stale, stale.preceding(), stale.preceding().preceding()]
    seed_collisions(live_database_url, owner.tenant_id, weeks, series="standup-series")

    assert items_of(read_session(http, signed_in, PLANNED), RaisedKind.REPEATED_COLLISION) == []


def test_a_pattern_whose_third_week_is_the_week_being_planned_is_raised(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """The near edge of the window, which the bound must NOT cut.

    Every other window read is about what has already happened, so the retrospective's window ends
    at the week before the one being planned. A collision is about a pattern the reader can still
    act on, and its third week is often the week in front of them: a bound that stopped at the
    reviewed week would leave exactly that pattern silent for the week it matters most.
    """
    area_id = declare_area(http, signed_in)
    weeks = [PLANNED.preceding().preceding(), PLANNED.preceding(), PLANNED]
    for week in weeks:
        seed_plan(
            live_database_url,
            owner.tenant_id,
            a_week([a_task_block(iso_week=week, area_id=area_id)], iso_week=week),
        )
    seed_collisions(live_database_url, owner.tenant_id, weeks, series="standup-series")

    (raised,) = items_of(read_session(http, signed_in, PLANNED), RaisedKind.REPEATED_COLLISION)

    assert raised["title"] == "Standup over Leetcode"
    assert f"Most recently {PLANNED}." in raised["statement"]


def test_a_one_off_commitment_never_contributes_to_a_repeated_collision(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    declare_area(http, signed_in)
    weeks = [REVIEWED, REVIEWED.preceding(), REVIEWED.preceding().preceding()]
    seed_collisions(live_database_url, owner.tenant_id, weeks, series=None)

    assert items_of(read_session(http, signed_in, PLANNED), RaisedKind.REPEATED_COLLISION) == []


def test_three_consecutive_weeks_of_one_pin_reach_the_payload_as_a_promotion_candidate(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """``US-TPL-05``, through the same domain rule the nightly learning run reads."""
    declare_area(http, signed_in)
    weeks = [REVIEWED.preceding().preceding(), REVIEWED.preceding(), REVIEWED]
    seed_pins(live_database_url, owner.tenant_id, weeks)

    payload = read_session(http, signed_in, PLANNED)

    (candidate,) = payload["promotions"]
    assert candidate["entityId"] == str(GYM)
    assert candidate["localTime"] == "13:00"
    assert candidate["consecutiveWeeks"] == len(weeks)
    assert candidate["weeks"] == [str(one) for one in weeks]
    assert "only when you accept it" in payload["promotionStatement"]


def test_a_promotion_candidate_is_named_by_the_api_and_falls_back_to_its_kind(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    """The name is resolved HERE, from the same blocks a repeated collision's block name comes from.

    A pin row stores a binding and no title, exactly as a conflict row does, so both surfaces of
    this payload ask one question and take one answer. The fallback is the reader's word for the
    kind, not the wire's token, which is what a client holding its own fallback got wrong.
    """
    area_id = declare_area(http, signed_in)
    weeks = [REVIEWED.preceding().preceding(), REVIEWED.preceding(), REVIEWED]
    seed_pins(live_database_url, owner.tenant_id, weeks)

    without_a_block = read_session(http, signed_in, PLANNED)
    assert without_a_block["promotions"][0]["title"] == "a habit"

    seed_plan(
        live_database_url,
        owner.tenant_id,
        a_week([a_habit_block(iso_week=REVIEWED, area_id=area_id)], iso_week=REVIEWED),
    )

    named = read_session(http, signed_in, PLANNED)
    assert named["promotions"][0]["title"] == "Gym"


def test_two_weeks_of_one_pin_are_below_the_threshold(
    http: TestClient, owner: UserRecord, signed_in: dict[str, str], live_database_url: str
) -> None:
    declare_area(http, signed_in)
    seed_pins(live_database_url, owner.tenant_id, [REVIEWED.preceding(), REVIEWED])

    assert read_session(http, signed_in, PLANNED)["promotions"] == []


# --------------------------------------------------------------------------------
# The credential, the shape, and another tenant's week
# --------------------------------------------------------------------------------


def test_reading_a_session_needs_a_credential(http: TestClient) -> None:
    answered = http.get(session_path(PLANNED))

    assert answered.status_code == HTTPStatus.UNAUTHORIZED


def test_a_malformed_week_names_the_parameter_the_caller_sent(
    http: TestClient, signed_in: dict[str, str]
) -> None:
    answered = http.get(session_path("2026-W99"), headers=signed_in)

    assert answered.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, answered.text
    assert "isoWeek" in answered.text


def test_one_tenants_plan_is_not_another_tenants_session(
    http: TestClient,
    owner: UserRecord,
    other_owner: UserRecord,
    signed_in: dict[str, str],
    live_database_url: str,
) -> None:
    area_id = declare_area(http, signed_in)
    seed_plan(
        live_database_url,
        other_owner.tenant_id,
        a_week([a_habit_block(iso_week=PLANNED, area_id=area_id)], iso_week=PLANNED),
    )

    payload = read_session(http, signed_in, PLANNED)

    assert payload["verdict"] is None
    assert payload["raised"] == []
